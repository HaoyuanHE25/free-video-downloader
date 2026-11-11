"""账号登录、密码重置与会员购买接口。会员只由支付回调开通，成功页只轮询。"""

from __future__ import annotations

import html
import logging
import os
import threading
import time
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app import billing, membership

log = logging.getLogger("suixia")

router = APIRouter()

COOKIE_NAME = "sx_session"
_PAID_EVENTS = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}

# 重置邮件/链接的发送冷却，防止被刷
_sent_at: dict[str, float] = {}
# 登录失败计数，防止暴力猜密码
_login_failures: dict[str, list[float]] = {}
_sent_lock = threading.Lock()
_LOGIN_WINDOW_SECONDS = 5 * 60
_LOGIN_MAX_FAILURES = 8


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class CredentialsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class FakePayRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)


def current_user(request: Request) -> dict | None:
    return membership.session_user(request.cookies.get(COOKIE_NAME))


def _require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "请先登录")
    return user


def _base_url(request: Request) -> str:
    fixed = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    return fixed or str(request.base_url).rstrip("/")


def _cookie_secure(request: Request) -> bool:
    """默认按请求协议判断；需要强制时可显式设置 COOKIE_SECURE=1/0。"""
    override = os.environ.get("COOKIE_SECURE", "").strip()
    if override in {"0", "1"}:
        return override == "1"
    return request.url.scheme == "https"


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=membership.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        path="/",
    )


def _allowed_origins(request: Request) -> set[str]:
    origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        f"{request.url.scheme}://{request.url.netloc}",
    }
    fixed = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if fixed:
        origins.add(fixed)
    for item in os.environ.get("ALLOWED_ORIGINS", "").split(","):
        value = item.strip().rstrip("/")
        if value:
            origins.add(value)
    return origins


def _guard_origin(request: Request) -> None:
    """浏览器的写操作必须来自本站。没有 Origin 的请求（命令行、测试、Webhook）不受影响。"""
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if not origin:
        return
    if origin not in _allowed_origins(request):
        raise HTTPException(403, "跨站请求被拒绝")


def _throttle(key: str) -> None:
    now = time.time()
    with _sent_lock:
        if len(_sent_at) > 2000:
            _sent_at.clear()
        last = _sent_at.get(key, 0)
        if now - last < 60:
            raise HTTPException(429, "操作太频繁，请一分钟后再试")
        _sent_at[key] = now


def _check_login_failures(key: str) -> None:
    now = time.time()
    with _sent_lock:
        recent = [item for item in _login_failures.get(key, []) if now - item < _LOGIN_WINDOW_SECONDS]
        _login_failures[key] = recent
        if len(recent) >= _LOGIN_MAX_FAILURES:
            raise HTTPException(429, "尝试次数过多，请几分钟后再试")


def _record_login_failure(key: str) -> None:
    with _sent_lock:
        if len(_login_failures) > 2000:
            _login_failures.clear()
        _login_failures.setdefault(key, []).append(time.time())


def _clear_login_failures(key: str) -> None:
    with _sent_lock:
        _login_failures.pop(key, None)


def _session_response(user: dict, request: Request) -> JSONResponse:
    response = JSONResponse({"ok": True, "user": {"email": user["email"]}})
    _set_session_cookie(response, membership.create_session(user["id"]), request)
    return response


@router.post("/api/auth/register")
def register(body: CredentialsRequest, request: Request):
    _guard_origin(request)
    try:
        user = membership.create_account(body.email, body.password)
    except membership.EmailTakenError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _clear_login_failures(body.email.strip().lower())
    log.info("新账号注册成功：%s", user["email"])
    return _session_response(user, request)


@router.post("/api/auth/login")
def login(body: CredentialsRequest, request: Request):
    _guard_origin(request)
    email = body.email.strip().lower()
    _check_login_failures(email)
    user = membership.authenticate(email, body.password)
    if user is None:
        _record_login_failure(email)
        raise HTTPException(401, "邮箱或密码不正确")
    _clear_login_failures(email)
    return _session_response(user, request)


@router.post("/api/auth/request-reset")
def request_reset(body: EmailRequest, request: Request):
    """申请重置密码。SMTP 已移除，重置链接直接返回给调用方并记录到后端日志。"""
    _guard_origin(request)
    email = body.email.strip().lower()
    _throttle(email)
    try:
        token = membership.issue_reset_token(email)
    except ValueError as exc:
        raise HTTPException(400, "邮箱格式不正确") from exc
    link = f"{_base_url(request)}/?reset={quote(token)}"
    log.info("密码重置链接（15 分钟内有效，仅一次）：%s", link)
    return {"ok": True, "reset_url": link}


@router.post("/api/auth/reset")
def reset_password(body: ResetRequest, request: Request):
    _guard_origin(request)
    try:
        user = membership.consume_reset_token(body.token, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if user is None:
        raise HTTPException(400, "重置链接无效或已过期，请重新申请")
    log.info("密码已重置：%s", user["email"])
    return _session_response(user, request)


@router.post("/api/auth/logout")
def logout(request: Request):
    _guard_origin(request)
    membership.revoke_session(request.cookies.get(COOKIE_NAME))
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


def _me_payload(user: dict | None) -> dict:
    member = membership.membership_of(user["id"]) if user else None
    limits = membership.MEMBER_LIMITS if member else membership.FREE_LIMITS
    return {
        "authenticated": user is not None,
        "user": {"email": user["email"]} if user else None,
        "member": member is not None,
        "membership": member,
        "limits": membership.limits_payload(limits),
        "price": billing.public_price(),
    }


@router.get("/api/me")
def read_me(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    user = membership.session_user(token)
    if user is not None and membership.renew_session(token):
        _set_session_cookie(response, token, request)
        log.info("会话已自动续期：%s", user["email"])
    # 登录态和会员态必须实时从服务端取，禁止任何中间层缓存，避免重新登录后读到旧状态。
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Cookie"
    return _me_payload(user)


@router.post("/api/billing/checkout")
def create_checkout(request: Request):
    _guard_origin(request)
    user = _require_user(request)
    if membership.membership_of(user["id"]):
        raise HTTPException(409, "你已经是会员了")
    provider = billing.provider()
    if provider == "fake" and not billing.fake_allowed():
        raise HTTPException(503, "支付暂时不可用")

    order = membership.open_order(user["id"], provider, billing.PRICE_CENTS, billing.CURRENCY)
    if order.get("checkout_url"):
        return {"url": order["checkout_url"], "session_id": order["stripe_session_id"]}

    try:
        session_id, url = billing.create_checkout(order, user, _base_url(request))
    except Exception as exc:
        log.warning("创建支付会话失败：%s", exc)
        membership.close_order(order["id"])
        raise HTTPException(502, "支付暂时不可用，请稍后再试") from exc

    membership.attach_checkout(order["id"], session_id, url)
    return {"url": url, "session_id": session_id}


@router.get("/api/billing/orders/{session_id}")
def read_order(session_id: str, request: Request):
    user = _require_user(request)
    order = membership.order_for_user(session_id, user["id"])
    if order is None:
        raise HTTPException(404, "订单不存在")
    member = membership.membership_of(user["id"])
    return {"status": order["status"], "member": member is not None}


@router.post("/api/billing/webhook")
async def stripe_webhook(request: Request):
    if billing.provider() != "stripe":
        raise HTTPException(404, "Not Found")
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = billing.construct_event(payload, signature)
    except ValueError as exc:
        raise HTTPException(400, "签名校验失败") from exc

    event_type = event.get("type") or ""
    event_id = event.get("id") or ""
    session = (event.get("data") or {}).get("object") or {}
    session_id = session.get("id") or ""
    meta = session.get("metadata") or {}

    if event_type in _PAID_EVENTS:
        if session.get("payment_status") != "paid":
            return {"received": True}
        result = membership.grant_from_session(
            event_id=event_id,
            event_type=event_type,
            session_id=session_id,
            order_id=meta.get("order_id"),
            user_id=meta.get("user_id"),
            amount=session.get("amount_total"),
            currency=session.get("currency"),
            expected_amount=billing.PRICE_CENTS,
            expected_currency=billing.CURRENCY,
        )
        if result not in {"granted", "duplicate"}:
            log.warning("支付回调未开通会员：%s %s", result, event_id)
    elif event_type == "checkout.session.expired":
        membership.expire_session_order(session_id)

    return {"received": True}


@router.get("/api/billing/fake/checkout/{order_id}", response_class=HTMLResponse)
def fake_checkout(order_id: str):
    if not billing.fake_allowed():
        raise HTTPException(404, "Not Found")
    order = membership.order_by_id(order_id)
    if order is None or order["status"] != "pending":
        raise HTTPException(404, "订单不存在")

    safe_id = html.escape(order_id)
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>模拟收银台 · 随下</title>
<style>
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
         font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
         background: linear-gradient(155deg, #f3f5fb, #eceff7 48%, #f4f1f4); color: #1b1f2a; }}
  .card {{ width: min(92vw, 420px); padding: 28px; border-radius: 20px; border: 1px solid rgba(255,255,255,.8);
          background: rgba(255,255,255,.72); box-shadow: 0 24px 60px -32px rgba(31,38,60,.4); }}
  h1 {{ margin: 0 0 6px; font-size: 18px; }}
  p {{ margin: 6px 0; font-size: 13px; line-height: 1.7; color: #5b6272; }}
  .price {{ margin: 18px 0; font-size: 30px; font-weight: 800; letter-spacing: -.02em; }}
  button {{ width: 100%; min-height: 44px; border: 0; border-radius: 999px; cursor: pointer;
           background: linear-gradient(180deg, #2b3143, #191e2c); color: #fff; font-size: 14px; }}
  button:disabled {{ opacity: .5; cursor: not-allowed; }}
  .note {{ margin-top: 14px; font-size: 12px; color: #8b92a1; }}
</style>
</head>
<body>
  <div class="card">
    <h1>模拟收银台（离线测试）</h1>
    <p>当前没有配置 Stripe 密钥，这里模拟一次支付。开通逻辑与真实回调完全一致。</p>
    <div class="price">{html.escape(billing.PRICE_LABEL)}</div>
    <button id="pay" onclick="pay()">模拟支付成功</button>
    <p class="note">测试用，不会产生任何真实扣款。</p>
  </div>
<script>
async function pay() {{
  const button = document.getElementById('pay');
  button.disabled = true;
  try {{
    const response = await fetch('/api/billing/fake/pay', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ order_id: '{safe_id}' }}),
    }});
    const data = await response.json().catch(() => ({{}}));
    if (!response.ok) throw new Error(data.detail || '支付没有完成');
    location.href = data.redirect;
  }} catch (error) {{
    button.disabled = false;
    alert(error.message || '支付没有完成');
  }}
}}
</script>
</body>
</html>"""
    return HTMLResponse(page)


@router.post("/api/billing/fake/pay")
def fake_pay(body: FakePayRequest, request: Request):
    _guard_origin(request)
    if not billing.fake_allowed():
        raise HTTPException(404, "Not Found")
    order = membership.order_by_id(body.order_id)
    if order is None or order["status"] not in {"pending", "paid"}:
        raise HTTPException(404, "订单不存在")
    session_id = order["stripe_session_id"] or f"fake_{order['id']}"
    membership.grant_from_session(
        event_id=f"fake:{order['id']}",
        event_type="fake.paid",
        session_id=session_id,
        order_id=order["id"],
        user_id=order["user_id"],
        amount=billing.PRICE_CENTS,
        currency=billing.CURRENCY,
        expected_amount=billing.PRICE_CENTS,
        expected_currency=billing.CURRENCY,
    )
    return {"ok": True, "redirect": f"/?checkout=success&session_id={quote(session_id)}"}
