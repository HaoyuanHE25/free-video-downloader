"""统一的 SSE 输出层。

业务侧只写同步生成器；这里把它放进工作线程，主协程负责心跳、断线取消和错误收尾。
所有接口共用同一套事件外壳：event 名 + JSON data。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable, Iterator

from fastapi.responses import StreamingResponse

from app.downloader import UserFacingError

HEARTBEAT_SECONDS = 15.0
_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_log = logging.getLogger(__name__)


def encode(event: str, data: dict) -> str:
    """一条 SSE 消息。data 压成单行 JSON，避免换行破坏协议。"""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def error_event(message: str, code: int = 500) -> dict:
    return {"event": "error", "data": {"message": message, "code": code}}


def event_stream(worker_factory: Callable[[threading.Event], Iterator[dict]]) -> StreamingResponse:
    """把同步事件生成器变成 SSE 响应。

    worker_factory 收到 stop 事件；客户端断开后 stop 被置位，生成器应尽快返回。
    """

    async def generate():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        stop = threading.Event()

        def publish(kind: str, payload: dict | None = None) -> None:
            if loop.is_closed():
                return
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))
            except RuntimeError:
                # 事件循环已经关闭，客户端早就走了。
                pass

        def run() -> None:
            try:
                for item in worker_factory(stop):
                    if stop.is_set():
                        break
                    publish("event", item)
            except UserFacingError as exc:
                publish("event", error_event(exc.message, exc.status))
            except Exception:
                _log.exception("SSE 任务中断")
                publish("event", error_event("处理中断，请稍后重试", 500))
            finally:
                publish("close")

        threading.Thread(target=run, name="suixia-sse", daemon=True).start()
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # 模型慢的时候也要让连接保持活跃，避免网关掐断。
                    yield ": keep-alive\n\n"
                    continue
                if kind == "close":
                    break
                event = (payload or {}).get("event") or "message"
                data = (payload or {}).get("data") or {}
                yield encode(event, data)
        finally:
            stop.set()

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_HEADERS)
