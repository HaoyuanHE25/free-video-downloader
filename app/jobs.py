"""内存中的下载任务。重启进程后任务和临时文件不再保留。"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.downloader import UserFacingError, download_media

MAX_CONCURRENT = 2
MAX_PENDING = 8
JOB_TTL_SECONDS = 30 * 60

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


@dataclass
class Job:
    id: str
    status: str
    progress: float
    filename: str | None
    error: str | None
    path: Path | None
    directory: Path
    created_at: float


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._root = Path(tempfile.gettempdir()) / "suixia"
        self._root.mkdir(parents=True, exist_ok=True)

    def submit(self, url: str, format_id: str) -> str:
        with self._lock:
            self._sweep_locked()
            pending = sum(1 for job in self._jobs.values() if job.status in {"queued", "downloading"})
            if pending >= MAX_PENDING:
                raise UserFacingError("当前下载较多，请稍后再试", 429)
            job = Job(
                id=uuid.uuid4().hex,
                status="queued",
                progress=0,
                filename=None,
                error=None,
                path=None,
                directory=Path(tempfile.mkdtemp(prefix="job-", dir=self._root)),
                created_at=time.monotonic(),
            )
            self._jobs[job.id] = job
        threading.Thread(
            target=self._run,
            args=(job, url, format_id),
            name=f"suixia-{job.id[:8]}",
            daemon=True,
        ).start()
        return job.id

    def snapshot(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return _public(job)

    def take_file(self, job_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None, "missing"
            if job.status != "finished" or job.path is None:
                return None, job.status
            payload = (job.path, job.filename or job.path.name, job.directory)
            job.path = None
            self._jobs.pop(job_id, None)
            return payload, "ok"

    def reset(self) -> None:
        with self._lock:
            directories = [job.directory for job in self._jobs.values()]
            self._jobs.clear()
        for directory in directories:
            shutil.rmtree(directory, ignore_errors=True)

    def _run(self, job: Job, url: str, format_id: str) -> None:
        with _slots:
            with self._lock:
                if job.id not in self._jobs:
                    return
                job.status = "downloading"

            def on_progress(value: float) -> None:
                with self._lock:
                    if job.id in self._jobs and job.status == "downloading":
                        job.progress = value

            try:
                path, filename = download_media(url, format_id, job.directory, on_progress)
            except UserFacingError as exc:
                self._fail(job, exc.message)
                return
            except Exception:
                self._fail(job, "下载没有完成，请重试")
                return
            with self._lock:
                if job.id not in self._jobs:
                    shutil.rmtree(job.directory, ignore_errors=True)
                    return
                job.path = path
                job.filename = filename
                job.progress = 1
                job.status = "finished"

    def _fail(self, job: Job, message: str) -> None:
        with self._lock:
            if job.id not in self._jobs:
                return
            job.status = "error"
            job.error = message
        shutil.rmtree(job.directory, ignore_errors=True)

    def _sweep_locked(self) -> None:
        now = time.monotonic()
        stale = [job for job in self._jobs.values() if now - job.created_at > JOB_TTL_SECONDS]
        for job in stale:
            self._jobs.pop(job.id, None)
            shutil.rmtree(job.directory, ignore_errors=True)


def _public(job: Job) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "progress": round(job.progress, 4),
        "filename": job.filename,
        "error": job.error,
    }


store = JobStore()
