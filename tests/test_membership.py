import socket
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import billing, downloader, member_routes, membership
from app.jobs import store
from app.main import app


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBERSHIP_DB_PATH", str(tmp_path / "membership.sqlite3"))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("BILLING_PROVIDER", "fake")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")
    member_routes._sent_at.clear()
    member_routes._login_failures.clear()
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    store.reset()


def _public_dns(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


PASSWORD = "password123"


def login(client: TestClient, email: str = "reader@example.com", password: str = PASSWORD) -> str:
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    if response.status_code == 409:
        response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    assert client.cookies.get("sx_session")
    return email


def _user_id(email: str) -> str:
    conn = sqlite3.connect(membership.db_path())
    try:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    return row[0]


def _count(sql: str, params: tuple = ()) -> int:
    conn = sqlite3.connect(membership.db_path())
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def buy(client: TestClient) -> dict:
    response = client.post("/api/billing/checkout")
    assert response.status_code == 200
    url = response.json()["url"]
    page = client.get(url)
    assert page.status_code == 200
    order_id = url.rstrip("/").split("/")[-1]
    paid = client.post("/api/billing/fake/pay", json={"order_id": order_id})
    assert paid.status_code == 200
    return paid.json()


def test_anonymous_user_has_free_limits(client):
    data = client.get("/api/me").json()
    assert data["authenticated"] is False
    assert data["member"] is False
    assert data["limits"]["tier"] == "free"
    assert data["limits"]["max_file_label"] == "500MB"
    assert data["price"]["cents"] == 990


def test_checkout_requires_login(client):
    assert client.post("/api/billing/checkout").status_code == 401


def test_fake_checkout_grants_member_only_once(client):
    login(client)
    paid = buy(client)

    me = client.get("/api/me").json()
    assert me["member"] is True
    assert me["limits"]["tier"] == "member"
    assert me["limits"]["max_file_label"] == "2GB"

    # 重复点击支付：仍然成功返回，但不会重复开通
    order_id = paid["redirect"].split("session_id=", 1)[1].replace("fake_", "")
    assert client.post("/api/billing/fake/pay", json={"order_id": order_id}).status_code == 200
    assert _count("SELECT COUNT(*) FROM memberships") == 1
    assert _count("SELECT COUNT(*) FROM orders WHERE status = 'paid'") == 1


def test_pending_order_is_reused(client):
    login(client)
    first = client.post("/api/billing/checkout").json()
    second = client.post("/api/billing/checkout").json()
    assert first["url"] == second["url"]
    assert first["session_id"] == second["session_id"]
    assert _count("SELECT COUNT(*) FROM orders") == 1


def test_member_cannot_start_another_checkout(client):
    login(client)
    buy(client)
    response = client.post("/api/billing/checkout")
    assert response.status_code == 409


def test_order_status_is_private(client):
    login(client, "owner@example.com")
    created = client.post("/api/billing/checkout").json()

    other = TestClient(app)
    login(other, "other@example.com")
    response = other.get(f"/api/billing/orders/{created['session_id']}")
    assert response.status_code == 404

    own = client.get(f"/api/billing/orders/{created['session_id']}")
    assert own.status_code == 200
    assert own.json()["status"] == "pending"


def test_download_uses_member_limits(client, monkeypatch):
    login(client)
    buy(client)

    captured = {}

    def fake_submit(url, format_id, *, limits=None):
        captured["limits"] = limits
        return "a" * 32

    monkeypatch.setattr(store, "submit", fake_submit)
    monkeypatch.setattr(downloader.socket, "getaddrinfo", _public_dns)

    response = client.post("/api/download", json={"url": "https://example.com/video", "format_id": "18"})
    assert response.status_code == 200
    assert captured["limits"].tier == "member"
    assert captured["limits"].max_file_bytes == 2 * 1024 * 1024 * 1024


def test_anonymous_download_stays_on_free_limits(client, monkeypatch):
    captured = {}

    def fake_submit(url, format_id, *, limits=None):
        captured["limits"] = limits
        return "b" * 32

    monkeypatch.setattr(store, "submit", fake_submit)
    monkeypatch.setattr(downloader.socket, "getaddrinfo", _public_dns)

    response = client.post("/api/download", json={"url": "https://example.com/video", "format_id": "18"})
    assert response.status_code == 200
    assert captured["limits"].tier == "free"


def _stub_download(monkeypatch):
    calls = []

    def fake_submit(url, format_id, *, limits=None):
        calls.append(limits)
        return "c" * 32

    monkeypatch.setattr(store, "submit", fake_submit)
    monkeypatch.setattr(downloader.socket, "getaddrinfo", _public_dns)
    return calls


def _download(client):
    return client.post("/api/download", json={"url": "https://example.com/video", "format_id": "18"})


def test_free_user_has_three_downloads_per_day(client, monkeypatch):
    calls = _stub_download(monkeypatch)

    for _ in range(membership.FREE_DAILY_DOWNLOADS):
        assert _download(client).status_code == 200

    blocked = _download(client)
    assert blocked.status_code == 429
    assert "已用完" in blocked.json()["detail"]
    assert len(calls) == membership.FREE_DAILY_DOWNLOADS
    assert membership.daily_quota_left(membership.usage_subject(None, "testclient")) == 0


def test_member_has_unlimited_downloads(client, monkeypatch):
    login(client)
    buy(client)
    calls = _stub_download(monkeypatch)

    for _ in range(membership.FREE_DAILY_DOWNLOADS + 2):
        assert _download(client).status_code == 200
    assert len(calls) == membership.FREE_DAILY_DOWNLOADS + 2
    assert _count("SELECT COUNT(*) FROM download_usage") == 0


def test_daily_quota_resets_next_day(client, monkeypatch):
    _stub_download(monkeypatch)
    monkeypatch.setattr(membership, "_usage_day", lambda offset_days=0: "2026-01-01")

    for _ in range(membership.FREE_DAILY_DOWNLOADS):
        assert _download(client).status_code == 200
    assert _download(client).status_code == 429

    monkeypatch.setattr(membership, "_usage_day", lambda offset_days=0: "2026-01-02")
    assert _download(client).status_code == 200


def test_failed_submit_refunds_daily_quota(client, monkeypatch):
    _stub_download(monkeypatch)

    def reject(url, format_id, *, limits=None):
        raise downloader.UserFacingError("当前下载较多，请稍后再试", 429)

    monkeypatch.setattr(store, "submit", reject)
    assert _download(client).status_code == 429
    assert membership.daily_quota_left(membership.usage_subject(None, "testclient")) == 3


def test_daily_quota_is_counted_per_account(client, monkeypatch):
    login(client, "quota-a@example.com")
    _stub_download(monkeypatch)
    for _ in range(membership.FREE_DAILY_DOWNLOADS):
        assert _download(client).status_code == 200
    assert _download(client).status_code == 429

    other = TestClient(app)
    login(other, "quota-b@example.com")
    assert _download(other).status_code == 200


def _session_event(
    event_id: str,
    session_id: str,
    order_id: str,
    user_id: str,
    *,
    amount: int = 990,
    currency: str = "cny",
    payment_status: str = "paid",
) -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "payment_status": payment_status,
                "amount_total": amount,
                "currency": currency,
                "metadata": {"order_id": order_id, "user_id": user_id},
            }
        },
    }


def _prepare_order(user_id: str) -> dict:
    order = membership.open_order(user_id, "stripe", billing.PRICE_CENTS, billing.CURRENCY)
    membership.attach_checkout(order["id"], "cs_test_123", "https://checkout.stripe.com/x")
    return order


def test_webhook_is_disabled_when_using_fake_provider(client):
    response = client.post("/api/billing/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert response.status_code == 404


def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(billing, "provider", lambda: "stripe")

    def reject(payload, signature):
        raise ValueError("签名校验失败")

    monkeypatch.setattr(billing, "construct_event", reject)
    response = client.post("/api/billing/webhook", content=b"{}", headers={"stripe-signature": "bad"})
    assert response.status_code == 400


def test_webhook_grants_once_and_rejects_wrong_amount(client, monkeypatch):
    login(client, "buyer@example.com")
    user_id = _user_id("buyer@example.com")
    order = _prepare_order(user_id)

    monkeypatch.setattr(billing, "provider", lambda: "stripe")

    wrong = _session_event("evt_wrong", "cs_test_123", order["id"], user_id, amount=1)
    monkeypatch.setattr(billing, "construct_event", lambda payload, sig: wrong)
    assert client.post("/api/billing/webhook", content=b"{}").status_code == 200
    assert client.get("/api/me").json()["member"] is False

    good = _session_event("evt_ok", "cs_test_123", order["id"], user_id)
    monkeypatch.setattr(billing, "construct_event", lambda payload, sig: good)
    assert client.post("/api/billing/webhook", content=b"{}").status_code == 200
    assert client.get("/api/me").json()["member"] is True
    assert _count("SELECT COUNT(*) FROM memberships") == 1

    # 同一事件被 Stripe 重投时保持幂等
    assert client.post("/api/billing/webhook", content=b"{}").status_code == 200
    assert _count("SELECT COUNT(*) FROM memberships") == 1


def test_webhook_ignores_unpaid_session(client, monkeypatch):
    login(client, "unpaid@example.com")
    user_id = _user_id("unpaid@example.com")
    order = _prepare_order(user_id)
    event = _session_event("evt_unpaid", "cs_test_123", order["id"], user_id, payment_status="unpaid")

    monkeypatch.setattr(billing, "provider", lambda: "stripe")
    monkeypatch.setattr(billing, "construct_event", lambda payload, sig: event)
    assert client.post("/api/billing/webhook", content=b"{}").status_code == 200
    assert client.get("/api/me").json()["member"] is False


def test_stripe_checkout_uses_sdk_request_options(monkeypatch):
    """锁定 stripe-python 16 的调用方式：金额在 params，幂等键在 options。"""
    from types import SimpleNamespace

    import stripe as stripe_sdk

    captured = {}

    class FakeSessions:
        def create(self, params, options=None):
            captured["params"] = params
            captured["options"] = options
            return SimpleNamespace(id="cs_test_1", url="https://checkout.stripe.com/c/pay/1")

    class FakeClient:
        def __init__(self, key):
            captured["key"] = key
            self.checkout = SimpleNamespace(sessions=FakeSessions())

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_unit")
    monkeypatch.setattr(stripe_sdk, "StripeClient", FakeClient)
    monkeypatch.setattr(billing, "provider", lambda: "stripe")

    order = {"id": "order-1", "user_id": "user-1", "created_at": 1000.0}
    session_id, url = billing.create_checkout(order, {"email": "a@example.com"}, "http://127.0.0.1:8000")

    assert session_id == "cs_test_1"
    assert url.startswith("https://checkout.stripe.com")
    assert captured["key"] == "sk_test_unit"
    assert captured["options"] == {"idempotency_key": "checkout:order-1"}
    params = captured["params"]
    assert params["mode"] == "payment"
    assert params["line_items"][0]["price_data"] == {
        "currency": "cny",
        "unit_amount": 990,
        "product_data": {"name": billing.PRODUCT_NAME},
    }
    assert params["success_url"].endswith("?checkout=success&session_id={CHECKOUT_SESSION_ID}")
    assert params["expires_at"] == 1000 + billing.CHECKOUT_EXPIRES_SECONDS
