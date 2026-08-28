"""Chunk lineage is extracted before ingestion drops structured metadata."""

from pathlib import Path

from pipelines.ingestion import SOURCE_LOCATOR_METADATA_KEY, chunk_document_with_text_splitter


def test_text_splitter_attaches_source_coordinates(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("First paragraph.\n\nSecond paragraph with the evidence.")

    nodes = chunk_document_with_text_splitter(
        str(path), chunk_size=64, chunk_overlap=0, document_hash="f" * 64
    )

    assert nodes
    locator = nodes[0].metadata[SOURCE_LOCATOR_METADATA_KEY]
    assert locator["document_hash"] == "f" * 64
    assert locator["source_format"] == "txt"
    assert locator["locator"]["element_path"] == "document"
    assert locator["locator"]["end_char"] > locator["locator"]["start_char"]
