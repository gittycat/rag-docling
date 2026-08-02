"""Eval job queueing.

Previously a second concurrent trigger got a 409 and was simply lost. Jobs now
queue behind the active one up to a bounded depth.
"""

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.job_manager import JobManager


class _BlockingManager(JobManager):
    """JobManager whose worker waits on an event instead of running an eval."""

    def __init__(self, runs_dir, max_queue_depth=2):
        super().__init__(runs_dir, max_queue_depth=max_queue_depth)
        self.release = threading.Event()
        self.started: list[str] = []
        self.finished = threading.Event()

    def _run_job(self, job_id, config, run_name):
        with self._lock:
            self._active_status = "running"
            self.started.append(job_id)
        try:
            self.release.wait(timeout=5)
        finally:
            with self._lock:
                self._active_status = "completed"
            self.finished.set()
            self._start_next_queued()


@pytest.fixture
def manager(tmp_path):
    jm = _BlockingManager(tmp_path)
    yield jm
    jm.release.set()


def test_first_job_starts_immediately(manager):
    job_id = manager.trigger(samples=1)

    assert manager.list_queued() == []
    active = manager.get_active_job()
    assert active is not None and active.job_id == job_id


def test_second_job_queues_instead_of_being_rejected(manager):
    first = manager.trigger(samples=1)
    second = manager.trigger(samples=1)

    queued = manager.list_queued()
    assert [q.job_id for q in queued] == [second]
    assert queued[0].position == 1
    assert manager.get_active_job().job_id == first


def test_queue_is_bounded(manager):
    manager.trigger(samples=1)
    manager.trigger(samples=1)
    manager.trigger(samples=1)

    with pytest.raises(RuntimeError, match="queue is full"):
        manager.trigger(samples=1)


def test_queued_job_starts_when_the_active_one_finishes(manager):
    first = manager.trigger(samples=1)
    second = manager.trigger(samples=1)

    manager.release.set()
    assert manager.finished.wait(timeout=5)

    # Give the promoted job a moment to claim the slot
    for _ in range(50):
        if second in manager.started:
            break
        threading.Event().wait(0.02)

    assert manager.started[:2] == [first, second]
    assert manager.list_queued() == []


def test_queued_job_can_be_cancelled_before_it_runs(manager):
    manager.trigger(samples=1)
    second = manager.trigger(samples=1)

    assert manager.cancel_queued(second) is True
    assert manager.list_queued() == []
    assert manager.cancel_queued(second) is False


def test_invalid_trigger_does_not_consume_the_slot(tmp_path):
    jm = JobManager(tmp_path)

    with pytest.raises(ValueError):
        jm.trigger(datasets=["not-a-dataset"])

    assert jm.get_active_job() is None
    assert jm.list_queued() == []


def test_samples_sidecar_is_not_indexed_as_a_run(tmp_path):
    (tmp_path / "abc_20260101_000000.json").write_text(
        json.dumps({"id": "abc", "name": "run", "created_at": "2026-01-01T00:00:00"})
    )
    (tmp_path / "abc_20260101_000000_samples.json").write_text(
        json.dumps({"run_id": "abc", "samples": []})
    )

    jm = JobManager(tmp_path)
    assert jm.index_existing_runs() == 1
    assert jm.get_run("abc") is not None
