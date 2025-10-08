import json
from datetime import datetime
from pathlib import Path
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
