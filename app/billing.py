"""支付通道：真实 Stripe，或完全离线的本地模拟收银台。

价格与币种只在这里定义，任何接口都不接受前端传金额。
"""

from __future__ import annotations

import json
import os
from typing import Any

PRICE_CENTS = 990
CURRENCY = "cny"
PRICE_LABEL = "¥9.9"
PRODUCT_NAME = "随下会员（永久）"
PLAN_ID = "lifetime"
CHECKOUT_EXPIRES_SECONDS = 31 * 60

_FAKE_PREFIX = "fake_"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def provider() -> str:
    chosen = _env("BILLING_PROVIDER").lower()
    if chosen in {"stripe", "fake"}:
        return chosen
    return "stripe" if _env("STRIPE_SECRET_KEY") else "fake"


def fake_allowed() -> bool:
    return provider() == "fake" and _env("APP_ENV").lower() != "production"


def public_price() -> dict:
    return {
        "cents": PRICE_CENTS,
        "currency": CURRENCY,
        "label": PRICE_LABEL,
        "product": PRODUCT_NAME,
        "plan": PLAN_ID,
    }


def create_checkout(order: dict, user: dict, base_url: str) -> tuple[str, str]:
    """创建收银台，返回 (session_id, 跳转地址)。同一订单重复调用不会产生第二笔付款。"""
    if provider() == "fake":
        if not fake_allowed():
            raise RuntimeError("生产环境不允许使用模拟支付")
        session_id = _FAKE_PREFIX + order["id"]
        return session_id, f"{base_url}/api/billing/fake/checkout/{order['id']}"

    stripe = _import_stripe()
    session = stripe.StripeClient(_env("STRIPE_SECRET_KEY")).checkout.sessions.create(
        {
            "mode": "payment",
            "client_reference_id": order["user_id"],
            "customer_email": user["email"],
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": CURRENCY,
                        "unit_amount": PRICE_CENTS,
                        "product_data": {"name": PRODUCT_NAME},
                    },
                }
            ],
            "metadata": {"order_id": order["id"], "user_id": order["user_id"]},
            "payment_intent_data": {
                "metadata": {"order_id": order["id"], "user_id": order["user_id"]}
            },
            "success_url": f"{base_url}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{base_url}/?checkout=cancel#member",
            "expires_at": int(order["created_at"]) + CHECKOUT_EXPIRES_SECONDS,
        },
        options={"idempotency_key": f"checkout:{order['id']}"},
    )
    return session.id, session.url


def construct_event(payload: bytes, signature: str) -> dict[str, Any]:
    """用原始请求体验签。签名不对会抛 ValueError，由路由转成 400。"""
    secret = _env("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise ValueError("未配置 STRIPE_WEBHOOK_SECRET")
    stripe = _import_stripe()
    try:
        stripe.Webhook.construct_event(
            payload,
            signature,
            secret,
            api_key=_env("STRIPE_SECRET_KEY") or None,
        )
    except Exception as exc:  # SignatureVerificationError 等
        raise ValueError("签名校验失败") from exc
    # 验签通过后统一转成普通 dict，避免上层依赖 StripeObject 的取值方式
    return json.loads(payload)


def _import_stripe():
    if not _env("STRIPE_SECRET_KEY"):
        raise RuntimeError("未配置 STRIPE_SECRET_KEY")
    try:
        import stripe
    except ImportError as exc:
        raise RuntimeError("服务端还没有安装 stripe") from exc
    return stripe
