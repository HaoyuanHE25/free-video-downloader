"""总结接口：保留旧的任务式接口，同时提供统一 SSE 流式接口。"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.downloader import UserFacingError, validate_public_url
from app.sse import event_stream
from app.subtitles import load_subtitles
from app.summary import QA_CONTEXT_LIMIT, build_qa_context, ensure_configured
from app.summary_jobs import store
from app.summary_stream import stream_mindmap, stream_qa, stream_qa_url, stream_subtitles, stream_summary

router = APIRouter()
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_ROOT = Path(tempfile.gettempdir()) / "suixia-summary"


class SummaryRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.strip()


class SourceRequest(BaseModel):
    """字幕/导图模块的输入：链接或直接粘贴文本，二选一。"""

    url: str = Field(default="", max_length=2048)
    text: str = Field(default="", max_length=120_000)

    @field_validator("url", "text")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip()


class AskTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[AskTurn] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    text: str = Field(default="", max_length=20_000)
    url: str = Field(default="", max_length=2048)

    @field_validator("question", "text", "url")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip()


@router.post("/api/summary")
def start_summary(body: SummaryRequest):
    try:
        url = validate_public_url(body.url)
        ensure_configured()
        _ROOT.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="summary-", dir=_ROOT))
        try:
            transcript = load_subtitles(url, directory)
            job_id = store.submit(transcript, directory)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
    except UserFacingError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return {"job_id": job_id}


@router.get("/api/summary/{job_id}")
def read_summary(job_id: str):
    if not _JOB_ID.fullmatch(job_id):
        raise HTTPException(404, "任务不存在或已过期")
    snapshot = store.snapshot(job_id)
    if snapshot is None:
        raise HTTPException(404, "任务不存在或已过期")
    return snapshot


@router.post("/api/summary/stream")
def summarize_as_stream(body: SummaryRequest):
    """总结摘要 + 字幕分段 + 思维导图，一条 SSE 流返回。"""
    try:
        url = validate_public_url(body.url)
        ensure_configured()
    except UserFacingError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return event_stream(lambda stop: stream_summary(url, stop))


@router.post("/api/subtitles/stream")
def subtitles_as_stream(body: SourceRequest):
    """字幕文本处理：链接抓取或直接粘贴 SRT/VTT/JSON 字幕。"""
    text = body.text.strip()
    url = body.url.strip()
    if not text and not url:
        raise HTTPException(400, "请提供视频链接或字幕文本")
    if url:
        try:
            url = validate_public_url(url)
        except UserFacingError as exc:
            raise HTTPException(exc.status, exc.message) from exc
    return event_stream(lambda stop: stream_subtitles(url, text, stop))


@router.post("/api/mindmap/stream")
def mindmap_as_stream(body: SourceRequest):
    """思维导图：链接走自动摘要，文本按缩进层级直接解析。"""
    text = body.text.strip()
    url = body.url.strip()
    if not text and not url:
        raise HTTPException(400, "请提供视频链接或提纲内容")
    try:
        if url:
            url = validate_public_url(url)
        if not text:
            ensure_configured()
    except UserFacingError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return event_stream(lambda stop: stream_mindmap(url, text, stop))


@router.post("/api/summary/ask/stream")
def ask_as_stream(body: AskRequest):
    """基于上下文的多轮问答：支持链接、粘贴资料或已有摘要结构。"""
    try:
        ensure_configured()
    except UserFacingError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    text = body.text.strip()
    url = body.url.strip()
    context = build_qa_context(body.context)
    if text:
        context = text
    elif context:
        text = ""
    if not context and not url:
        raise HTTPException(400, "还没有可问答的内容，请提供视频链接或粘贴资料")
    try:
        if url:
            url = validate_public_url(url)
    except UserFacingError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    history = [
        {"role": turn.role, "content": turn.content.strip()}
        for turn in body.history[-6:]
        if turn.content.strip()
    ]
    if context:
        return event_stream(lambda stop: stream_qa(question, context[:QA_CONTEXT_LIMIT], history, stop))
    return event_stream(lambda stop: stream_qa_url(question, url, history, stop))
