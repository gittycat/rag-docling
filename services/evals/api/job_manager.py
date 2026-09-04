"""In-memory job store + background thread for running evals.

Only one eval job can run at a time. Jobs are tracked in memory; completed
run data is persisted to disk by EvaluationRunner and indexed here for
fast lookup.
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from api.dashboard import compute_dashboard_metrics
from api.schemas import (
    ActiveJobResponse,
    DashboardMetrics,
    ProgressInfo,
    QueuedJob,
    RetrievalFunnelOut,
    RunDetailResponse,
    RunSummary,
)
from evals.config import DatasetName, EvalConfig, EvalTier, MetricConfig, resolve_judge_config
from evals.runner import EvaluationRunner
from evals.samples import SAMPLES_SUFFIX

# Evals are serialized because they saturate the RAG server; queueing the rest is
# what turns a second request from a 409 into a wait.
DEFAULT_QUEUE_DEPTH = int(os.environ.get("EVAL_QUEUE_DEPTH", "5"))


@dataclass
class _PendingJob:
    job_id: str
    config: EvalConfig
    run_name: str
    created_at: datetime


def _extract_duration(data: dict) -> float | None:
    """Extract duration_seconds from run data, computing from timestamps as fallback."""
    if data.get("duration_seconds") is not None:
        return data["duration_seconds"]
    created = data.get("created_at")
    completed = data.get("completed_at")
    if not created or not completed:
        return None
    try:
        t0 = datetime.fromisoformat(created)
        t1 = datetime.fromisoformat(completed)
        return (t1 - t0).total_seconds()
    except (ValueError, TypeError):
        return None

logger = logging.getLogger(__name__)


class JobManager:
    """Manages eval job lifecycle: trigger, progress, cancellation, run index."""

    def __init__(self, runs_dir: Path, max_queue_depth: int = DEFAULT_QUEUE_DEPTH):
        self.runs_dir = runs_dir
        self.max_queue_depth = max_queue_depth
        self._lock = threading.Lock()

        # Active job state
        self._active_job_id: str | None = None
        self._active_status: str = "idle"
        self._active_progress: dict[str, Any] = {}
        self._active_created_at: datetime | None = None
        self._cancelled = threading.Event()
        self._thread: threading.Thread | None = None

        # Jobs waiting for the active one to finish, FIFO
        self._queue: deque[_PendingJob] = deque()

        # Run index: run_id -> (filepath, summary dict loaded from JSON)
        self._run_index: dict[str, tuple[Path, dict]] = {}

    # ── Startup ───────────────────────────────────────────────────────────

    def index_existing_runs(self) -> int:
        """Scan runs_dir and build an in-memory index. Returns count."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for filepath in sorted(self.runs_dir.glob("*.json")):
            # Sidecars sit next to their run and are not runs themselves
            if filepath.name.endswith(SAMPLES_SUFFIX):
                continue
            try:
                data = json.loads(filepath.read_text())
                run_id = data.get("id", filepath.stem.split("_")[0])
                self._run_index[run_id] = (filepath, data)
                count += 1
            except Exception as e:
                logger.warning(f"Skipping corrupt run file {filepath}: {e}")
        logger.info(f"Indexed {count} existing eval runs")
        return count

    # ── Trigger ───────────────────────────────────────────────────────────

    def trigger(
        self,
        *,
        name: str | None = None,
        tier: str = "generation",
        datasets: list[str] | None = None,
        samples: int = 100,
        seed: int | None = 42,
        judge_enabled: bool = True,
        groundedness: bool = True,
        rag_server_url: str = "http://rag-server:8001",
    ) -> str:
        """Start or queue an eval job. Returns job_id.

        Raises RuntimeError only when the queue is full — a second concurrent
        request waits its turn rather than being rejected outright.
        """
        # Validate before claiming a slot: a rejected request must not leave the
        # manager thinking a job is queued, which would block every later trigger.
        dataset_names = [DatasetName(d) for d in (datasets or ["ragbench"])]
        eval_tier = EvalTier(tier)

        job_id = str(uuid.uuid4())[:8]
        config = EvalConfig(
            datasets=dataset_names,
            samples_per_dataset=samples,
            seed=seed,
            rag_server_url=rag_server_url,
            runs_dir=self.runs_dir,
            tier=eval_tier,
            judge=resolve_judge_config(
                enabled=judge_enabled, datasets=dataset_names, tier=eval_tier
            ),
            metrics=MetricConfig(groundedness=groundedness),
        )
        pending = _PendingJob(
            job_id=job_id,
            config=config,
            run_name=name or f"eval-{job_id}",
            created_at=datetime.now(),
        )

        with self._lock:
            if self._active_job_id and self._active_status in ("queued", "running"):
                if len(self._queue) >= self.max_queue_depth:
                    raise RuntimeError(
                        f"Eval queue is full ({self.max_queue_depth} jobs waiting)"
                    )
                self._queue.append(pending)
                logger.info(f"Queued eval job {job_id} (position {len(self._queue)})")
                return job_id

            try:
                self._start_locked(pending)
            except Exception:
                # Release the slot rather than wedging the service on a job that never ran.
                self._active_job_id = None
                self._active_status = "failed"
                raise

        return job_id

    def _start_locked(self, pending: _PendingJob) -> None:
        """Claim the active slot and start the worker thread. Caller holds the lock."""
        self._active_job_id = pending.job_id
        self._active_status = "queued"
        self._active_progress = {}
        self._active_created_at = pending.created_at
        self._cancelled.clear()

        self._thread = threading.Thread(
            target=self._run_job,
            args=(pending.job_id, pending.config, pending.run_name),
            daemon=True,
        )
        self._thread.start()

    def _start_next_queued(self) -> None:
        """Promote the head of the queue, if any. Caller must not hold the lock."""
        with self._lock:
            while self._queue:
                pending = self._queue.popleft()
                try:
                    self._start_locked(pending)
                    return
                except Exception as e:
                    # A job that cannot even start must not stall the ones behind it
                    logger.error(f"Queued eval job {pending.job_id} failed to start: {e}")
                    self._active_job_id = None
                    self._active_status = "failed"

    def _run_job(self, job_id: str, config: EvalConfig, run_name: str) -> None:
        """Background thread target — runs async eval in a new event loop."""
        with self._lock:
            self._active_status = "running"

        def progress_callback(info: dict) -> None:
            with self._lock:
                self._active_progress = info

        runner = EvaluationRunner(config)
        try:
            result = asyncio.run(runner.run(
                name=run_name,
                progress_callback=progress_callback,
                cancelled=self._cancelled,
            ))
            filepath = self.runs_dir / f"{result.id}_{result.created_at.strftime('%Y%m%d_%H%M%S')}.json"
            if filepath.exists():
                data = json.loads(filepath.read_text())
                self._run_index[result.id] = (filepath, data)

            with self._lock:
                self._active_status = "completed"
        except Exception as e:
            logger.error(f"Eval job {job_id} failed: {e}")
            with self._lock:
                self._active_status = "failed"
                self._active_progress["error"] = str(e)
        finally:
            asyncio.run(runner.close())
            self._start_next_queued()

    # ── Active job ────────────────────────────────────────────────────────

    def get_active_job(self) -> ActiveJobResponse | None:
        with self._lock:
            if not self._active_job_id:
                return None
            if self._active_status not in ("queued", "running"):
                return None

            elapsed = 0.0
            if self._active_created_at:
                elapsed = (datetime.now() - self._active_created_at).total_seconds()

            progress = ProgressInfo(
                current_question=self._active_progress.get("current_question", 0),
                total_questions=self._active_progress.get("total_questions", 0),
                current_dataset=self._active_progress.get("current_dataset", ""),
                phase=self._active_progress.get("phase", "initializing"),
                elapsed_seconds=elapsed,
            )
            return ActiveJobResponse(
                job_id=self._active_job_id,
                status=self._active_status,
                progress=progress,
            )

    @property
    def active_created_at(self) -> datetime | None:
        with self._lock:
            return self._active_created_at

    def cancel_active(self) -> bool:
        """Cancel the running job. Returns True if there was one to cancel."""
        with self._lock:
            if not self._active_job_id or self._active_status not in ("queued", "running"):
                return False
            self._cancelled.set()
            self._active_status = "cancelled"
            return True

    def list_queued(self) -> list[QueuedJob]:
        """Jobs waiting behind the active one, in the order they will run."""
        with self._lock:
            return [
                QueuedJob(
                    job_id=p.job_id,
                    position=i + 1,
                    created_at=p.created_at,
                    name=p.run_name,
                    tier=p.config.tier.value,
                    datasets=[d.value for d in p.config.datasets],
                )
                for i, p in enumerate(self._queue)
            ]

    def cancel_queued(self, job_id: str) -> bool:
        """Drop a job from the queue before it starts."""
        with self._lock:
            for pending in list(self._queue):
                if pending.job_id == job_id:
                    self._queue.remove(pending)
                    return True
        return False

    # ── Run index ─────────────────────────────────────────────────────────

    def list_runs(self, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        """Return (runs_data_list, total_count) sorted newest first."""
        all_runs = sorted(
            self._run_index.values(),
            key=lambda item: item[1].get("created_at", ""),
            reverse=True,
        )
        total = len(all_runs)
        page = all_runs[offset : offset + limit]
        return [data for _, data in page], total

    def get_run(self, run_id: str) -> dict | None:
        entry = self._run_index.get(run_id)
        return entry[1] if entry else None

    def get_latest_run(self) -> dict | None:
        if not self._run_index:
            return None
        _, data = max(
            self._run_index.values(),
            key=lambda item: item[1].get("created_at", ""),
        )
        return data

    # ── Helpers ───────────────────────────────────────────────────────────

    def run_to_summary(self, data: dict) -> RunSummary:
        tier = data.get("metadata", {}).get("tier", "")
        scorecard = data.get("scorecard") or {}
        funnel = data.get("retrieval_funnel")
        dm = compute_dashboard_metrics(scorecard, tier=tier, funnel=funnel)
        ws = data.get("weighted_score", {})
        metrics = {m["name"]: m["value"] for m in scorecard.get("metrics", [])}
        groups = scorecard.get("by_group", {})
        return RunSummary(
            id=data["id"],
            name=data.get("name", ""),
            created_at=data.get("created_at", ""),
            completed_at=data.get("completed_at"),
            tier=tier,
            datasets=data.get("datasets", []),
            question_count=data.get("question_count", 0),
            error_count=data.get("error_count", 0),
            duration_seconds=_extract_duration(data),
            weighted_score=ws.get("score") if ws else None,
            llm_model=data.get("config", {}).get("llm_model"),
            dashboard_metrics=dm,
            retrieval_funnel=RetrievalFunnelOut(**funnel) if funnel else None,
            metrics=metrics,
            groups=groups,
        )

    def run_to_detail(self, data: dict) -> RunDetailResponse:
        tier = data.get("metadata", {}).get("tier", "")
        funnel = data.get("retrieval_funnel")
        dm = compute_dashboard_metrics(data.get("scorecard"), tier=tier, funnel=funnel)
        ws = data.get("weighted_score", {})
        return RunDetailResponse(
            id=data["id"],
            name=data.get("name", ""),
            created_at=data.get("created_at", ""),
            completed_at=data.get("completed_at"),
            tier=tier,
            datasets=data.get("datasets", []),
            config=data.get("config", {}),
            scorecard=data.get("scorecard"),
            weighted_score=ws,
            question_count=data.get("question_count", 0),
            error_count=data.get("error_count", 0),
            duration_seconds=_extract_duration(data),
            metadata=data.get("metadata", {}),
            dashboard_metrics=dm,
            retrieval_funnel=RetrievalFunnelOut(**funnel) if funnel else None,
        )
