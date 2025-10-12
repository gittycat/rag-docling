#!/usr/bin/env python3
"""
Diagnostic script to test RAG retrieval pipeline
Tests document upload, retrieval, and generates RAGAS evaluation
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import requests
from typing import Dict, List
from evaluation.dataset_loader import load_default_dataset
from evaluation.data_models import EvaluationSample
from evaluation.end_to_end_eval import EndToEndEvaluator
from evaluation.ragas_config import create_default_ragas_config
from evaluation.report_generator import EvaluationReportGenerator

RAG_SERVER_URL = "http://localhost:8000"  # Via web app


def upload_documents() -> Dict:
    """Upload evaluation documents to RAG server"""
    eval_docs_path = Path(__file__).parent.parent / "eval_data" / "documents"
    docs = list(eval_docs_path.glob("*.html"))

    print(f"\n📤 Uploading {len(docs)} documents...")
    for doc in docs:
        print(f"  - {doc.name}")

    files = [('files', (doc.name, open(doc, 'rb'), 'text/html')) for doc in docs]

    try:
        response = requests.post(f"{RAG_SERVER_URL}/api/upload", files=files, timeout=300)
        response.raise_for_status()
        result = response.json()

        print(f"\n✓ Upload initiated: batch_id={result['batch_id']}")
        print(f"  Tasks queued: {len(result['tasks'])}")

        return result
    except Exception as e:
        print(f"\n❌ Upload failed: {e}")
        raise
    finally:
        for _, (_, f, _) in files:
            f.close()


def wait_for_upload_completion(batch_id: str, timeout: int = 300) -> bool:
    """Poll batch status until all tasks complete"""
    import time

    print(f"\n⏳ Waiting for upload to complete...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"{RAG_SERVER_URL}/api/tasks/{batch_id}/status")
            response.raise_for_status()
            progress = response.json()

            completed = progress['completed']
            total = progress['total']

            print(f"  Progress: {completed}/{total} tasks completed", end='\r')

            if completed == total:
                print(f"\n✓ All {total} documents processed successfully")
                return True

            time.sleep(2)
        except Exception as e:
            print(f"\n❌ Error checking status: {e}")
            return False

    print(f"\n⚠ Timeout after {timeout}s")
    return False


def list_documents() -> List[Dict]:
    """List all indexed documents"""
    response = requests.get(f"{RAG_SERVER_URL}/api/documents")
    response.raise_for_status()
    docs = response.json()['documents']

    print(f"\n📚 Indexed documents: {len(docs)}")
    for doc in docs:
        print(f"  - {doc['file_name']}: {doc['chunks']} chunks")

    return docs


def test_single_query(query: str) -> Dict:
    """Test a single query and return response"""
    print(f"\n🔍 Testing query: \"{query}\"")

    response = requests.post(
        f"{RAG_SERVER_URL}/api/query",
        json={"query": query},
        timeout=60
    )
    response.raise_for_status()
    result = response.json()

    print(f"  Answer: {result['answer'][:200]}...")
    print(f"  Sources: {len(result['sources'])} nodes retrieved")

    for i, source in enumerate(result['sources'][:3], 1):
        print(f"    [{i}] {source['document_name']}: {source['excerpt'][:100]}...")

    return result


def run_ragas_evaluation() -> None:
    """Run full RAGAS evaluation on uploaded documents"""
    print(f"\n🎯 Running RAGAS evaluation...")

    golden_qa = load_default_dataset()
    print(f"  Loaded {len(golden_qa)} test questions")

    samples = []
    print(f"\n  Querying RAG system for each question...")

    for i, qa in enumerate(golden_qa, 1):
        print(f"    [{i}/{len(golden_qa)}] {qa.question[:60]}...")

        try:
            response = requests.post(
                f"{RAG_SERVER_URL}/api/query",
                json={"query": qa.question},
                timeout=60
            )
            response.raise_for_status()
            result = response.json()

            sample = EvaluationSample(
                user_input=qa.question,
                retrieved_contexts=[s['excerpt'] for s in result['sources']],
                response=result['answer'],
                reference=qa.answer
            )
            samples.append(sample)

        except Exception as e:
            print(f"\n    ❌ Query failed: {e}")
            sample = EvaluationSample(
                user_input=qa.question,
                retrieved_contexts=[],
                response=f"ERROR: {e}",
                reference=qa.answer
            )
            samples.append(sample)

    # Analyze retrieval stats before RAGAS
    print(f"\n📊 Retrieval Statistics:")
    context_counts = [len(s.retrieved_contexts) for s in samples]
    avg_contexts = sum(context_counts) / len(context_counts) if context_counts else 0
    zero_contexts = sum(1 for c in context_counts if c == 0)

    print(f"  Average contexts per query: {avg_contexts:.1f}")
    print(f"  Queries with 0 contexts: {zero_contexts}/{len(samples)}")
    print(f"  Context count range: {min(context_counts) if context_counts else 0} - {max(context_counts) if context_counts else 0}")

    if zero_contexts == len(samples):
        print(f"\n❌ CRITICAL: All queries returned 0 contexts!")
        print(f"   This indicates retrieval is completely failing.")
        print(f"   Skipping RAGAS evaluation.")
        return

    print(f"\n  Running RAGAS metrics (this may take several minutes)...")
    try:
        config = create_default_ragas_config()
        evaluator = EndToEndEvaluator(config)
        result = evaluator.evaluate(samples, include_correctness=True)

        report_gen = EvaluationReportGenerator(
            output_dir=Path(__file__).parent.parent / "eval_data"
        )

        print("\n" + "="*80)
        print(report_gen.generate_text_report(result))
        print("="*80)

        report_path = report_gen.save_report(result)
        json_path = report_gen.save_json_results(result)

        print(f"\n✓ Reports saved:")
        print(f"  Text: {report_path}")
        print(f"  JSON: {json_path}")

    except Exception as e:
        print(f"\n❌ RAGAS evaluation failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    print("="*80)
    print("RAG RETRIEVAL DIAGNOSTIC TOOL")
    print("="*80)

    # Check if documents already uploaded
    try:
        docs = list_documents()
        if docs:
            print(f"\n⚠ Documents already indexed. Skipping upload.")
            print(f"  To re-index, delete documents via API first.")
        else:
            # Upload documents
            result = upload_documents()

            # Wait for processing
            if not wait_for_upload_completion(result['batch_id']):
                print("\n❌ Upload did not complete. Exiting.")
                sys.exit(1)

            # Verify upload
            docs = list_documents()
            if not docs:
                print("\n❌ No documents indexed after upload. Check logs.")
                sys.exit(1)

    except Exception as e:
        print(f"\n❌ Error during document upload: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Test a few sample queries
    print("\n" + "="*80)
    print("TESTING SAMPLE QUERIES")
    print("="*80)

    sample_queries = [
        "What are the three qualities for great work?",
        "What is the simple trick for getting more people to read what you write?",
        "What are the four quadrants of conformism?"
    ]

    for query in sample_queries:
        try:
            test_single_query(query)
        except Exception as e:
            print(f"\n❌ Query failed: {e}")

    # Run full RAGAS evaluation
    print("\n" + "="*80)
    print("RAGAS EVALUATION")
    print("="*80)

    try:
        run_ragas_evaluation()
    except Exception as e:
        print(f"\n❌ Evaluation failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*80)
    print("DIAGNOSTIC COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
