import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_importing_task_worker_has_no_side_effects():
    """Importing the worker must not touch the network, Postgres or Settings.

    Regression guard for docs/suggestions.md #4.9: initialize_settings() used to
    run at module scope, which took down the whole pytest collection wherever
    Ollama was not running.
    """
    with patch("core.config.initialize_settings") as init_llama, \
         patch("app.settings.init_settings") as init_secrets:
        sys.modules.pop("infrastructure.tasks.task_worker", None)
        import infrastructure.tasks.task_worker  # noqa: F401

    init_llama.assert_not_called()
    init_secrets.assert_not_called()


def test_default_worker_concurrency_is_two(monkeypatch):
    from infrastructure.tasks import task_worker

    monkeypatch.delenv("WORKER_CONCURRENCY", raising=False)
    assert task_worker.get_worker_concurrency() == 2


def test_worker_concurrency_respects_env(monkeypatch):
    from infrastructure.tasks import task_worker

    monkeypatch.setenv("WORKER_CONCURRENCY", "5")
    assert task_worker.get_worker_concurrency() == 5


def test_worker_concurrency_capped_at_max(monkeypatch):
    from infrastructure.tasks import task_worker

    monkeypatch.setenv("WORKER_CONCURRENCY", "20")
    assert task_worker.get_worker_concurrency() == task_worker.MAX_WORKER_CONCURRENCY


def test_worker_concurrency_minimum_one(monkeypatch):
    from infrastructure.tasks import task_worker

    monkeypatch.setenv("WORKER_CONCURRENCY", "0")
    assert task_worker.get_worker_concurrency() == 1


def test_run_worker_spawns_concurrent_claim_loops(monkeypatch):
    from infrastructure.tasks import task_worker

    monkeypatch.setenv("WORKER_CONCURRENCY", "3")

    call_counts = {}

    async def fake_claim_loop(loop_id):
        call_counts[loop_id] = call_counts.get(loop_id, 0) + 1

    async def fake_check_stuck_tasks():
        await asyncio.sleep(3600)

    with patch.object(task_worker, "claim_loop", side_effect=fake_claim_loop), \
         patch.object(task_worker, "check_stuck_tasks", side_effect=fake_check_stuck_tasks):
        asyncio.run(task_worker.run_worker())

    assert set(call_counts.keys()) == {0, 1, 2}
