"""
Integration tests for the document processing pipeline.

Tests the full flow: Upload -> Docling parse -> Chunk -> Embed -> Store -> Retrieve

Run with: pytest tests/integration/test_document_pipeline.py -v --run-integration
Requires: docker compose up -d
"""
import pytest
import os
import sys
import uuid
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.integration
class TestPDFFullPipeline:
    """
    Test complete document processing pipeline with real PDF.

    Validates:
    - DoclingReader correctly parses PDF
    - DoclingNodeParser creates nodes
    - Embeddings are generated via Ollama
    - Nodes are stored in ChromaDB
    - Content is retrievable via query
    """

    def test_pdf_full_pipeline(
        self,
        integration_env,
        check_services,
        sample_pdf,
        clean_test_collection,
    ):
        """
        Upload real PDF -> Docling parses -> nodes created -> ChromaDB stores -> queryable

        This is the most critical integration test. It validates the entire
        document processing pipeline works end-to-end without mocking.
        """
        # Import after env is set
        from core_logic.document_processor import chunk_document_from_file
        from core_logic.chroma_manager import (
            get_or_create_collection,
            add_documents,
            query_documents,
            delete_document,
            list_documents,
        )

        # Step 1: Process PDF through Docling
        nodes = chunk_document_from_file(str(sample_pdf))

        # Verify nodes were created
        assert len(nodes) > 0, "Docling should create at least one node from PDF"

        # Verify nodes have content
        for node in nodes:
            assert node.get_content(), "Each node should have text content"
            assert isinstance(node.metadata, dict), "Node should have metadata dict"

        # Step 2: Add unique document_id to nodes
        doc_id = str(uuid.uuid4())
        for i, node in enumerate(nodes):
            node.metadata["document_id"] = doc_id
            node.metadata["file_name"] = sample_pdf.name
            node.id_ = f"{doc_id}-chunk-{i}"

        # Step 3: Store in ChromaDB (generates embeddings via Ollama)
        index = get_or_create_collection()
        add_documents(index, nodes)

        # Step 4: Verify documents are listed
        docs = list_documents(index)
        doc_ids = [d["id"] for d in docs]
        assert doc_id in doc_ids, "Document should appear in list after indexing"

        # Step 5: Query for known content
        results = query_documents(index, "ChromaDB vector database", n_results=5)

        assert results["documents"], "Query should return documents"
        assert len(results["documents"][0]) > 0, "Should have at least one result"

        # Verify retrieval contains expected content
        all_content = " ".join(results["documents"][0])
        assert "ChromaDB" in all_content or "vector" in all_content, \
            "Retrieved content should contain query-related terms"

        # Step 6: Query for unique identifier
        results = query_documents(index, "TESTID_XYZ789", n_results=3)
        all_content = " ".join(results["documents"][0])
        assert "TESTID_XYZ789" in all_content, \
            "Should retrieve exact identifier via keyword search"

        # Cleanup: Delete test document
        delete_document(index, doc_id)

        # Verify deletion
        docs_after = list_documents(index)
        doc_ids_after = [d["id"] for d in docs_after]
        assert doc_id not in doc_ids_after, "Document should be removed after deletion"

    def test_text_file_pipeline(
        self,
        integration_env,
        check_services,
        sample_text_file,
    ):
        """
        Test text files use SimpleDirectoryReader path (not Docling).

        This verifies the fallback path for .txt/.md files works correctly.
        """
        from core_logic.document_processor import chunk_document_from_file
        from core_logic.chroma_manager import (
            get_or_create_collection,
            add_documents,
            query_documents,
            delete_document,
        )

        # Process text file (uses SimpleDirectoryReader)
        nodes = chunk_document_from_file(str(sample_text_file))

        assert len(nodes) > 0, "Should create nodes from text file"

        # Verify unique content is present
        all_text = " ".join(node.get_content() for node in nodes)
        assert "UNIQUE_TEXT_12345" in all_text, "Unique identifier should be in nodes"

        # Store and retrieve
        doc_id = str(uuid.uuid4())
        for i, node in enumerate(nodes):
            node.metadata["document_id"] = doc_id
            node.id_ = f"{doc_id}-chunk-{i}"

        index = get_or_create_collection()
        add_documents(index, nodes)

        # Query for unique identifier
        results = query_documents(index, "UNIQUE_TEXT_12345", n_results=3)
        all_content = " ".join(results["documents"][0])
        assert "UNIQUE_TEXT_12345" in all_content, "Should retrieve unique identifier"

        # Cleanup
        delete_document(index, doc_id)

    def test_metadata_preserved_through_pipeline(
        self,
        integration_env,
        check_services,
        sample_text_file,
    ):
        """
        Verify metadata is correctly preserved through the pipeline.

        ChromaDB only supports flat types (str, int, float, bool, None).
        This tests the metadata cleaning works correctly.
        """
        from core_logic.document_processor import (
            chunk_document_from_file,
            extract_metadata,
        )
        from core_logic.chroma_manager import (
            get_or_create_collection,
            add_documents,
            list_documents,
            delete_document,
        )

        nodes = chunk_document_from_file(str(sample_text_file))
        metadata = extract_metadata(str(sample_text_file))

        doc_id = str(uuid.uuid4())
        for i, node in enumerate(nodes):
            node.metadata.update(metadata)
            node.metadata["document_id"] = doc_id
            node.metadata["chunk_index"] = i
            node.id_ = f"{doc_id}-chunk-{i}"

        index = get_or_create_collection()
        add_documents(index, nodes)

        # Verify metadata in listing
        docs = list_documents(index)
        test_doc = next((d for d in docs if d["id"] == doc_id), None)

        assert test_doc is not None, "Document should be listed"
        assert test_doc["file_name"] == sample_text_file.name
        assert test_doc["chunks"] == len(nodes)

        # Cleanup
        delete_document(index, doc_id)

    def test_large_document_chunking(
        self,
        integration_env,
        check_services,
        large_text_file,
    ):
        """
        Test chunking behavior with large documents.

        Verifies:
        - Document is split into multiple chunks
        - All chunks have reasonable size
        - Content is distributed across chunks
        """
        from core_logic.document_processor import chunk_document_from_file
        from core_logic.chroma_manager import (
            get_or_create_collection,
            add_documents,
            delete_document,
        )

        nodes = chunk_document_from_file(str(large_text_file))

        # Should have multiple chunks for large document
        assert len(nodes) > 5, f"Large document should produce many chunks, got {len(nodes)}"

        # Verify chunk sizes are reasonable (not too large)
        for node in nodes:
            content = node.get_content()
            # Chunks should be under typical context window limits
            assert len(content) < 10000, f"Chunk too large: {len(content)} chars"

        # Verify we can store and retrieve
        doc_id = str(uuid.uuid4())
        for i, node in enumerate(nodes):
            node.metadata["document_id"] = doc_id
            node.id_ = f"{doc_id}-chunk-{i}"

        index = get_or_create_collection()
        add_documents(index, nodes)

        # Cleanup
        delete_document(index, doc_id)


@pytest.mark.integration
class TestUnsupportedFormats:
    """Test handling of unsupported file formats."""

    def test_unsupported_format_rejected(self, integration_env, tmp_path):
        """Unsupported file types should raise clear error."""
        from core_logic.document_processor import chunk_document_from_file

        # Create fake executable file
        exe_path = tmp_path / "program.exe"
        exe_path.write_bytes(b"MZ\x00\x00")  # PE header start

        with pytest.raises(ValueError, match="Unsupported file type"):
            chunk_document_from_file(str(exe_path))

    def test_missing_file_error(self, integration_env):
        """Non-existent file should raise clear error."""
        from core_logic.document_processor import chunk_document_from_file

        with pytest.raises((FileNotFoundError, ValueError, Exception)):
            chunk_document_from_file("/nonexistent/path/file.pdf")
