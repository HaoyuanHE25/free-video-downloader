"""把字幕处理、摘要生成、思维导图、问答串成 SSE 事件流。

事件顺序：meta → status* → stats → segment* → status → delta/point* → outline
→ chapter* → status → mindmap → done（出错时以 error 收尾）。
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from app.mindmap import build_mindmap, build_tree_from_text, to_mermaid
from app.subtitles import load_subtitles
from app.subtitles_proc import build_document, read_subtitles, to_plain, to_srt, to_vtt
from app.summary import (
    QA_CONTEXT_LIMIT,
    ensure_configured,
    stream_answer,
    stream_digest,
)

_ROOT = Path(tempfile.gettempdir()) / "suixia-summary"


def stream_summary(url: str, stop: threading.Event):
    started = time.monotonic()
    yield {"event": "meta", "data": {"request_id": uuid.uuid4().hex, "url": url}}
    ensure_configured()
    _ROOT.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="summary-", dir=_ROOT))
    try:
        yield _status("fetching_subtitles", "正在读取字幕")
        transcript = load_subtitles(url, directory)
        if stop.is_set():
            return
        yield _status("processing_subtitles", "正在整理字幕分段")
        document = build_document(transcript["cues"], bool(transcript.get("truncated")))
        yield {"event": "stats", "data": document["stats"]}
        for segment in document["segments"]:
            if stop.is_set():
                return
            yield {"event": "segment", "data": segment}
        yield _status("summarizing", "正在生成摘要")
        result = None
        for item in stream_digest(document["cues"], document["truncated"], stop):
            if item["event"] == "digest_result":
                result = item["data"]["result"]
                continue
            yield item
        if result is None or stop.is_set():
            return
        yield _status("building_mindmap", "正在整理思维导图")
        result["segments"] = document["segments"]
        tree = build_mindmap(result)
        result["mindmap"] = tree
        yield {"event": "mindmap", "data": {"root": tree}}
        yield {
            "event": "done",
            "data": {"result": result, "elapsed_ms": int((time.monotonic() - started) * 1000)},
        }
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def stream_subtitles(url: str, text: str, stop: threading.Event):
    """字幕处理：支持链接抓取或直接粘贴字幕文本。"""
    started = time.monotonic()
    yield {"event": "meta", "data": {"request_id": uuid.uuid4().hex}}
    directory = None
    if url:
        _ROOT.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="subtitle-", dir=_ROOT))
    try:
        if text:
            yield _status("processing_subtitles", "正在解析字幕文本")
            parsed = read_subtitles(text)
            document = build_document(parsed["cues"])
            source = parsed["format"]
        else:
            yield _status("fetching_subtitles", "正在读取字幕")
            transcript = load_subtitles(url, directory)
            if stop.is_set():
                return
            yield _status("processing_subtitles", "正在整理字幕分段")
            document = build_document(transcript["cues"], bool(transcript.get("truncated")))
            source = "url"
        yield {"event": "stats", "data": {**document["stats"], "source": source}}
        for segment in document["segments"]:
            if stop.is_set():
                return
            yield {"event": "segment", "data": segment}
        if stop.is_set():
            return
        cues = document["cues"]
        payload = {
            "stats": document["stats"],
            "source": source,
            "segments": document["segments"],
            "exports": {
                "plain": to_plain(cues),
                "timed": to_plain(cues, with_time=True),
                "srt": to_srt(cues),
                "vtt": to_vtt(cues),
            },
        }
        yield {
            "event": "done",
            "data": {"result": payload, "elapsed_ms": int((time.monotonic() - started) * 1000)},
        }
    finally:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


def stream_mindmap(url: str, text: str, stop: threading.Event):
    """思维导图：链接走“字幕 → 摘要 → 结构”，文本按缩进直接成树。"""
    started = time.monotonic()
    yield {"event": "meta", "data": {"request_id": uuid.uuid4().hex}}
    directory = None
    try:
        if text:
            yield _status("building_mindmap", "正在解析提纲层级")
            tree = build_tree_from_text(text)
        else:
            ensure_configured()
            _ROOT.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix="mindmap-", dir=_ROOT))
            yield _status("fetching_subtitles", "正在读取字幕")
            transcript = load_subtitles(url, directory)
            if stop.is_set():
                return
            yield _status("processing_subtitles", "正在整理字幕分段")
            document = build_document(transcript["cues"], bool(transcript.get("truncated")))
            yield _status("summarizing", "正在生成摘要结构")
            result = None
            for item in stream_digest(document["cues"], document["truncated"], stop):
                if item["event"] == "digest_result":
                    result = item["data"]["result"]
                    break
                if item["event"] in {"outline", "point", "chapter"}:
                    yield item
            if result is None or stop.is_set():
                return
            yield _status("building_mindmap", "正在整理导图层级")
            tree = build_mindmap(result)
        code = to_mermaid(tree)
        yield {"event": "tree", "data": {"root": tree}}
        yield {"event": "mermaid", "data": {"code": code}}
        yield {
            "event": "done",
            "data": {
                "result": {"root": tree, "mermaid": code},
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        }
    finally:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


def stream_qa(question: str, context: str, history: list[dict], stop: threading.Event):
    yield {"event": "meta", "data": {"request_id": uuid.uuid4().hex, "question": question}}
    yield _status("thinking", "正在思考")
    yield from stream_answer(question, context, history, stop)


def stream_qa_url(question: str, url: str, history: list[dict], stop: threading.Event):
    """没带上下文时，用视频链接现取字幕作为问答资料。"""
    yield {"event": "meta", "data": {"request_id": uuid.uuid4().hex, "question": question, "url": url}}
    _ROOT.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="qa-", dir=_ROOT))
    try:
        yield _status("fetching_subtitles", "正在读取字幕")
        transcript = load_subtitles(url, directory)
        if stop.is_set():
            return
        yield _status("processing_subtitles", "正在整理问答资料")
        document = build_document(transcript["cues"], bool(transcript.get("truncated")))
        context = to_plain(document["cues"], with_time=True)
        if len(context) > QA_CONTEXT_LIMIT:
            context = context[:QA_CONTEXT_LIMIT].rstrip() + "\n（资料较长，已截断）"
        if not context:
            return
        yield _status("thinking", "正在思考")
        yield from stream_answer(question, context, history, stop)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _status(stage: str, message: str) -> dict:
    return {"event": "status", "data": {"stage": stage, "message": message}}
