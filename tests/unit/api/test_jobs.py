"""Tests for the background JobManager."""

from __future__ import annotations

from momentum.api.jobs import JobManager, Progress


def _sync() -> JobManager:
    # Synchronous runner → deterministic, terminal-on-return jobs.
    return JobManager(runner=lambda fn: fn())


def test_successful_job_records_result_and_progress() -> None:
    mgr = _sync()
    seen: list[tuple[float, str]] = []

    def fn(progress: Progress) -> dict[str, object]:
        progress(0.5, "halfway")
        seen.append((0.5, "halfway"))
        return {"ok": True}

    job = mgr.submit("demo", fn)
    assert job.status == "succeeded"
    assert job.progress == 1.0
    assert job.result == {"ok": True}
    assert job.error is None
    assert job.finished_at is not None
    assert seen == [(0.5, "halfway")]


def test_failed_job_captures_error() -> None:
    mgr = _sync()

    def boom(progress: Progress) -> dict[str, object]:
        raise RuntimeError("kaboom")

    job = mgr.submit("demo", boom)
    assert job.status == "failed"
    assert job.error is not None and "kaboom" in job.error
    assert job.result is None


def test_get_and_recent() -> None:
    mgr = _sync()
    a = mgr.submit("x", lambda p: {"n": 1})
    b = mgr.submit("y", lambda p: {"n": 2})
    assert mgr.get(a.id) is a
    assert mgr.get("nope") is None
    recent = mgr.recent()
    assert [j.id for j in recent] == [b.id, a.id]  # newest first


def test_history_is_pruned() -> None:
    mgr = JobManager(runner=lambda fn: fn(), max_history=3)
    ids = [mgr.submit("k", lambda p: {}).id for _ in range(5)]
    assert mgr.get(ids[0]) is None  # oldest evicted
    assert mgr.get(ids[-1]) is not None
    assert len(mgr.recent(50)) == 3


def test_progress_is_clamped() -> None:
    mgr = _sync()

    def fn(progress: Progress) -> dict[str, object]:
        progress(5.0, "over")  # clamped to 1.0 transiently, then set to 1.0 on success
        return {}

    job = mgr.submit("demo", fn)
    assert 0.0 <= job.progress <= 1.0
