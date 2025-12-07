"""Report generation for RAG evaluation results.

Supports DeepEval-based evaluation reports.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from .data_models import EndToEndEvaluationResult, RetrievalEvaluationResult, GenerationEvaluationResult
from .reranking_eval import RerankingComparison


class EvaluationReportGenerator:
    def __init__(self, output_dir: Path | str = "eval_data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_text_report(
        self,
        result: EndToEndEvaluationResult,
        title: str = "RAG Evaluation Report",
    ) -> str:
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append(f"{title}")
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("=" * 80)
        report_lines.append("")

        report_lines.append("RETRIEVAL METRICS")
        report_lines.append("-" * 80)
        if result.retrieval.context_precision is not None:
            status = self._get_status_indicator(result.retrieval.context_precision, 0.85)
            report_lines.append(f"  Context Precision:     {result.retrieval.context_precision:.3f} {status}")
        if result.retrieval.context_recall is not None:
            status = self._get_status_indicator(result.retrieval.context_recall, 0.90)
            report_lines.append(f"  Context Recall:        {result.retrieval.context_recall:.3f} {status}")
        report_lines.append("")

        report_lines.append("GENERATION METRICS")
        report_lines.append("-" * 80)
        if result.generation.faithfulness is not None:
            status = self._get_status_indicator(result.generation.faithfulness, 0.90)
            report_lines.append(f"  Faithfulness:          {result.generation.faithfulness:.3f} {status}")
        if result.generation.answer_relevancy is not None:
            status = self._get_status_indicator(result.generation.answer_relevancy, 0.85)
            report_lines.append(f"  Answer Relevancy:      {result.generation.answer_relevancy:.3f} {status}")
        if result.generation.answer_correctness is not None:
            status = self._get_status_indicator(result.generation.answer_correctness, 0.85)
            report_lines.append(f"  Answer Correctness:    {result.generation.answer_correctness:.3f} {status}")
        report_lines.append("")

        report_lines.append("OVERALL")
        report_lines.append("-" * 80)
        if result.overall_score is not None:
            status = self._get_status_indicator(result.overall_score, 0.85)
            report_lines.append(f"  Overall Score:         {result.overall_score:.3f} {status}")
        report_lines.append(f"  Sample Count:          {result.sample_count}")
        report_lines.append("=" * 80)

        return "\n".join(report_lines)

    def generate_reranking_report(
        self, comparison: RerankingComparison, title: str = "Reranking Effectiveness Report"
    ) -> str:
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append(f"{title}")
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("=" * 80)
        report_lines.append("")

        report_lines.append("PRECISION METRICS")
        report_lines.append("-" * 80)
        report_lines.append(f"  Before Reranking:")
        report_lines.append(f"    Precision@1:         {comparison.before_precision_at_1:.3f}")
        report_lines.append(f"    Precision@3:         {comparison.before_precision_at_3:.3f}")
        report_lines.append("")
        report_lines.append(f"  After Reranking:")
        report_lines.append(f"    Precision@1:         {comparison.after_precision_at_1:.3f}")
        report_lines.append(f"    Precision@3:         {comparison.after_precision_at_3:.3f}")
        report_lines.append("")

        report_lines.append("RANKING QUALITY")
        report_lines.append("-" * 80)
        report_lines.append(f"  Before NDCG:           {comparison.before_ndcg:.3f}")
        report_lines.append(f"  After NDCG:            {comparison.after_ndcg:.3f}")
        report_lines.append("")

        report_lines.append("IMPROVEMENTS")
        report_lines.append("-" * 80)
        improvement_status = self._get_improvement_indicator(comparison.precision_improvement)
        report_lines.append(f"  Precision Improvement: {comparison.precision_improvement:+.1f}% {improvement_status}")
        ndcg_status = self._get_improvement_indicator(comparison.ndcg_improvement)
        report_lines.append(f"  NDCG Improvement:      {comparison.ndcg_improvement:+.1f}% {ndcg_status}")
        report_lines.append(f"  Sample Count:          {comparison.sample_count}")
        report_lines.append("=" * 80)

        return "\n".join(report_lines)

    def save_report(
        self,
        result: EndToEndEvaluationResult | RerankingComparison,
        filename: str | None = None,
    ) -> Path:
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"evaluation_report_{timestamp}.txt"

        report_path = self.output_dir / filename

        if isinstance(result, EndToEndEvaluationResult):
            report_text = self.generate_text_report(result)
        elif isinstance(result, RerankingComparison):
            report_text = self.generate_reranking_report(result)
        else:
            raise ValueError(f"Unsupported result type: {type(result)}")

        with open(report_path, "w") as f:
            f.write(report_text)

        return report_path

    def save_json_results(
        self, result: EndToEndEvaluationResult, filename: str | None = None
    ) -> Path:
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"evaluation_results_{timestamp}.json"

        json_path = self.output_dir / filename

        with open(json_path, "w") as f:
            json.dump(result.model_dump(), f, indent=2)

        return json_path

    def _get_status_indicator(self, value: float, threshold: float) -> str:
        if value >= threshold + 0.10:
            return "✓ Excellent"
        elif value >= threshold:
            return "✓ Good"
        elif value >= threshold - 0.10:
            return "⚠ Needs Improvement"
        else:
            return "✗ Poor"

    def _get_improvement_indicator(self, improvement: float) -> str:
        if improvement >= 15.0:
            return "✓ Excellent"
        elif improvement >= 10.0:
            return "✓ Good"
        elif improvement >= 5.0:
            return "⚠ Moderate"
        elif improvement > 0:
            return "⚠ Minimal"
        else:
            return "✗ None/Negative"

    def generate_deepeval_report(
        self,
        results: Any,  # DeepEval results object
        title: str = "DeepEval RAG Evaluation Report",
    ) -> str:
        """Generate text report from DeepEval evaluation results.

        Args:
            results: DeepEval evaluation results
            title: Report title

        Returns:
            Formatted text report
        """
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append(f"{title}")
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"Framework: DeepEval with Anthropic Claude")
        report_lines.append("=" * 80)
        report_lines.append("")

        # DeepEval results may have test_results attribute
        if hasattr(results, "test_results"):
            test_results = results.test_results
            total_tests = len(test_results)
            passed_tests = sum(1 for tr in test_results if hasattr(tr, "success") and tr.success)

            report_lines.append("OVERALL RESULTS")
            report_lines.append("-" * 80)
            report_lines.append(f"  Total Test Cases:      {total_tests}")
            report_lines.append(f"  Passed:                {passed_tests} ({passed_tests/total_tests*100:.1f}%)")
            report_lines.append(f"  Failed:                {total_tests - passed_tests}")
            report_lines.append("")

        # Metric scores (if available)
        report_lines.append("METRICS SUMMARY")
        report_lines.append("-" * 80)

        # Try to extract metric scores
        if hasattr(results, "metrics_data"):
            for metric_name, metric_data in results.metrics_data.items():
                score = metric_data.get("score", "N/A")
                threshold = metric_data.get("threshold", "N/A")
                status = "✓" if metric_data.get("passed", False) else "✗"
                report_lines.append(f"  {metric_name:30s}: {score:.3f} (threshold: {threshold}) {status}")
        else:
            report_lines.append("  (Detailed metric breakdown not available)")

        report_lines.append("")
        report_lines.append("=" * 80)

        return "\n".join(report_lines)

    def save_deepeval_report(
        self,
        results: Any,
        filename: Optional[str] = None,
    ) -> Path:
        """Save DeepEval evaluation results as text report.

        Args:
            results: DeepEval evaluation results
            filename: Optional output filename

        Returns:
            Path to saved report
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"deepeval_report_{timestamp}.txt"

        report_path = self.output_dir / filename
        report_text = self.generate_deepeval_report(results)

        with open(report_path, "w") as f:
            f.write(report_text)

        return report_path

    def save_deepeval_json(
        self,
        results: Any,
        filename: Optional[str] = None,
    ) -> Path:
        """Save DeepEval results as JSON.

        Args:
            results: DeepEval evaluation results
            filename: Optional output filename

        Returns:
            Path to saved JSON file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"deepeval_results_{timestamp}.json"

        json_path = self.output_dir / filename

        # Try to serialize results
        try:
            if hasattr(results, "to_dict"):
                results_dict = results.to_dict()
            elif hasattr(results, "model_dump"):
                results_dict = results.model_dump()
            elif hasattr(results, "__dict__"):
                results_dict = results.__dict__
            else:
                results_dict = {"results": str(results)}
        except Exception:
            results_dict = {"results": str(results)}

        with open(json_path, "w") as f:
            json.dump(results_dict, f, indent=2, default=str)

        return json_path
