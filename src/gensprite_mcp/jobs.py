"""Bounded durable jobs for local processing; states always reflect actual outcomes."""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


class JobManager:
    def __init__(self, root: Path):
        self.root = root.resolve() / "jobs"
        if self.root.is_symlink() or not self.root.resolve().is_relative_to(root.resolve()):
            raise ValueError("Job directory escapes the asset store")
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks: dict[str, asyncio.Task] = {}
        self.records: dict[str, dict] = {}

    def _path(self, job_id: str) -> Path:
        if not re.fullmatch(r"j_[0-9a-f]{32}", job_id):
            raise ValueError("Invalid job ID")
        path = self.root / f"{job_id}.json"
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Unsafe job path")
        return path

    def _save(self, data: dict) -> None:
        path = self._path(data["job_id"])
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(data, default=str), encoding="utf-8")
        temporary.replace(path)

    def get(self, job_id: str) -> dict[str, Any]:
        path = self._path(job_id)
        if not path.exists():
            raise ValueError("Job not found")
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("Job record exceeds the 1 MiB limit")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["status"] in ("queued", "running") and job_id not in self.tasks:
            data.update(status="failed", error="Processing was interrupted; submit a new job")
            self._save(data)
        return data

    def submit(self, kind: str, work: Callable[[], dict]) -> dict[str, Any]:
        if sum(not task.done() for task in self.tasks.values()) >= 8:
            raise ValueError("At most eight local jobs may be active")
        job_id = f"j_{uuid4().hex}"
        data = dict(
            job_id=job_id,
            operation_id=job_id,
            kind=kind,
            status="queued",
            progress=0,
            created_at=datetime.now(timezone.utc).isoformat(),
            output=None,
            error=None,
        )
        self._save(data)

        async def run() -> None:
            try:
                if data["status"] == "cancelled":
                    return
                data.update(status="running", progress=10)
                self._save(data)
                result = await asyncio.to_thread(work)
                if data["status"] != "cancelled":
                    data.update(status="completed", progress=100, output=result)
                    self._save(data)
            except asyncio.CancelledError:
                data.update(status="cancelled", output=None)
                self._save(data)
            except Exception as exc:
                if data["status"] != "cancelled":
                    data.update(status="failed", output=None, error=str(exc)[:2000])
                    self._save(data)
            finally:
                self.tasks.pop(job_id, None)
                self.records.pop(job_id, None)

        self.records[job_id] = data
        self.tasks[job_id] = asyncio.create_task(run())
        return {**data, "poll": {"tool": "check_job_status", "arguments": {"job_id": job_id}}}

    async def check(self, job_id: str, wait_seconds: int = 0) -> dict[str, Any]:
        if type(wait_seconds) is not int or not 0 <= wait_seconds <= 30:
            raise ValueError("wait_seconds must be an integer from 0 through 30")
        self._path(job_id)
        task = self.tasks.get(job_id)
        if task and wait_seconds and self.get(job_id)["status"] != "cancelled":
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass
        data = self.get(job_id)
        if data["status"] == "completed":
            data["assets"] = data["output"].get("assets", [data["output"]])
        return data

    def cancel(self, job_id: str) -> dict[str, Any]:
        data = self.get(job_id)
        if data["status"] in ("queued", "running"):
            data = self.records.get(job_id, data)
            data.update(status="cancelled", output=None)
            self._save(data)
        return data

    def active(self) -> dict:
        return {
            "jobs": [self.get(key) for key, task in list(self.tasks.items()) if not task.done()]
        }
