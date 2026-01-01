"""SQLite-based results store for benchmark persistence.

Stores benchmark run results for historical tracking and trend analysis.
"""

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class MetricResult:
    """A single metric result."""

    name: str
    score: float
    sample_count: int
    per_sample_scores: list[float] | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "sample_count": self.sample_count,
            "per_sample_scores": self.per_sample_scores,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MetricResult":
        return cls(
            name=data["name"],
            score=data["score"],
            sample_count=data["sample_count"],
            per_sample_scores=data.get("per_sample_scores"),
        )


@dataclass
class BenchmarkRun:
    """A complete benchmark run with all metrics."""

    run_id: str
    dataset_name: str
    dataset_info: dict
    sample_size: int
    metrics: list[MetricResult]
    total_time_seconds: float
    upload_time_seconds: float
    query_time_seconds: float
    avg_latency_ms: float
    timestamp: datetime = field(default_factory=datetime.now)
    notes: str = ""
    config_snapshot: dict = field(default_factory=dict)

    def get_metric(self, name: str) -> float | None:
        """Get a specific metric value by name."""
        for m in self.metrics:
            if m.name == name:
                return m.score
        return None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "dataset_name": self.dataset_name,
            "dataset_info": self.dataset_info,
            "sample_size": self.sample_size,
            "metrics": [m.to_dict() for m in self.metrics],
            "total_time_seconds": self.total_time_seconds,
            "upload_time_seconds": self.upload_time_seconds,
            "query_time_seconds": self.query_time_seconds,
            "avg_latency_ms": self.avg_latency_ms,
            "timestamp": self.timestamp.isoformat(),
            "notes": self.notes,
            "config_snapshot": self.config_snapshot,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BenchmarkRun":
        return cls(
            run_id=data["run_id"],
            dataset_name=data["dataset_name"],
            dataset_info=data["dataset_info"],
            sample_size=data["sample_size"],
            metrics=[MetricResult.from_dict(m) for m in data["metrics"]],
            total_time_seconds=data["total_time_seconds"],
            upload_time_seconds=data["upload_time_seconds"],
            query_time_seconds=data["query_time_seconds"],
            avg_latency_ms=data["avg_latency_ms"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            notes=data.get("notes", ""),
            config_snapshot=data.get("config_snapshot", {}),
        )


class BenchmarkResultsStore:
    """SQLite-based storage for benchmark results."""

    def __init__(self, db_path: Path | str | None = None):
        """Initialize the results store.

        Args:
            db_path: Path to SQLite database. Defaults to eval_data/benchmark_results.db
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "eval_data" / "benchmark_results.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    run_id TEXT PRIMARY KEY,
                    dataset_name TEXT NOT NULL,
                    dataset_info TEXT NOT NULL,
                    sample_size INTEGER NOT NULL,
                    metrics TEXT NOT NULL,
                    total_time_seconds REAL NOT NULL,
                    upload_time_seconds REAL NOT NULL,
                    query_time_seconds REAL NOT NULL,
                    avg_latency_ms REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    notes TEXT,
                    config_snapshot TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dataset_name
                ON benchmark_runs(dataset_name)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON benchmark_runs(timestamp)
            """)

            conn.commit()

    def save_run(self, run: BenchmarkRun) -> None:
        """Save a benchmark run to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO benchmark_runs
                (run_id, dataset_name, dataset_info, sample_size, metrics,
                 total_time_seconds, upload_time_seconds, query_time_seconds,
                 avg_latency_ms, timestamp, notes, config_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.dataset_name,
                    json.dumps(run.dataset_info),
                    run.sample_size,
                    json.dumps([m.to_dict() for m in run.metrics]),
                    run.total_time_seconds,
                    run.upload_time_seconds,
                    run.query_time_seconds,
                    run.avg_latency_ms,
                    run.timestamp.isoformat(),
                    run.notes,
                    json.dumps(run.config_snapshot),
                ),
            )
            conn.commit()

    def get_run(self, run_id: str) -> BenchmarkRun | None:
        """Get a specific run by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM benchmark_runs WHERE run_id = ?",
                (run_id,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_run(row)
            return None

    def list_runs(
        self,
        dataset_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BenchmarkRun]:
        """List benchmark runs with optional filtering."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if dataset_name:
                cursor = conn.execute(
                    """
                    SELECT * FROM benchmark_runs
                    WHERE dataset_name = ?
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    (dataset_name, limit, offset),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM benchmark_runs
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )

            return [self._row_to_run(row) for row in cursor.fetchall()]

    def get_latest_run(self, dataset_name: str | None = None) -> BenchmarkRun | None:
        """Get the most recent run, optionally filtered by dataset."""
        runs = self.list_runs(dataset_name=dataset_name, limit=1)
        return runs[0] if runs else None

    def delete_run(self, run_id: str) -> bool:
        """Delete a run by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM benchmark_runs WHERE run_id = ?",
                (run_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_metric_history(
        self,
        metric_name: str,
        dataset_name: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get historical values for a specific metric.

        Returns list of {timestamp, run_id, score} dicts.
        """
        runs = self.list_runs(dataset_name=dataset_name, limit=limit)
        history = []

        for run in runs:
            score = run.get_metric(metric_name)
            if score is not None:
                history.append({
                    "timestamp": run.timestamp,
                    "run_id": run.run_id,
                    "score": score,
                    "dataset": run.dataset_name,
                })

        return history

    def get_summary_stats(self, dataset_name: str | None = None) -> dict:
        """Get summary statistics across runs."""
        runs = self.list_runs(dataset_name=dataset_name, limit=1000)

        if not runs:
            return {}

        # Aggregate metrics
        metric_values: dict[str, list[float]] = {}
        for run in runs:
            for metric in run.metrics:
                if metric.name not in metric_values:
                    metric_values[metric.name] = []
                metric_values[metric.name].append(metric.score)

        # Compute stats
        stats = {
            "total_runs": len(runs),
            "datasets": list(set(r.dataset_name for r in runs)),
            "metrics": {},
        }

        for name, values in metric_values.items():
            sorted_vals = sorted(values)
            stats["metrics"][name] = {
                "mean": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "latest": values[0],  # Most recent
                "p50": sorted_vals[len(sorted_vals) // 2],
            }

        return stats

    def _row_to_run(self, row: sqlite3.Row) -> BenchmarkRun:
        """Convert a database row to a BenchmarkRun."""
        return BenchmarkRun(
            run_id=row["run_id"],
            dataset_name=row["dataset_name"],
            dataset_info=json.loads(row["dataset_info"]),
            sample_size=row["sample_size"],
            metrics=[MetricResult.from_dict(m) for m in json.loads(row["metrics"])],
            total_time_seconds=row["total_time_seconds"],
            upload_time_seconds=row["upload_time_seconds"],
            query_time_seconds=row["query_time_seconds"],
            avg_latency_ms=row["avg_latency_ms"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            notes=row["notes"] or "",
            config_snapshot=json.loads(row["config_snapshot"] or "{}"),
        )
