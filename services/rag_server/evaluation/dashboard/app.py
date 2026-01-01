"""Streamlit dashboard for benchmark results visualization.

Run with: streamlit run evaluation/dashboard/app.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from evaluation.results_store import BenchmarkResultsStore


# Page config
st.set_page_config(
    page_title="RAG Benchmark Dashboard",
    page_icon="📊",
    layout="wide",
)


@st.cache_resource
def get_store() -> BenchmarkResultsStore:
    """Get cached results store instance."""
    return BenchmarkResultsStore()


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        return f"{seconds / 3600:.1f}h"


def main():
    st.title("RAG Benchmark Dashboard")

    store = get_store()

    # Sidebar filters
    st.sidebar.header("Filters")

    # Get available datasets
    runs = store.list_runs(limit=1000)
    datasets = sorted(set(r.dataset_name for r in runs)) if runs else []

    selected_dataset = st.sidebar.selectbox(
        "Dataset",
        options=["All"] + datasets,
        index=0,
    )

    date_range = st.sidebar.selectbox(
        "Time Range",
        options=["All Time", "Last 7 Days", "Last 30 Days", "Last 90 Days"],
        index=0,
    )

    # Apply filters
    dataset_filter = None if selected_dataset == "All" else selected_dataset
    filtered_runs = store.list_runs(dataset_name=dataset_filter, limit=500)

    # Apply date filter
    if date_range != "All Time":
        days = {"Last 7 Days": 7, "Last 30 Days": 30, "Last 90 Days": 90}[date_range]
        cutoff = datetime.now() - timedelta(days=days)
        filtered_runs = [r for r in filtered_runs if r.timestamp > cutoff]

    if not filtered_runs:
        st.warning("No benchmark runs found. Run a benchmark first!")
        st.code("just bench-run squad --samples 50")
        return

    # Summary metrics
    st.header("Summary")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Runs", len(filtered_runs))

    with col2:
        datasets_count = len(set(r.dataset_name for r in filtered_runs))
        st.metric("Datasets", datasets_count)

    latest = filtered_runs[0]
    with col3:
        recall = latest.get_metric("recall@k")
        st.metric(
            "Latest Recall@K",
            f"{recall:.1%}" if recall else "N/A",
        )

    with col4:
        st.metric(
            "Latest Latency (P50)",
            f"{latest.get_metric('latency_p50_ms'):.0f}ms" if latest.get_metric('latency_p50_ms') else "N/A",
        )

    # Metric trends
    st.header("Metric Trends")

    # Create DataFrame for charting
    chart_data = []
    for run in reversed(filtered_runs):  # Oldest to newest
        row = {
            "timestamp": run.timestamp,
            "run_id": run.run_id,
            "dataset": run.dataset_name,
        }
        for metric in run.metrics:
            row[metric.name] = metric.score
        chart_data.append(row)

    df = pd.DataFrame(chart_data)

    if not df.empty:
        # Metric selector
        available_metrics = [c for c in df.columns if c not in ["timestamp", "run_id", "dataset"]]

        selected_metrics = st.multiselect(
            "Select metrics to display",
            options=available_metrics,
            default=["recall@k", "mrr", "answer_rate"] if all(m in available_metrics for m in ["recall@k", "mrr", "answer_rate"]) else available_metrics[:3],
        )

        if selected_metrics:
            # Create tabs for different chart types
            tab1, tab2 = st.tabs(["Line Chart", "Data Table"])

            with tab1:
                chart_df = df[["timestamp"] + selected_metrics].set_index("timestamp")
                st.line_chart(chart_df)

            with tab2:
                st.dataframe(
                    df[["timestamp", "run_id", "dataset"] + selected_metrics],
                    use_container_width=True,
                )

    # Latest run details
    st.header("Latest Run Details")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader(f"Run: {latest.run_id}")
        st.write(f"**Dataset:** {latest.dataset_name}")
        st.write(f"**Sample Size:** {latest.sample_size}")
        st.write(f"**Timestamp:** {latest.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        st.write(f"**Total Time:** {format_duration(latest.total_time_seconds)}")
        st.write(f"**Notes:** {latest.notes or 'None'}")

    with col2:
        st.subheader("Metrics")
        metrics_df = pd.DataFrame([
            {"Metric": m.name, "Score": m.score, "Samples": m.sample_count}
            for m in latest.metrics
        ])
        st.dataframe(metrics_df, use_container_width=True, hide_index=True)

    # Run history table
    st.header("Run History")

    history_data = []
    for run in filtered_runs[:50]:  # Show last 50
        row = {
            "Run ID": run.run_id,
            "Dataset": run.dataset_name,
            "Samples": run.sample_size,
            "Recall@K": run.get_metric("recall@k"),
            "MRR": run.get_metric("mrr"),
            "Answer Rate": run.get_metric("answer_rate"),
            "Latency P50": run.get_metric("latency_p50_ms"),
            "Duration": format_duration(run.total_time_seconds),
            "Timestamp": run.timestamp.strftime("%Y-%m-%d %H:%M"),
        }
        history_data.append(row)

    history_df = pd.DataFrame(history_data)

    # Format percentage columns
    for col in ["Recall@K", "MRR", "Answer Rate"]:
        if col in history_df.columns:
            history_df[col] = history_df[col].apply(
                lambda x: f"{x:.1%}" if pd.notna(x) else "N/A"
            )

    if "Latency P50" in history_df.columns:
        history_df["Latency P50"] = history_df["Latency P50"].apply(
            lambda x: f"{x:.0f}ms" if pd.notna(x) else "N/A"
        )

    st.dataframe(history_df, use_container_width=True, hide_index=True)

    # Dataset comparison
    if len(datasets) > 1:
        st.header("Dataset Comparison")

        comparison_data = []
        for dataset in datasets:
            dataset_runs = [r for r in filtered_runs if r.dataset_name == dataset]
            if dataset_runs:
                latest_run = dataset_runs[0]
                comparison_data.append({
                    "Dataset": dataset,
                    "Runs": len(dataset_runs),
                    "Recall@K": latest_run.get_metric("recall@k"),
                    "MRR": latest_run.get_metric("mrr"),
                    "Answer Rate": latest_run.get_metric("answer_rate"),
                    "Avg Latency": latest_run.avg_latency_ms,
                })

        if comparison_data:
            comp_df = pd.DataFrame(comparison_data)
            st.bar_chart(
                comp_df.set_index("Dataset")[["Recall@K", "MRR", "Answer Rate"]],
            )


if __name__ == "__main__":
    main()
