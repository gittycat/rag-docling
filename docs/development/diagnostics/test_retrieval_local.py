#!/usr/bin/env python3
"""
Diagnostic script to test RAG retrieval pipeline - runs inside rag-server container
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core_logic.rag_pipeline import query_rag
from core_logic.chroma_manager import get_or_create_collection, list_documents, add_documents
from core_logic.document_processor import chunk_document_from_file
from evaluation.dataset_loader import load_default_dataset
from evaluation.data_models import EvaluationSample
from evaluation.end_to_end_eval import EndToEndEvaluator
from evaluation.ragas_config import create_default_ragas_config
from evaluation.report_generator import EvaluationReportGenerator
import uuid
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def upload_eval_documents():
    """Upload evaluation documents directly"""
    eval_docs_path = Path(__file__).parent.parent / "eval_data" / "documents"
    docs = list(eval_docs_path.glob("*.html"))

    logger.info(f"\n📤 Uploading {len(docs)} documents...")

    index = get_or_create_collection()

    for doc_path in docs:
        logger.info(f"  Processing {doc_path.name}...")

        # Chunk the document
        nodes = chunk_document_from_file(str(doc_path))
        logger.info(f"    Created {len(nodes)} chunks")

        # Add metadata
        doc_id = str(uuid.uuid4())
        for i, node in enumerate(nodes):
            node.metadata.update({
                "file_name": doc_path.name,
                "file_type": doc_path.suffix,
                "path": str(doc_path),
                "chunk_index": i,
                "document_id": doc_id
            })
            node.id_ = f"{doc_id}-chunk-{i}"

        # Add to index
        add_documents(index, nodes)
        logger.info(f"    ✓ Indexed as {doc_id}")

    logger.info(f"\n✓ Upload complete")


def check_documents():
    """Check what documents are indexed"""
    logger.info(f"\n📚 Checking indexed documents...")

    index = get_or_create_collection()
    docs = list_documents(index)

    logger.info(f"  Total documents: {len(docs)}")
    for doc in docs:
        logger.info(f"    - {doc['file_name']}: {doc['chunks']} chunks (id: {doc['id'][:8]}...)")

    return docs


def test_query(query: str):
    """Test a single query"""
    logger.info(f"\n🔍 Query: \"{query}\"")

    try:
        result = query_rag(query)

        logger.info(f"  Answer: {result['answer'][:200]}...")
        logger.info(f"  Sources: {len(result['sources'])} contexts")

        for i, source in enumerate(result['sources'][:3], 1):
            excerpt = source['excerpt'][:100].replace('\n', ' ')
            logger.info(f"    [{i}] {source['document_name']}: {excerpt}...")

        return result
    except Exception as e:
        logger.error(f"  ❌ Query failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def run_ragas_evaluation():
    """Run RAGAS evaluation"""
    logger.info(f"\n🎯 Running RAGAS evaluation...")

    golden_qa = load_default_dataset()
    logger.info(f"  Loaded {len(golden_qa)} test questions\n")

    samples = []

    for i, qa in enumerate(golden_qa, 1):
        logger.info(f"  [{i}/{len(golden_qa)}] {qa.question[:70]}...")

        try:
            result = query_rag(qa.question)

            sample = EvaluationSample(
                user_input=qa.question,
                retrieved_contexts=[s['excerpt'] for s in result['sources']],
                response=result['answer'],
                reference=qa.answer
            )
            samples.append(sample)

            logger.info(f"       → Retrieved {len(result['sources'])} contexts")

        except Exception as e:
            logger.error(f"       ❌ Failed: {e}")
            samples.append(EvaluationSample(
                user_input=qa.question,
                retrieved_contexts=[],
                response=f"ERROR: {e}",
                reference=qa.answer
            ))

    # Analyze retrieval stats
    logger.info(f"\n📊 Retrieval Statistics:")
    context_counts = [len(s.retrieved_contexts) for s in samples]
    avg_contexts = sum(context_counts) / len(context_counts) if context_counts else 0
    zero_contexts = sum(1 for c in context_counts if c == 0)

    logger.info(f"  Average contexts per query: {avg_contexts:.1f}")
    logger.info(f"  Queries with 0 contexts: {zero_contexts}/{len(samples)}")
    logger.info(f"  Context count range: {min(context_counts) if context_counts else 0} - {max(context_counts) if context_counts else 0}")

    if zero_contexts == len(samples):
        logger.error(f"\n❌ CRITICAL: All queries returned 0 contexts!")
        logger.error(f"   Retrieval is completely failing. Skipping RAGAS.")
        return

    # Run RAGAS
    logger.info(f"\n  Running RAGAS metrics (may take several minutes)...")
    try:
        config = create_default_ragas_config()
        evaluator = EndToEndEvaluator(config)
        result = evaluator.evaluate(samples, include_correctness=True)

        report_gen = EvaluationReportGenerator(
            output_dir=Path(__file__).parent.parent / "eval_data"
        )

        logger.info("\n" + "="*80)
        logger.info(report_gen.generate_text_report(result))
        logger.info("="*80)

        report_path = report_gen.save_report(result)
        json_path = report_gen.save_json_results(result)

        logger.info(f"\n✓ Reports saved:")
        logger.info(f"  Text: {report_path}")
        logger.info(f"  JSON: {json_path}")

    except Exception as e:
        logger.error(f"\n❌ RAGAS evaluation failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    logger.info("="*80)
    logger.info("RAG RETRIEVAL DIAGNOSTIC TOOL (LOCAL)")
    logger.info("="*80)

    # Check current state
    docs = check_documents()

    if not docs:
        logger.info(f"\n⚠ No documents indexed. Uploading evaluation documents...")
        upload_eval_documents()
        docs = check_documents()

        if not docs:
            logger.error(f"\n❌ Upload failed. Exiting.")
            sys.exit(1)

    # Test sample queries
    logger.info(f"\n" + "="*80)
    logger.info("TESTING SAMPLE QUERIES")
    logger.info("="*80)

    sample_queries = [
        "What are the three qualities for great work?",
        "What is the simple trick for getting more people to read what you write?",
        "What are the four quadrants of conformism?"
    ]

    for query in sample_queries:
        test_query(query)

    # Run RAGAS
    logger.info(f"\n" + "="*80)
    logger.info("RAGAS EVALUATION")
    logger.info("="*80)

    run_ragas_evaluation()

    logger.info(f"\n" + "="*80)
    logger.info("DIAGNOSTIC COMPLETE")
    logger.info("="*80)


if __name__ == "__main__":
    main()
