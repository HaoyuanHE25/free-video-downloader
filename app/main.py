"""本机接口。开发时由 Vite 把 /api 代理到这里。"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.background import BackgroundTask

from app import downloader
from app.downloader import UserFacingError, fetch_cover, parse, validate_format_id, validate_public_url
from app.jobs import store
from app.summary_routes import router as summary_router


def _load_env_file() -> None:
    """把项目根目录 .env 补进环境变量。已有的进程变量优先，不覆盖。"""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()

app = FastAPI(title="随下", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


class ParseRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.strip()


class DownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    format_id: str = Field(min_length=1, max_length=81)

    @field_validator("url", "format_id")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip()


@app.exception_handler(RequestValidationError)
async def invalid_body(request, exc: RequestValidationError):
    fields = {str(part) for err in exc.errors() for part in err.get("loc", ())}
    path = getattr(getattr(request, "url", None), "path", "") or ""
    if "question" in fields or path.startswith("/api/summary/ask"):
        message = "问题无效，请检查后重试"
    elif "format_id" in fields and "url" not in fields:
        message = "清晰度选项无效"
    else:
        message = "链接无效"
    return JSONResponse(status_code=400, content={"detail": message})


@app.get("/api/cover")
def read_cover(url: str):
    try:
        body, media_type = fetch_cover(url)
    except UserFacingError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return Response(content=body, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/parse")
def parse_video(body: ParseRequest):
    url = _public_url(body.url)
    try:
        return parse(url)
    except UserFacingError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@app.post("/api/download")
def start_download(body: DownloadRequest):
    url = _public_url(body.url)
    try:
        format_id = validate_format_id(body.format_id)
        if "+" in format_id and not downloader.ffmpeg_available():
            raise UserFacingError("需要安装 ffmpeg，才能把画面和声音合成一个文件")
        job_id = store.submit(url, format_id)
    except UserFacingError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str):
    if not _JOB_ID.fullmatch(job_id):
        raise HTTPException(404, "任务不存在或已过期")
    snapshot = store.snapshot(job_id)
    if snapshot is None:
        raise HTTPException(404, "任务不存在或已过期")
    return snapshot


@app.get("/api/jobs/{job_id}/file")
def read_job_file(job_id: str):
    if not _JOB_ID.fullmatch(job_id):
        raise HTTPException(404, "任务不存在或已过期")
    payload, reason = store.take_file(job_id)
    if reason == "missing":
        raise HTTPException(404, "任务不存在或已过期")
    if reason != "ok":
        raise HTTPException(409, "文件还没准备好")
    path, filename, directory = payload

    def cleanup() -> None:
        shutil.rmtree(directory, ignore_errors=True)

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        content_disposition_type="attachment",
        background=BackgroundTask(cleanup),
    )


def _public_url(url: str) -> str:
    try:
        return validate_public_url(url)
    except UserFacingError as exc:
        raise HTTPException(exc.status, exc.message) from exc


app.include_router(summary_router)

if _DIST.is_dir() and (_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="site")
