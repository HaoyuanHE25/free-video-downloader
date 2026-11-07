"""总结任务。和下载队列分开，重启后清空。"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.downloader import UserFacingError
from app.summary import summarize

MAX_PENDING = 4
JOB_TTL_SECONDS = 30 * 60


@dataclass
class SummaryJob:
    id: str
    status: str
    error: str | None
    result: dict | None
    transcript: dict
    directory: Path
    created_at: float


class SummaryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, SummaryJob] = {}
        self._root = Path(tempfile.gettempdir()) / "suixia-summary"
        self._root.mkdir(parents=True, exist_ok=True)

    def submit(self, transcript: dict, directory: Path) -> str:
        with self._lock:
            self._sweep_locked()
            active = sum(1 for job in self._jobs.values() if job.status in {"queued", "summarizing"})
            if active >= MAX_PENDING:
                raise UserFacingError("当前总结较多，请稍后再试", 429)
            job = SummaryJob(
                id=uuid.uuid4().hex,
                status="queued",
                error=None,
                result=None,
                transcript=transcript,
                directory=directory,
                created_at=time.monotonic(),
            )
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), name=f"suixia-summary-{job.id[:8]}", daemon=True).start()
        return job.id

    def snapshot(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                "id": job.id,
                "status": job.status,
                "error": job.error,
                "result": job.result,
            }

    def reset(self) -> None:
        with self._lock:
            directories = [job.directory for job in self._jobs.values()]
            self._jobs.clear()
        for directory in directories:
            shutil.rmtree(directory, ignore_errors=True)

    def _run(self, job: SummaryJob) -> None:
        with self._lock:
            if job.id not in self._jobs:
                return
            job.status = "summarizing"
        try:
            result = summarize(job.transcript["cues"], bool(job.transcript.get("truncated")))
        except UserFacingError as exc:
            self._fail(job, exc.message)
            return
        except Exception:
            self._fail(job, "总结失败，请重试")
            return
        with self._lock:
            if job.id not in self._jobs:
                shutil.rmtree(job.directory, ignore_errors=True)
                return
            job.result = result
            job.status = "finished"
        shutil.rmtree(job.directory, ignore_errors=True)

    def _fail(self, job: SummaryJob, message: str) -> None:
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


store = SummaryStore()
