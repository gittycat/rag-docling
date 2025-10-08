import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.dataset_loader import load_default_dataset
from evaluation.data_models import EvaluationSample
from evaluation.end_to_end_eval import EndToEndEvaluator
from evaluation.ragas_config import create_default_ragas_config
from evaluation.report_generator import EvaluationReportGenerator
from pathlib import Path
import json


def create_mock_samples_from_golden_qa() -> list[EvaluationSample]:
    golden_qa = load_default_dataset()

    samples = []
    for qa in golden_qa[:3]:
        sample = EvaluationSample(
            user_input=qa.question,
            retrieved_contexts=[
                f"Mock context for {qa.question}. {qa.context_hint or ''}",
                "Additional mock context that might be less relevant.",
            ],
            response=f"Mock response: {qa.answer[:50]}...",
            reference=qa.answer,
        )
        samples.append(sample)

    return samples


def run_evaluation():
    print("Loading golden Q&A dataset...")
    golden_qa = load_default_dataset()
    print(f"Loaded {len(golden_qa)} Q&A pairs\n")

    print("Creating mock evaluation samples...")
    samples = create_mock_samples_from_golden_qa()
    print(f"Created {len(samples)} samples\n")

    print("Initializing evaluator with Ollama configuration...")
    config = create_default_ragas_config()
    evaluator = EndToEndEvaluator(config)

    print("Running evaluation (this may take several minutes)...")
    try:
        result = evaluator.evaluate(samples, include_correctness=True)

        report_gen = EvaluationReportGenerator(
            output_dir=Path(__file__).parent.parent / "eval_data"
        )

        print("\n" + report_gen.generate_text_report(result))

        report_path = report_gen.save_report(result)
        json_path = report_gen.save_json_results(result)

        print(f"\nText report saved to: {report_path}")
        print(f"JSON results saved to: {json_path}")

    except Exception as e:
        print(f"\n❌ Evaluation failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_evaluation()
