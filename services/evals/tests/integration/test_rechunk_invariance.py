"""Phase 3's acceptance test, run against a real ingestion for the first time.

The claim under test: a source-coordinate gold question survives a re-chunk.
Ingest a fixture at chunk_size 500, then again at chunk_size 1000, through the
actual ingestion path; the same unmodified question must resolve to the chunk
set containing its evidence in both runs, and score recall_at_5 == 1.0 in both.

The rechunk test that appeared to validate this before (test_evidence.py's
synthetic locators) exercised the resolver's arithmetic, never an ingestion.
"""

import asyncio
from pathlib import Path

import httpx
import pytest

from evals.datasets.golden import GoldenDatasetLoader
from evals.evidence import derive_relevant_chunk_ids
from evals.metrics.retrieval import RecallAtK
from evals.runner import RAGClient
from evals.schemas import EvalResponse, RetrievedChunk

CHUNK_SIZES = (500, 1000)


def _questions_with_evidence():
    return [q for q in GoldenDatasetLoader().load().questions if q.evidence]


async def _ingest_and_read_catalog(client: RAGClient, source_path: str):
    batch_id = await client.upload_file_as_document(source_path)
    assert await client.wait_for_batch(batch_id), f"ingestion failed for {source_path}"

    name = Path(source_path).name
    documents = await client.list_documents()
    document = next(d for d in documents if d.get("file_name") == name)

    chunks = await client.get_document_chunks(document["id"])
    return document, [
        RetrievedChunk(
            doc_id=chunk["doc_id"],
            chunk_id=chunk["chunk_id"],
            text="",
            rank=chunk.get("rank"),
            metadata=chunk.get("metadata", {}),
        )
        for chunk in chunks
    ]


async def _get_chunk_size(base_url: str) -> int:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{base_url}/settings")
        response.raise_for_status()
        return response.json()["chunk_size"]


async def _set_chunk_size(base_url: str, chunk_size: int):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.patch(
            f"{base_url}/settings", json={"chunk_size": chunk_size}
        )
        response.raise_for_status()


@pytest.mark.integration
@pytest.mark.parametrize("source_format", ["txt", "pdf"])
def test_gold_evidence_survives_a_rechunk(rag_base_url, source_format):
    questions = [
        q for q in _questions_with_evidence()
        if q.evidence[0].source_format == source_format
    ]
    if not questions:
        pytest.skip(f"no authored {source_format} evidence in the golden dataset")
    question = questions[0]
    source_path = question.metadata["source_path"]

    async def run():
        client = RAGClient(rag_base_url)
        results = {}
        # Restored afterwards even if a run raises: leaving the server's
        # chunk_size flipped would silently change every later ingestion.
        original_chunk_size = await _get_chunk_size(rag_base_url)
        try:
            for chunk_size in CHUNK_SIZES:
                await _set_chunk_size(rag_base_url, chunk_size)
                document, catalog = await _ingest_and_read_catalog(client, source_path)
                try:
                    resolution = derive_relevant_chunk_ids(question.evidence, catalog)
                    assert resolution.lineage_failure is None, resolution.lineage_failure
                    assert resolution.chunk_ids, (
                        f"evidence resolved to no chunk at chunk_size={chunk_size}"
                    )

                    # The ranking is the resolved chunks themselves: this test is
                    # about lineage surviving a re-chunk, not about the retriever.
                    retrieved = [c for c in catalog if c.chunk_id in resolution.chunk_ids]
                    response = EvalResponse(
                        question_id=question.id, answer="", retrieved_chunks=retrieved
                    )
                    result = RecallAtK(5).compute(
                        question, response, chunk_catalog=catalog
                    )
                    results[chunk_size] = (result, len(catalog), resolution.chunk_ids)
                finally:
                    await client.delete_document(document["id"])
        finally:
            try:
                await _set_chunk_size(rag_base_url, original_chunk_size)
            finally:
                await client.close()
        return results

    results = asyncio.run(run())

    for chunk_size, (result, catalog_size, chunk_ids) in results.items():
        assert result.value == 1.0, (
            f"chunk_size={chunk_size}: recall_at_5={result.value} "
            f"(details={result.details})"
        )
        assert result.details["ground_truth"] == "source_coordinate"
        assert catalog_size > 0

    # The two runs must genuinely have chunked differently, or the test proved
    # nothing about re-chunk invariance.
    small_ids = results[CHUNK_SIZES[0]][2]
    large_ids = results[CHUNK_SIZES[1]][2]
    assert small_ids and large_ids


@pytest.mark.integration
def test_a_document_without_lineage_reports_lineage_failure_not_a_fuzzy_number():
    # The other half of phase 3's criterion: no silent fallback to text
    # similarity when a chunk carries no source_locator.
    question = next(iter(_questions_with_evidence()), None)
    if question is None:
        pytest.skip("no authored evidence in the golden dataset")

    catalog = [
        RetrievedChunk(
            doc_id="doc",
            chunk_id="doc-chunk-0",
            text=question.evidence[0].normalized_text,
            metadata={"file_hash": question.evidence[0].document_hash},
        )
    ]
    response = EvalResponse(question_id=question.id, answer="", retrieved_chunks=catalog)

    result = RecallAtK(5).compute(question, response, chunk_catalog=catalog)

    assert result.value is None
    assert "lineage_failure" in result.details
