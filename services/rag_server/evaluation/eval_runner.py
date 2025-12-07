import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.dataset_loader import load_default_dataset
from evaluation.data_models import EvaluationSample
import requests
import os
import json


def query_rag_server(question: str, session_id: str) -> dict:
    """Call the RAG server /query endpoint"""
    rag_server_url = os.getenv("RAG_SERVER_URL", "http://localhost:8001")

    response = requests.post(
        f"{rag_server_url}/query",
        json={"query": question, "session_id": session_id},
        timeout=60
    )
    response.raise_for_status()
    return response.json()


def create_evaluation_samples_from_rag(limit: int | None = None) -> list[EvaluationSample]:
    """Query the RAG server and create evaluation samples from real responses"""
    golden_qa = load_default_dataset()

    if limit:
        golden_qa = golden_qa[:limit]

    samples = []
    session_id = "eval_session"

    for idx, qa in enumerate(golden_qa):
        print(f"Querying RAG server ({idx+1}/{len(golden_qa)}): {qa.question[:60]}...")

        try:
            result = query_rag_server(qa.question, session_id)

            # Extract full_text from sources for retrieval_context
            retrieval_context = [
                source['full_text']
                for source in result.get('sources', [])
            ]

            sample = EvaluationSample(
                input=qa.question,
                retrieval_context=retrieval_context,
                actual_output=result['answer'],
                expected_output=qa.answer,
            )
            samples.append(sample)

        except Exception as e:
            print(f"  ⚠ Error querying RAG server: {e}")
            continue

    return samples


def run_evaluation():
    """Run end-to-end RAG evaluation using real queries"""
    print("=" * 80)
    print("RAG Evaluation Runner (Phase 1 - Data Collection)")
    print("=" * 80)
    print()

    print("Loading golden Q&A dataset...")
    golden_qa = load_default_dataset()
    print(f"Loaded {len(golden_qa)} Q&A pairs\n")

    print("Querying RAG server to collect evaluation samples...")
    print("(This will make real queries to the RAG system)\n")

    samples = create_evaluation_samples_from_rag(limit=3)  # Start with 3 for testing

    if not samples:
        print("\n❌ No samples collected. Ensure RAG server is running.")
        sys.exit(1)

    print(f"\n✓ Collected {len(samples)} evaluation samples")

    # Save samples for inspection
    output_dir = Path(__file__).parent.parent / "eval_data"
    output_dir.mkdir(parents=True, exist_ok=True)

    samples_path = output_dir / "evaluation_samples.json"
    with open(samples_path, "w") as f:
        json.dump([s.model_dump() for s in samples], f, indent=2)

    print(f"✓ Samples saved to: {samples_path}")
    print()
    print("Phase 1 complete. Samples ready for DeepEval evaluation.")
    print("=" * 80)


if __name__ == "__main__":
    run_evaluation()
