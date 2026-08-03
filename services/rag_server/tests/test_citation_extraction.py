"""Citation extraction and source-shaping tests for pipelines.inference.

Moved here from services/evals/tests/test_rag_eval.py (docs/suggestions.md #4.8):
they exercise rag-server code, so they could never import in the evals service.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.inference import extract_numeric_citations, extract_sources


# =============================================================================
# CITATION EXTRACTION TESTS
# =============================================================================


class TestCitationExtraction:
    """Tests for extracting numeric citations from LLM answers."""

    def test_extract_single_citation(self):
        """Single bracket citation should be extracted."""
        sources = [
            {"document_id": "doc1", "chunk_id": "chunk1"},
            {"document_id": "doc2", "chunk_id": "chunk2"},
        ]

        citations = extract_numeric_citations("The answer is Paris [1].", sources)

        assert len(citations) == 1
        assert citations[0]["source_index"] == 1
        assert citations[0]["document_id"] == "doc1"
        assert citations[0]["chunk_id"] == "chunk1"

    def test_extract_multiple_citations(self):
        """Multiple bracket citations should be extracted."""
        sources = [
            {"document_id": "doc1", "chunk_id": "chunk1"},
            {"document_id": "doc2", "chunk_id": "chunk2"},
            {"document_id": "doc3", "chunk_id": "chunk3"},
        ]

        citations = extract_numeric_citations("According to [1] and [2], also [3].", sources)

        assert len(citations) == 3
        assert [c["source_index"] for c in citations] == [1, 2, 3]

    def test_extract_comma_separated_citations(self):
        """Comma-separated citations like [1,2] should be expanded."""
        sources = [
            {"document_id": "doc1", "chunk_id": "chunk1"},
            {"document_id": "doc2", "chunk_id": "chunk2"},
            {"document_id": "doc3", "chunk_id": "chunk3"},
        ]

        citations = extract_numeric_citations("See sources [1, 2, 3].", sources)

        assert len(citations) == 3
        assert [c["source_index"] for c in citations] == [1, 2, 3]

    def test_extract_range_citations(self):
        """Range citations like [1-3] should be expanded."""
        sources = [
            {"document_id": "doc1", "chunk_id": "chunk1"},
            {"document_id": "doc2", "chunk_id": "chunk2"},
            {"document_id": "doc3", "chunk_id": "chunk3"},
        ]

        citations = extract_numeric_citations("Sources [1-3] agree.", sources)

        assert len(citations) == 3
        assert [c["source_index"] for c in citations] == [1, 2, 3]

    def test_dedupe_citations(self):
        """Duplicate citations should be deduplicated."""
        sources = [
            {"document_id": "doc1", "chunk_id": "chunk1"},
        ]

        citations = extract_numeric_citations("See [1] and again [1].", sources)

        assert len(citations) == 1
        assert citations[0]["source_index"] == 1

    def test_citation_out_of_range(self):
        """Citations beyond source count should be ignored."""
        sources = [
            {"document_id": "doc1", "chunk_id": "chunk1"},
        ]

        citations = extract_numeric_citations("See [1] and [5].", sources)

        assert len(citations) == 1
        assert citations[0]["source_index"] == 1

    def test_no_citations(self):
        """Answer without citations should return empty list."""
        sources = [
            {"document_id": "doc1", "chunk_id": "chunk1"},
        ]

        citations = extract_numeric_citations("The answer is Paris.", sources)

        assert citations == []

    def test_parenthesis_citations(self):
        """Parenthesis citations like (1) should also be extracted."""
        sources = [
            {"document_id": "doc1", "chunk_id": "chunk1"},
            {"document_id": "doc2", "chunk_id": "chunk2"},
        ]

        citations = extract_numeric_citations("According to (1) and (2).", sources)

        assert len(citations) == 2


# =============================================================================
# QUERY ENDPOINT TESTS (include_chunks)
# =============================================================================


class TestQueryEndpointIncludeChunks:
    """Tests for /query endpoint with include_chunks parameter."""

    def test_include_chunks_false_no_chunk_fields(self):
        """When include_chunks=False, chunk_id/chunk_index should not be in sources."""
        # Create mock source nodes
        node1 = MagicMock()
        node1.id_ = "node-123"
        node1.metadata = {
            "document_id": "doc1",
            "file_name": "test.pdf",
            "chunk_index": 0,
            "path": "/path/to/test.pdf",
        }
        node1.get_content.return_value = "This is the text content"
        node1.score = 0.95

        sources = extract_sources([node1], include_chunks=False)

        assert len(sources) == 1
        assert "document_id" in sources[0]
        assert "chunk_id" not in sources[0]
        assert "chunk_index" not in sources[0]

    def test_include_chunks_true_has_chunk_fields(self):
        """When include_chunks=True, chunk_id/chunk_index should be in sources."""
        # Create mock source nodes
        node1 = MagicMock()
        node1.id_ = "node-123"
        node1.metadata = {
            "document_id": "doc1",
            "file_name": "test.pdf",
            "chunk_index": 5,
            "path": "/path/to/test.pdf",
        }
        node1.get_content.return_value = "This is the text content"
        node1.score = 0.95

        sources = extract_sources([node1], include_chunks=True, dedupe_by_document=False)

        assert len(sources) == 1
        assert sources[0]["chunk_id"] == "node-123"
        assert sources[0]["chunk_index"] == 5

    def test_include_chunks_disables_deduplication(self):
        """When include_chunks=True, multiple chunks from same doc should be returned."""
        # Create mock source nodes from same document
        node1 = MagicMock()
        node1.id_ = "chunk-1"
        node1.metadata = {
            "document_id": "doc1",
            "file_name": "test.pdf",
            "chunk_index": 0,
        }
        node1.get_content.return_value = "First chunk"
        node1.score = 0.95

        node2 = MagicMock()
        node2.id_ = "chunk-2"
        node2.metadata = {
            "document_id": "doc1",  # Same document
            "file_name": "test.pdf",
            "chunk_index": 1,
        }
        node2.get_content.return_value = "Second chunk"
        node2.score = 0.90

        sources = extract_sources([node1, node2], include_chunks=True, dedupe_by_document=False)

        assert len(sources) == 2
        assert sources[0]["chunk_id"] == "chunk-1"
        assert sources[1]["chunk_id"] == "chunk-2"
