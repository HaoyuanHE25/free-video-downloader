"""邮箱 + 密码认证：注册、登录、错误提示、密码重置。"""

import sqlite3
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import member_routes, membership
from app.main import app

PASSWORD = "password123"


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBERSHIP_DB_PATH", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")
    monkeypatch.setenv("BILLING_PROVIDER", "fake")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    member_routes._sent_at.clear()
    member_routes._login_failures.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str = "new@example.com", password: str = PASSWORD):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str = "new@example.com", password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _reset_token(client: TestClient, email: str) -> str:
    response = client.post("/api/auth/request-reset", json={"email": email})
    assert response.status_code == 200
    query = parse_qs(urlparse(response.json()["reset_url"]).query)
    return query["reset"][0]


def test_register_creates_account_and_logs_in(client):
    response = register(client, "new@example.com")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "new@example.com"
    me = client.get("/api/me").json()
    assert me["authenticated"] is True
    assert me["member"] is False


def test_password_is_hashed_not_plaintext(client):
    register(client, "hash@example.com")
    conn = sqlite3.connect(membership.db_path())
    try:
        stored = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?", ("hash@example.com",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert stored != PASSWORD
    assert stored.startswith("$2")
    assert PASSWORD not in stored


def test_duplicate_email_is_rejected(client):
    assert register(client, "dup@example.com").status_code == 200
    response = register(client, "dup@example.com")
    assert response.status_code == 409
    assert "已经注册" in response.json()["detail"]


def test_short_password_is_rejected(client):
    response = register(client, "short@example.com", "1234567")
    assert response.status_code == 400
    assert "至少 8 位" in response.json()["detail"]


def test_wrong_password_then_correct_password(client):
    register(client, "right@example.com")
    client.post("/api/auth/logout")

    wrong = login(client, "right@example.com", "wrong-password")
    assert wrong.status_code == 401
    assert "不正确" in wrong.json()["detail"]
    assert client.get("/api/me").json()["authenticated"] is False

    ok = login(client, "right@example.com")
    assert ok.status_code == 200
    assert client.get("/api/me").json()["authenticated"] is True


def test_login_unknown_email_returns_same_error(client):
    response = login(client, "nobody@example.com")
    assert response.status_code == 401
    assert response.json()["detail"] == "邮箱或密码不正确"


def test_too_many_failed_logins_are_throttled(client):
    register(client, "brute@example.com")
    client.post("/api/auth/logout")
    for _ in range(member_routes._LOGIN_MAX_FAILURES):
        assert login(client, "brute@example.com", "bad-password").status_code == 401
    blocked = login(client, "brute@example.com")
    assert blocked.status_code == 429


def test_password_reset_full_flow(client):
    register(client, "forgot@example.com")
    client.post("/api/auth/logout")

    token = _reset_token(client, "forgot@example.com")
    response = client.post("/api/auth/reset", json={"token": token, "password": "brand-new-pass"})
    assert response.status_code == 200
    # 重置成功后自动登录
    assert client.get("/api/me").json()["authenticated"] is True

    client.post("/api/auth/logout")
    assert login(client, "forgot@example.com", PASSWORD).status_code == 401
    assert login(client, "forgot@example.com", "brand-new-pass").status_code == 200


def test_reset_token_can_only_be_used_once(client):
    register(client, "once@example.com")
    token = _reset_token(client, "once@example.com")
    assert client.post("/api/auth/reset", json={"token": token, "password": "first-new-pass"}).status_code == 200
    again = client.post("/api/auth/reset", json={"token": token, "password": "second-new-pass"})
    assert again.status_code == 400


def test_reset_token_expires(client, monkeypatch):
    register(client, "late@example.com")
    monkeypatch.setattr(membership, "RESET_TOKEN_TTL_SECONDS", -1)
    token = _reset_token(client, "late@example.com")
    response = client.post("/api/auth/reset", json={"token": token, "password": "too-late-pass"})
    assert response.status_code == 400


def test_reset_request_does_not_reveal_whether_email_exists(client):
    # 未注册邮箱也返回结构一致的链接，但 token 不落库，重置时会失败
    token = _reset_token(client, "ghost@example.com")
    response = client.post("/api/auth/reset", json={"token": token, "password": "whatever-pass"})
    assert response.status_code == 400
    assert "无效或已过期" in response.json()["detail"]


def test_reset_revokes_existing_sessions(client):
    register(client, "multi@example.com")
    old_token = client.cookies.get("sx_session")
    reset_token = _reset_token(client, "multi@example.com")
    assert client.post("/api/auth/reset", json={"token": reset_token, "password": "another-pass"}).status_code == 200

    other = TestClient(app)
    other.cookies.set("sx_session", old_token)
    assert other.get("/api/me").json()["authenticated"] is False


def test_legacy_account_without_password_cannot_login(client):
    """老的无密码账号作废：即使伪造出会话 Cookie 也无法通过校验。"""
    membership.session_user("probe")  # 先建库
    now = time.time()
    conn = sqlite3.connect(membership.db_path())
    try:
        conn.execute(
            "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
            ("u_legacy", "legacy@example.com", now),
        )
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (membership._hash("legacy-session"), "u_legacy", now, now + 3600),
        )
        conn.commit()
    finally:
        conn.close()

    client.cookies.set("sx_session", "legacy-session")
    assert client.get("/api/me").json()["authenticated"] is False
    assert login(client, "legacy@example.com").status_code == 401
