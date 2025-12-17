#!/usr/bin/env python3
"""
Simple diagnostic to test document upload and retrieval
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.rag import query_rag, get_reranker_config
from infrastructure.database.chroma import get_or_create_collection, list_documents, add_documents
from services.document import chunk_document_from_file
import uuid
import json


def upload_eval_documents():
    """Upload evaluation documents directly"""
    eval_docs_path = Path(__file__).parent.parent / "eval_data" / "documents"
    docs = list(eval_docs_path.glob("*.html"))

    print(f"\n📤 Uploading {len(docs)} documents...")

    index = get_or_create_collection()

    for doc_path in docs:
        print(f"  Processing {doc_path.name}...")

        # Chunk the document
        nodes = chunk_document_from_file(str(doc_path))
        print(f"    Created {len(nodes)} chunks")

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
        print(f"    ✓ Indexed as {doc_id}")

    print(f"\n✓ Upload complete")


def check_documents():
    """Check what documents are indexed"""
    print(f"\n📚 Checking indexed documents...")

    index = get_or_create_collection()
    docs = list_documents(index)

    print(f"  Total documents: {len(docs)}")
    total_chunks = 0
    for doc in docs:
        print(f"    - {doc['file_name']}: {doc['chunks']} chunks (id: {doc['id'][:8]}...)")
        total_chunks += doc['chunks']

    print(f"  Total chunks in index: {total_chunks}")
    return docs


def test_query(query: str):
    """Test a single query"""
    print(f"\n{'='*80}")
    print(f"🔍 Query: \"{query}\"")
    print(f"{'='*80}")

    try:
        result = query_rag(query)

        print(f"\n📝 Answer:")
        print(f"  {result['answer']}\n")

        print(f"📚 Retrieved {len(result['sources'])} source contexts:")
        for i, source in enumerate(result['sources'], 1):
            excerpt = source['excerpt'].replace('\n', ' ')
            distance = source.get('distance', 'N/A')
            print(f"\n  [{i}] {source['document_name']}")
            print(f"      Distance: {distance}")
            print(f"      Excerpt: {excerpt[:150]}...")

        return result
    except Exception as e:
        print(f"  ❌ Query failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def check_config():
    """Display current configuration"""
    print(f"\n⚙️  Current Configuration:")

    import os
    print(f"  CHROMADB_URL: {os.getenv('CHROMADB_URL', 'NOT SET')}")
    print(f"  OLLAMA_URL: {os.getenv('OLLAMA_URL', 'NOT SET')}")
    print(f"  EMBEDDING_MODEL: {os.getenv('EMBEDDING_MODEL', 'NOT SET')}")
    print(f"  LLM_MODEL: {os.getenv('LLM_MODEL', 'NOT SET')}")
    print(f"  PROMPT_STRATEGY: {os.getenv('PROMPT_STRATEGY', 'NOT SET')}")

    reranker_config = get_reranker_config()
    print(f"\n  Reranker Configuration:")
    print(f"    Enabled: {reranker_config['enabled']}")
    print(f"    Model: {reranker_config['model']}")
    print(f"    Similarity Threshold: {reranker_config['similarity_threshold']}")
    print(f"    Retrieval Top-K: {reranker_config['retrieval_top_k']}")


def main():
    print("="*80)
    print("RAG BASIC RETRIEVAL DIAGNOSTIC")
    print("="*80)

    # Show configuration
    check_config()

    # Check current state
    docs = check_documents()

    if not docs:
        print(f"\n⚠️  No documents indexed. Uploading evaluation documents...")
        upload_eval_documents()
        docs = check_documents()

        if not docs:
            print(f"\n❌ Upload failed. Exiting.")
            sys.exit(1)
    else:
        print(f"\n✓ Documents already indexed.")

    # Test sample queries from golden QA
    print(f"\n{'='*80}")
    print("TESTING SAMPLE QUERIES")
    print(f"{'='*80}")

    test_queries = [
        "What are the three qualities for great work?",
        "What is the simple trick for getting more people to read what you write?",
        "What are the four quadrants of conformism?",
        "Why is informal language better for expressing complex ideas?",
        "Where have the independent-minded traditionally protected themselves?"
    ]

    results = []
    for query in test_queries:
        result = test_query(query)
        if result:
            results.append({
                'query': query,
                'answer': result['answer'],
                'num_sources': len(result['sources'])
            })

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")

    if results:
        avg_sources = sum(r['num_sources'] for r in results) / len(results)
        zero_sources = sum(1 for r in results if r['num_sources'] == 0)

        print(f"\n  Queries tested: {len(results)}")
        print(f"  Average sources per query: {avg_sources:.1f}")
        print(f"  Queries with 0 sources: {zero_sources}/{len(results)}")

        print(f"\n  Queries with \"I don't have enough information\":")
        for r in results:
            if "don't have enough information" in r['answer'] or "don't know" in r['answer']:
                print(f"    - \"{r['query'][:60]}...\" ({r['num_sources']} sources)")

        if zero_sources > 0:
            print(f"\n  ❌ ISSUE FOUND: {zero_sources} queries returned 0 sources")
            print(f"     Possible causes:")
            print(f"     - Reranker threshold too high (current: {get_reranker_config()['similarity_threshold']})")
            print(f"     - Embedding model mismatch")
            print(f"     - Documents not properly indexed")
        elif avg_sources < 2:
            print(f"\n  ⚠️  WARNING: Low average sources ({avg_sources:.1f})")
            print(f"     Consider lowering reranker threshold or checking embedding quality")
        else:
            print(f"\n  ✓ Retrieval appears healthy")

    print(f"\n{'='*80}")
    print("DIAGNOSTIC COMPLETE")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
