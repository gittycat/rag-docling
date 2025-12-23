"""
Integration tests for hybrid search (BM25 + Vector + RRF).

Tests the retrieval system combining sparse and dense search.

Run with: pytest tests/integration/test_hybrid_search.py -v --run-integration
Requires: docker compose up -d
"""
import pytest
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.integration
class TestBM25RefreshAfterUpload:
    """
    Test BM25 index synchronization after document operations.

    Critical for hybrid search correctness - BM25 must reflect current index state.
    """

    def test_bm25_refresh_after_upload(
        self,
        integration_env,
        check_services,
        sample_text_file,
    ):
        """
        Upload new doc -> BM25 index includes new content.

        This is a critical test that catches index desync bugs where
        BM25 returns stale results after new documents are added.
        """
        from pipelines.ingestion import chunk_document_from_file
        from infrastructure.database.chroma import (
            get_or_create_collection,
            add_documents,
            delete_document,
        )
        from pipelines.inference import (
            create_hybrid_retriever,
            refresh_bm25_retriever,
            get_bm25_retriever,
            initialize_bm25_retriever,
        )

        # Create document with unique identifier for this test
        unique_id = f"BM25TEST_{uuid.uuid4().hex[:8]}"
        content = f"""
        BM25 Refresh Test Document

        This document contains a unique identifier: {unique_id}

        The identifier should be findable via BM25 keyword search
        after the document is uploaded and BM25 is refreshed.

        Additional keywords: retrieval, sparse, keyword, matching
        """

        # Write to temp file
        test_file = sample_text_file.parent / f"bm25_test_{unique_id}.txt"
        test_file.write_text(content)

        try:
            # Process and store document
            nodes = chunk_document_from_file(str(test_file))
            doc_id = str(uuid.uuid4())

            for i, node in enumerate(nodes):
                node.metadata["document_id"] = doc_id
                node.metadata["file_name"] = test_file.name
                node.id_ = f"{doc_id}-chunk-{i}"

            index = get_or_create_collection()
            add_documents(index, nodes)

            # Refresh BM25 after adding documents (this is what tasks.py does)
            refresh_bm25_retriever(index)

            # Verify BM25 retriever is initialized
            bm25_retriever = get_bm25_retriever()
            assert bm25_retriever is not None, "BM25 retriever should be initialized after refresh"

            # Create hybrid retriever and search for unique ID
            hybrid_retriever = create_hybrid_retriever(index, similarity_top_k=10)
            assert hybrid_retriever is not None, "Hybrid retriever should be created"

            # Search for unique identifier - BM25 should find exact keyword match
            results = hybrid_retriever.retrieve(unique_id)

            # Verify results contain our document
            found_unique_id = False
            for node in results:
                if unique_id in node.get_content():
                    found_unique_id = True
                    break

            assert found_unique_id, \
                f"BM25 should find document with unique ID '{unique_id}' after refresh"

        finally:
            # Cleanup
            try:
                delete_document(index, doc_id)
                refresh_bm25_retriever(index)  # Refresh again after delete
            except Exception:
                pass

    def test_bm25_refresh_after_delete(
        self,
        integration_env,
        check_services,
        sample_text_file,
    ):
        """
        Delete doc -> BM25 no longer returns deleted content.

        Tests that stale data is properly removed from BM25 index.
        """
        from pipelines.ingestion import chunk_document_from_file
        from infrastructure.database.chroma import (
            get_or_create_collection,
            add_documents,
            delete_document,
        )
        from pipelines.inference import (
            create_hybrid_retriever,
            refresh_bm25_retriever,
        )

        # Create document with unique identifier
        unique_id = f"DELETEME_{uuid.uuid4().hex[:8]}"
        content = f"""
        Document to be deleted: {unique_id}

        This content should NOT appear in search results after deletion.
        """

        test_file = sample_text_file.parent / f"delete_test_{unique_id}.txt"
        test_file.write_text(content)

        try:
            # Store document
            nodes = chunk_document_from_file(str(test_file))
            doc_id = str(uuid.uuid4())

            for i, node in enumerate(nodes):
                node.metadata["document_id"] = doc_id
                node.id_ = f"{doc_id}-chunk-{i}"

            index = get_or_create_collection()
            add_documents(index, nodes)
            refresh_bm25_retriever(index)

            # Verify it's findable before deletion
            hybrid_retriever = create_hybrid_retriever(index, similarity_top_k=10)
            results_before = hybrid_retriever.retrieve(unique_id)

            found_before = any(unique_id in node.get_content() for node in results_before)
            assert found_before, "Document should be findable before deletion"

            # Delete document
            delete_document(index, doc_id)
            refresh_bm25_retriever(index)

            # Search again - should NOT find deleted content
            hybrid_retriever = create_hybrid_retriever(index, similarity_top_k=10)
            results_after = hybrid_retriever.retrieve(unique_id)

            found_after = any(unique_id in node.get_content() for node in results_after)
            assert not found_after, \
                f"Deleted document with ID '{unique_id}' should NOT appear in BM25 results"

        finally:
            # Cleanup (may already be deleted)
            try:
                delete_document(index, doc_id)
            except Exception:
                pass

    def test_hybrid_fallback_on_empty_index(
        self,
        integration_env,
        check_services,
    ):
        """
        If BM25 init fails (empty index), system should fallback to vector-only.

        Tests graceful degradation when hybrid search isn't possible.
        """
        from pipelines.inference import (
            get_hybrid_retriever_config,
            initialize_bm25_retriever,
        )
        from infrastructure.database.chroma import get_or_create_collection
        from unittest.mock import patch, MagicMock

        config = get_hybrid_retriever_config()
        assert config['enabled'], "Hybrid search should be enabled for this test"

        # Create a mock index with no nodes
        mock_index = MagicMock()
        with patch('pipelines.inference.get_all_nodes', return_value=[]):
            result = initialize_bm25_retriever(mock_index, similarity_top_k=10)

        # Should return None when no nodes available
        assert result is None, "BM25 should return None when index is empty"


@pytest.mark.integration
class TestHybridSearchBehavior:
    """Test hybrid search combines BM25 and vector search correctly."""

    def test_exact_keyword_found_by_bm25(
        self,
        integration_env,
        check_services,
        tmp_path,
    ):
        """
        BM25 finds exact acronym that pure vector search might rank lower.

        BM25 excels at: exact keywords, IDs, names, abbreviations.
        """
        from pipelines.ingestion import chunk_document_from_file
        from infrastructure.database.chroma import (
            get_or_create_collection,
            add_documents,
            delete_document,
            query_documents,
        )
        from pipelines.inference import (
            create_hybrid_retriever,
            refresh_bm25_retriever,
        )

        # Create document with technical acronym
        unique_acronym = "XQ7B9-PROTO"
        content = f"""
        Technical Specification Document

        Protocol identifier: {unique_acronym}

        This protocol handles network communication between services.
        The {unique_acronym} specification defines message formats.
        """

        test_file = tmp_path / "acronym_test.txt"
        test_file.write_text(content)

        try:
            nodes = chunk_document_from_file(str(test_file))
            doc_id = str(uuid.uuid4())

            for i, node in enumerate(nodes):
                node.metadata["document_id"] = doc_id
                node.id_ = f"{doc_id}-chunk-{i}"

            index = get_or_create_collection()
            add_documents(index, nodes)
            refresh_bm25_retriever(index)

            # Test hybrid retrieval
            hybrid_retriever = create_hybrid_retriever(index, similarity_top_k=10)
            results = hybrid_retriever.retrieve(unique_acronym)

            # Exact acronym should be in top results
            assert len(results) > 0, "Should return results"

            top_result_content = results[0].get_content()
            assert unique_acronym in top_result_content, \
                f"Top result should contain exact acronym '{unique_acronym}'"

        finally:
            try:
                delete_document(index, doc_id)
            except Exception:
                pass

    def test_rrf_combines_both_retrievers(
        self,
        integration_env,
        check_services,
        tmp_path,
    ):
        """
        Verify RRF fusion uses results from both BM25 and vector search.

        Creates two documents: one optimized for keyword match, one for semantic.
        """
        from pipelines.ingestion import chunk_document_from_file
        from infrastructure.database.chroma import (
            get_or_create_collection,
            add_documents,
            delete_document,
        )
        from pipelines.inference import (
            create_hybrid_retriever,
            refresh_bm25_retriever,
        )

        # Document 1: Keyword-rich
        keyword_content = """
        OAuth2 Authentication Protocol RFC6749

        OAuth2 defines authorization framework. OAuth2 tokens.
        OAuth2 flows include authorization code grant.
        OAuth2 client credentials. OAuth2 refresh tokens.
        """

        # Document 2: Semantically related but different keywords
        semantic_content = """
        User Authentication and Authorization Guide

        This guide explains how to verify user identity and grant access.
        Authentication confirms who you are. Authorization determines what you can do.
        Modern systems use token-based approaches for stateless verification.
        """

        keyword_file = tmp_path / "keyword_doc.txt"
        keyword_file.write_text(keyword_content)

        semantic_file = tmp_path / "semantic_doc.txt"
        semantic_file.write_text(semantic_content)

        doc_ids = []

        try:
            index = get_or_create_collection()

            # Store both documents
            for test_file in [keyword_file, semantic_file]:
                nodes = chunk_document_from_file(str(test_file))
                doc_id = str(uuid.uuid4())
                doc_ids.append(doc_id)

                for i, node in enumerate(nodes):
                    node.metadata["document_id"] = doc_id
                    node.metadata["file_name"] = test_file.name
                    node.id_ = f"{doc_id}-chunk-{i}"

                add_documents(index, nodes)

            refresh_bm25_retriever(index)

            # Query with exact keyword
            hybrid_retriever = create_hybrid_retriever(index, similarity_top_k=10)
            results = hybrid_retriever.retrieve("OAuth2 authentication")

            # Should return results from both documents
            # BM25 should favor keyword doc, vector should find semantic doc
            assert len(results) >= 2, "Should return results from hybrid search"

            # Verify we got content from keyword doc (BM25 strength)
            all_content = " ".join(node.get_content() for node in results)
            assert "OAuth2" in all_content, "Should include keyword-matched content"

        finally:
            for doc_id in doc_ids:
                try:
                    delete_document(index, doc_id)
                except Exception:
                    pass
