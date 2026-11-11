"""账号、会话、密码重置与订单的持久化存储。SQLite 单文件，够单机使用。"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import bcrypt

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _ROOT / "data" / "app.sqlite3"

RESET_TOKEN_TTL_SECONDS = 15 * 60
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
# 剩余有效期不足这个值时，访问 /api/me 会把会话顺延一整个 TTL，避免长期用户被强制重新登录。
SESSION_RENEW_BEFORE_SECONDS = 7 * 24 * 60 * 60
ORDER_REUSE_SECONDS = 25 * 60

PASSWORD_MIN_LENGTH = 8
# bcrypt 只处理前 72 字节，超长直接拒绝而不是静默截断。
PASSWORD_MAX_BYTES = 72

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,}$")

# 会员权益：只放宽并发、体积与超时，不新增功能。
@dataclass(frozen=True)
class Limits:
    tier: str
    max_concurrent: int
    max_file_bytes: int
    timeout_seconds: int
    max_pending: int


FREE_LIMITS = Limits("free", 2, 500 * 1024 * 1024, 10 * 60, 8)
MEMBER_LIMITS = Limits("member", 4, 2 * 1024 * 1024 * 1024, 30 * 60, 8)

# 非会员（含未登录游客）每天能发起的下载次数，会员不限。
FREE_DAILY_DOWNLOADS = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    created_at REAL NOT NULL,
    last_login_at REAL
);
CREATE TABLE IF NOT EXISTS reset_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    stripe_session_id TEXT UNIQUE,
    checkout_url TEXT,
    created_at REAL NOT NULL,
    paid_at REAL
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, status);
CREATE TABLE IF NOT EXISTS memberships (
    user_id TEXT PRIMARY KEY,
    plan TEXT NOT NULL,
    order_id TEXT,
    granted_at REAL NOT NULL,
    expires_at REAL
);
CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS download_usage (
    subject TEXT NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (subject, day)
);
"""


def db_path() -> Path:
    override = os.environ.get("MEMBERSHIP_DB_PATH", "").strip()
    return Path(override) if override else _DEFAULT_DB


def _migrate(conn: sqlite3.Connection) -> None:
    """兼容老库：补 password_hash 列，并删除已废弃的邮件登录表。"""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "password_hash" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    legacy = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'magic_links'"
    ).fetchone()
    if legacy is not None:
        conn.execute("DROP TABLE magic_links")


@contextmanager
def _connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=8000")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    try:
        yield conn
    finally:
        conn.close()


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not _EMAIL_RE.fullmatch(value):
        raise ValueError("邮箱格式不正确")
    return value


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class EmailTakenError(ValueError):
    """邮箱已经注册过了。"""


def _bcrypt_rounds() -> int:
    """生产默认 12；测试可用 BCRYPT_ROUNDS=4 加速。"""
    raw = os.environ.get("BCRYPT_ROUNDS", "").strip()
    if not raw:
        return 12
    try:
        return min(max(int(raw), 4), 15)
    except ValueError:
        return 12


def _validate_password(password: str) -> bytes:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"密码至少 {PASSWORD_MIN_LENGTH} 位")
    encoded = password.encode("utf-8")
    if len(encoded) > PASSWORD_MAX_BYTES:
        raise ValueError("密码太长，最多 72 个字节")
    return encoded


# 用户不存在时也做一次等价比对，避免通过响应耗时枚举已注册邮箱。
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(rounds=4)).decode("utf-8")


def hash_password(password: str) -> str:
    encoded = _validate_password(password)
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=_bcrypt_rounds())).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        bcrypt.checkpw(b"dummy-password-for-timing", _DUMMY_HASH.encode("utf-8"))
        return False
    try:
        return bcrypt.checkpw((password or "").encode("utf-8")[:PASSWORD_MAX_BYTES], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_account(email: str, password: str) -> dict:
    """注册：邮箱 + 密码。密码只存 bcrypt 哈希。"""
    value = normalize_email(email)
    password_hash = hash_password(password)
    now = time.time()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (value,)).fetchone():
                raise EmailTakenError("这个邮箱已经注册过了")
            user_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO users (id, email, password_hash, created_at, last_login_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, value, password_hash, now, now),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {"id": user_id, "email": value}


def authenticate(email: str, password: str) -> dict | None:
    """校验邮箱与密码。任何一项不匹配都返回 None，不区分具体原因。"""
    try:
        value = normalize_email(email)
    except ValueError:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?", (value,)
        ).fetchone()
    if row is None:
        verify_password(password or "", None)
        return None
    if not verify_password(password or "", row["password_hash"]):
        return None
    with _connect() as conn:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (time.time(), row["id"]))
    return {"id": row["id"], "email": row["email"]}


def issue_reset_token(email: str) -> str:
    """生成一次性重置 token。

    邮箱不存在时也返回一个随机 token（不落库），这样接口无法用来枚举已注册邮箱；
    这种 token 在重置时会被判定为无效。
    """
    value = normalize_email(email)
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (value,)).fetchone()
            if row is not None:
                conn.execute(
                    "INSERT INTO reset_tokens (token_hash, user_id, created_at, expires_at)"
                    " VALUES (?, ?, ?, ?)",
                    (_hash(token), row["id"], now, now + RESET_TOKEN_TTL_SECONDS),
                )
            conn.execute("DELETE FROM reset_tokens WHERE expires_at < ?", (now - 24 * 60 * 60,))
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return token


def consume_reset_token(token: str, password: str) -> dict | None:
    """用一次性 token 重设密码，并踢掉该账号所有旧会话。"""
    if not token:
        return None
    password_hash = hash_password(password)
    now = time.time()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT r.user_id, r.expires_at, r.used_at, u.email"
                " FROM reset_tokens r JOIN users u ON u.id = r.user_id"
                " WHERE r.token_hash = ?",
                (_hash(token),),
            ).fetchone()
            if row is None or row["used_at"] is not None or row["expires_at"] < now:
                conn.execute("COMMIT")
                return None
            conn.execute(
                "UPDATE reset_tokens SET used_at = ? WHERE token_hash = ?", (now, _hash(token))
            )
            conn.execute(
                "UPDATE users SET password_hash = ?, last_login_at = ? WHERE id = ?",
                (password_hash, now, row["user_id"]),
            )
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {"id": row["user_id"], "email": row["email"]}


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_hash(token), user_id, now, now + SESSION_TTL_SECONDS),
        )
    return token


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.email, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ? AND u.password_hash IS NOT NULL",
            (_hash(token),),
        ).fetchone()
    if row is None or row["expires_at"] < now:
        return None
    return {"id": row["id"], "email": row["email"]}


def renew_session(token: str | None) -> bool:
    """会话快过期时顺延一整个 TTL。返回是否真的顺延（用于决定要不要重发 Cookie）。"""
    if not token:
        return False
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            "SELECT expires_at FROM sessions WHERE token_hash = ?", (_hash(token),)
        ).fetchone()
        if row is None or row["expires_at"] < now:
            return False
        if row["expires_at"] - now > SESSION_RENEW_BEFORE_SECONDS:
            return False
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
            (now + SESSION_TTL_SECONDS, _hash(token)),
        )
    return True


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def membership_of(user_id: str) -> dict | None:
    if not user_id:
        return None
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id, plan, order_id, granted_at, expires_at FROM memberships WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    if row["expires_at"] is not None and row["expires_at"] < now:
        return None
    return {
        "plan": row["plan"],
        "order_id": row["order_id"],
        "granted_at": row["granted_at"],
        "expires_at": row["expires_at"],
    }


def limits_for(user: dict | None) -> Limits:
    if user and membership_of(user["id"]):
        return MEMBER_LIMITS
    return FREE_LIMITS


def limits_payload(limits: Limits) -> dict:
    return {
        "tier": limits.tier,
        "max_concurrent": limits.max_concurrent,
        "max_file_bytes": limits.max_file_bytes,
        "max_file_label": human_size(limits.max_file_bytes),
        "timeout_seconds": limits.timeout_seconds,
        "max_pending": limits.max_pending,
        "daily_downloads": None if limits.tier == MEMBER_LIMITS.tier else FREE_DAILY_DOWNLOADS,
    }


def _usage_day(offset_days: int = 0) -> str:
    """按服务器本地时区的自然日计数，零点自动重置。"""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() + offset_days * 86400))


def usage_subject(user: dict | None, ip: str | None) -> str:
    """会员都会被跳过；这里只区分是哪个账号或哪个 IP 在消耗每日次数。"""
    if user:
        return f"user:{user['id']}"
    return f"ip:{ip or 'unknown'}"


def consume_daily_quota(subject: str, limit: int = FREE_DAILY_DOWNLOADS) -> bool:
    """原子地占用一次今日额度。次数用尽返回 False。"""
    day = _usage_day()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT count FROM download_usage WHERE subject = ? AND day = ?", (subject, day)
            ).fetchone()
            if row is not None and row["count"] >= limit:
                conn.execute("COMMIT")
                return False
            conn.execute(
                "INSERT INTO download_usage (subject, day, count) VALUES (?, ?, 1)"
                " ON CONFLICT(subject, day) DO UPDATE SET count = count + 1",
                (subject, day),
            )
            conn.execute("DELETE FROM download_usage WHERE day < ?", (_usage_day(-7),))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return True


def refund_daily_quota(subject: str) -> None:
    """任务没真正排队成功时把刚占用的一次还回去。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE download_usage SET count = count - 1 WHERE subject = ? AND day = ? AND count > 0",
            (subject, _usage_day()),
        )


def daily_quota_left(subject: str, limit: int = FREE_DAILY_DOWNLOADS) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT count FROM download_usage WHERE subject = ? AND day = ?", (subject, _usage_day())
        ).fetchone()
    used = row["count"] if row else 0
    return max(limit - used, 0)


def human_size(size: int) -> str:
    if size >= 1024 * 1024 * 1024 and size % (1024 * 1024 * 1024) == 0:
        return f"{size // (1024 * 1024 * 1024)}GB"
    return f"{max(size // (1024 * 1024), 1)}MB"


def open_order(user_id: str, provider: str, amount: int, currency: str) -> dict:
    """返回可用的 pending 订单。25 分钟内复用同一笔，避免重复付款。"""
    now = time.time()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM orders WHERE user_id = ? AND status = 'pending'"
                " ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is not None and row["checkout_url"] and now - row["created_at"] < ORDER_REUSE_SECONDS:
                conn.execute("COMMIT")
                return dict(row)
            if row is not None:
                conn.execute("UPDATE orders SET status = 'expired' WHERE id = ?", (row["id"],))
            order_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO orders (id, user_id, provider, status, amount, currency, created_at)"
                " VALUES (?, ?, ?, 'pending', ?, ?, ?)",
                (order_id, user_id, provider, amount, currency, now),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {
        "id": order_id,
        "user_id": user_id,
        "provider": provider,
        "status": "pending",
        "amount": amount,
        "currency": currency,
        "stripe_session_id": None,
        "checkout_url": None,
        "created_at": now,
        "paid_at": None,
    }


def attach_checkout(order_id: str, session_id: str, url: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE orders SET stripe_session_id = ?, checkout_url = ? WHERE id = ?",
            (session_id, url, order_id),
        )


def close_order(order_id: str, status: str = "failed") -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE orders SET status = ? WHERE id = ? AND status = 'pending'", (status, order_id)
        )


def order_for_user(session_id: str, user_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE stripe_session_id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def order_by_id(order_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def expire_session_order(session_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'expired' WHERE stripe_session_id = ? AND status = 'pending'",
            (session_id,),
        )


def grant_from_session(
    *,
    event_id: str,
    event_type: str,
    session_id: str,
    amount: int | None,
    currency: str | None,
    expected_amount: int,
    expected_currency: str,
    order_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """校验并开通会员。返回 granted / duplicate / unknown_order / mismatch。

    事件记录与会员写入在同一个事务里，任一步失败都不会留下半成品。
    """
    now = time.time()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute(
                "SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,)
            ).fetchone():
                conn.execute("COMMIT")
                return "duplicate"
            conn.execute(
                "INSERT INTO processed_events (event_id, event_type, created_at) VALUES (?, ?, ?)",
                (event_id, event_type, now),
            )
            order = conn.execute(
                "SELECT * FROM orders WHERE stripe_session_id = ?", (session_id,)
            ).fetchone()
            if order is None and order_id:
                order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order is None:
                conn.execute("COMMIT")
                return "unknown_order"
            if (
                amount != expected_amount
                or currency != expected_currency
                or order["amount"] != expected_amount
                or order["currency"] != expected_currency
                or (user_id and user_id != order["user_id"])
            ):
                conn.execute("COMMIT")
                return "mismatch"
            conn.execute(
                "UPDATE orders SET status = 'paid', paid_at = ? WHERE id = ? AND status != 'paid'",
                (now, order["id"]),
            )
            conn.execute(
                "INSERT OR IGNORE INTO memberships (user_id, plan, order_id, granted_at, expires_at)"
                " VALUES (?, 'lifetime', ?, ?, NULL)",
                (order["user_id"], order["id"], now),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return "granted"
