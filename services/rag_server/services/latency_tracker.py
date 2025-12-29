"""Latency tracking service for query response times.

Tracks query latencies during evaluation runs and computes
percentile statistics (P50, P95, etc.).
"""

import statistics
from dataclasses import dataclass, field

from schemas.metrics import LatencyMetrics


@dataclass
class LatencyTracker:
    """Tracks query latencies and computes statistics.

    Usage:
        tracker = LatencyTracker()
        for query in queries:
            start = time.perf_counter()
            result = await query_rag(query)
            elapsed_ms = (time.perf_counter() - start) * 1000
            tracker.record(elapsed_ms)
        metrics = tracker.get_metrics()
    """

    _latencies: list[float] = field(default_factory=list)

    def record(self, latency_ms: float) -> None:
        """Record a query latency.

        Args:
            latency_ms: Query latency in milliseconds
        """
        self._latencies.append(latency_ms)

    def get_metrics(self) -> LatencyMetrics:
        """Get latency metrics for all recorded queries.

        Returns:
            LatencyMetrics with percentiles and averages
        """
        if not self._latencies:
            return LatencyMetrics(
                avg_query_time_ms=0.0,
                p50_query_time_ms=0.0,
                p95_query_time_ms=0.0,
                min_query_time_ms=0.0,
                max_query_time_ms=0.0,
                total_queries=0,
            )

        sorted_latencies = sorted(self._latencies)
        n = len(sorted_latencies)

        # Calculate percentiles
        p50_idx = int(n * 0.50)
        p95_idx = min(int(n * 0.95), n - 1)

        return LatencyMetrics(
            avg_query_time_ms=round(statistics.mean(sorted_latencies), 2),
            p50_query_time_ms=round(sorted_latencies[p50_idx], 2),
            p95_query_time_ms=round(sorted_latencies[p95_idx], 2),
            min_query_time_ms=round(sorted_latencies[0], 2),
            max_query_time_ms=round(sorted_latencies[-1], 2),
            total_queries=n,
        )

    def reset(self) -> None:
        """Reset all recorded latencies."""
        self._latencies.clear()

    @property
    def count(self) -> int:
        """Number of recorded latencies."""
        return len(self._latencies)
