"""登录态持久化、跨会话一致性与接口安全防护。"""

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app import member_routes, membership
from app.main import app

PASSWORD = "password123"


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBERSHIP_DB_PATH", str(tmp_path / "session.sqlite3"))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("BILLING_PROVIDER", "fake")
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    member_routes._sent_at.clear()
    member_routes._login_failures.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str = "reader@example.com", password: str = PASSWORD) -> None:
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    if response.status_code == 409:
        response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    assert client.cookies.get("sx_session")


def buy(client: TestClient) -> None:
    url = client.post("/api/billing/checkout").json()["url"]
    order_id = url.rstrip("/").split("/")[-1]
    assert client.post("/api/billing/fake/pay", json={"order_id": order_id}).status_code == 200


def _session_expiry(token: str) -> float:
    conn = sqlite3.connect(membership.db_path())
    try:
        row = conn.execute(
            "SELECT expires_at FROM sessions WHERE token_hash = ?", (membership._hash(token),)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return row[0]


def test_me_is_never_cached(client):
    response = client.get("/api/me")
    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("no-store")
    assert "Cookie" in response.headers["vary"]


def test_login_cookie_is_httponly_and_long_lived(client):
    response = client.post("/api/auth/register", json={"email": "cookie@example.com", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert f"max-age={membership.SESSION_TTL_SECONDS}" in cookie
    assert "secure" not in cookie  # http 测试环境下不加 Secure，否则浏览器不会保存


def test_member_survives_logout_and_relogin(client):
    """核心回归：会员退出后重新登录，会员身份不能丢。"""
    login(client, "member@example.com")
    buy(client)
    assert client.get("/api/me").json()["member"] is True

    assert client.post("/api/auth/logout").status_code == 200
    me = client.get("/api/me").json()
    assert me["authenticated"] is False
    assert me["member"] is False

    # 同一邮箱重新登录，读写同一个 users.id，会员权益应仍然有效
    login(client, "member@example.com")
    me = client.get("/api/me").json()
    assert me["authenticated"] is True
    assert me["member"] is True
    assert me["limits"]["tier"] == "member"
    assert me["limits"]["max_file_label"] == "2GB"


def test_session_survives_browser_restart(client):
    """模拟关闭浏览器重开：Cookie 仍在，新客户端也能识别会员。"""
    login(client, "restart@example.com")
    buy(client)
    token = client.cookies.get("sx_session")

    reopened = TestClient(app)
    reopened.cookies.set("sx_session", token)
    me = reopened.get("/api/me").json()
    assert me["authenticated"] is True
    assert me["member"] is True


def test_session_is_renewed_near_expiry(client):
    login(client, "renew@example.com")
    token = client.cookies.get("sx_session")
    conn = sqlite3.connect(membership.db_path())
    try:
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
            (time.time() + 60, membership._hash(token)),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/me")
    assert response.status_code == 200
    assert "sx_session" in response.headers["set-cookie"]
    assert _session_expiry(token) > time.time() + membership.SESSION_TTL_SECONDS - 60


def test_session_ignores_forged_token(client):
    client.cookies.set("sx_session", "forged-token")
    me = client.get("/api/me").json()
    assert me["authenticated"] is False
    assert me["member"] is False


def test_cross_site_write_is_rejected(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "evil@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_same_origin_write_is_allowed(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "ok@example.com", "password": PASSWORD},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
