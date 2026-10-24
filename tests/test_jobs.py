import asyncio
import threading

import pytest

from gensprite_mcp.jobs import JobManager


def test_jobs_report_actual_success_failure_cancel_and_restart(tmp_path):
    async def exercise():
        jobs = JobManager(tmp_path)
        submitted = jobs.submit("image", lambda: {"asset_id": "real-result"})
        result = await jobs.check(submitted["job_id"], wait_seconds=2)
        assert result["status"] == "completed"
        assert result["output"]["asset_id"] == "real-result"
        assert JobManager(tmp_path).get(submitted["job_id"])["status"] == "completed"
        failed = jobs.submit("image", lambda: (_ for _ in ()).throw(ValueError("invalid pixels")))
        assert (await jobs.check(failed["job_id"], 2))["status"] == "failed"
        cancelled = jobs.submit("image", lambda: {"should_not_be_claimed": True})
        assert jobs.cancel(cancelled["job_id"])["status"] == "cancelled"
        await asyncio.sleep(0.02)
        assert jobs.get(cancelled["job_id"])["output"] is None
        with pytest.raises(ValueError, match="ID"):
            jobs.get("../secret")

    asyncio.run(exercise())


def test_cancelled_workers_keep_the_concurrency_slot_until_processing_exits(tmp_path):
    async def exercise():
        jobs = JobManager(tmp_path)
        release = threading.Event()
        try:
            submitted = [jobs.submit("blocking", lambda: release.wait(3) or {}) for _ in range(8)]
            await asyncio.sleep(0.05)
            for item in submitted:
                jobs.cancel(item["job_id"])
            with pytest.raises(ValueError, match="eight"):
                jobs.submit("overflow", lambda: {})
        finally:
            release.set()
            await asyncio.sleep(0.05)

    asyncio.run(exercise())


def test_cancelled_worker_error_does_not_replace_terminal_cancellation(tmp_path):
    async def exercise():
        jobs = JobManager(tmp_path)
        release = threading.Event()

        def work():
            release.wait(3)
            raise ValueError("Late worker error")

        job = jobs.submit("late_failure", work)
        task = jobs.tasks[job["job_id"]]
        await asyncio.sleep(0.02)
        jobs.cancel(job["job_id"])
        release.set()
        await asyncio.wait_for(task, timeout=3)
        result = jobs.get(job["job_id"])
        assert result["status"] == "cancelled"
        assert result["output"] is None
        assert result["error"] is None

    asyncio.run(exercise())
