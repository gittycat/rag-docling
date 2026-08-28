"""Resolve source-coordinate gold evidence against the current chunk lineage."""

from dataclasses import dataclass
from typing import Any

from evals.schemas.dataset import EvidenceLocator
from evals.schemas.response import RetrievedChunk


@dataclass(frozen=True)
class EvidenceResolution:
    """Relevant current chunk ids, or a reason coordinate lineage cannot be used."""

    chunk_ids: set[str]
    matched_indices: set[int]
    matched_evidence_indices: set[int]
    lineage_failure: str | None = None


def _formats_match(left: str, right: str) -> bool:
    aliases = {"text": "txt", "markdown": "md"}
    return aliases.get(left.lower(), left.lower()) == aliases.get(right.lower(), right.lower())


def _ranges_overlap(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


def _valid_bbox(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    if not all(isinstance(item, (int, float)) for item in value):
        return False
    return value[0] < value[2] and value[1] < value[3]


def _bbox_overlap(left: Any, right: Any) -> bool:
    if not _valid_bbox(left) or not _valid_bbox(right):
        return False
    return _ranges_overlap(float(left[0]), float(left[2]), float(right[0]), float(right[2])) and _ranges_overlap(
        float(left[1]), float(left[3]), float(right[1]), float(right[3])
    )


def _locator_is_usable(source_format: str, locator: dict[str, Any]) -> bool:
    source_format = source_format.lower()
    if source_format in {"txt", "md", "html", "htm"}:
        return all(isinstance(locator.get(key), int) for key in ("start_char", "end_char"))
    regions = locator.get("regions")
    candidates = [region for region in regions if isinstance(region, dict)] if isinstance(regions, list) else [locator]
    if source_format == "pdf":
        return any(
            candidate.get("page") is not None
            and (candidate.get("block_id") is not None or _valid_bbox(candidate.get("bbox")))
            for candidate in candidates
        )
    if source_format in {"docx", "pptx"}:
        return any(candidate.get("element_id") for candidate in candidates)
    if source_format == "xlsx":
        return any(
            candidate.get("sheet") is not None
            and (candidate.get("range") is not None or (candidate.get("row") is not None and candidate.get("col") is not None))
            for candidate in candidates
        )
    return False


def _locators_overlap(source_format: str, evidence: dict[str, Any], chunk: dict[str, Any]) -> bool:
    source_format = source_format.lower()
    regions = chunk.get("regions")
    if isinstance(regions, list):
        return any(
            _locators_overlap(source_format, evidence, region)
            for region in regions
            if isinstance(region, dict)
        )
    if source_format in {"txt", "md", "html", "htm"}:
        return (
            evidence.get("element_path") == chunk.get("element_path")
            and all(isinstance(value, int) for value in (
                evidence.get("start_char"), evidence.get("end_char"),
                chunk.get("start_char"), chunk.get("end_char"),
            ))
            and _ranges_overlap(
                evidence["start_char"], evidence["end_char"],
                chunk["start_char"], chunk["end_char"],
            )
        )
    if source_format == "pdf":
        if evidence.get("page") != chunk.get("page"):
            return False
        if evidence.get("block_id") and chunk.get("block_id"):
            return evidence["block_id"] == chunk["block_id"]
        return _bbox_overlap(evidence.get("bbox"), chunk.get("bbox"))
    if source_format in {"docx", "pptx"}:
        return bool(evidence.get("element_id")) and evidence.get("element_id") == chunk.get("element_id")
    if source_format == "xlsx":
        if evidence.get("sheet") != chunk.get("sheet"):
            return False
        return all(evidence.get(key) == chunk.get(key) for key in ("row", "col"))
    return False


def derive_relevant_chunk_ids(
    evidence: list[EvidenceLocator], chunks: list[RetrievedChunk]
) -> EvidenceResolution:
    """Resolve stable evidence coordinates to chunk ids in the current ingestion.

    This intentionally does not fall back to text similarity.  A missing or
    malformed source locator is a lineage failure, not a weak positive match:
    fuzzy matching would make a chunk-size sweep score against regenerated gold.
    """
    if not evidence:
        return EvidenceResolution(set(), set(), set())

    matched_ids: set[str] = set()
    matched_chunk_indices: set[int] = set()
    matched_evidence_indices: set[int] = set()
    evidence_hashes = {item.document_hash for item in evidence}

    for index, chunk in enumerate(chunks):
        source_locator = chunk.metadata.get("source_locator")
        file_hash = chunk.metadata.get("file_hash")
        if file_hash not in evidence_hashes:
            continue
        if not isinstance(source_locator, dict):
            return EvidenceResolution(
                set(), set(), set(),
                f"chunk {chunk.chunk_id} has no source_locator",
            )
        if source_locator.get("document_hash") != file_hash:
            return EvidenceResolution(
                set(), set(), set(),
                f"chunk {chunk.chunk_id} source_locator document_hash does not match its document",
            )
        source_format = source_locator.get("source_format")
        locator = source_locator.get("locator")
        if not isinstance(source_format, str) or not isinstance(locator, dict):
            return EvidenceResolution(
                set(), set(), set(), f"chunk {chunk.chunk_id} has malformed source_locator"
            )
        if source_format.lower() not in {"txt", "md", "html", "htm", "pdf", "docx", "pptx", "xlsx"}:
            return EvidenceResolution(
                set(), set(), set(), f"chunk {chunk.chunk_id} uses unsupported source format {source_format}"
            )
        if not _locator_is_usable(source_format, locator):
            return EvidenceResolution(
                set(), set(), set(), f"chunk {chunk.chunk_id} has unreconstructable source_locator"
            )
        for evidence_index, item in enumerate(evidence):
            if item.document_hash != file_hash or not _formats_match(item.source_format, source_format):
                continue
            if _locators_overlap(source_format, item.locator, locator):
                matched_ids.add(chunk.chunk_id)
                matched_chunk_indices.add(index)
                matched_evidence_indices.add(evidence_index)

    return EvidenceResolution(matched_ids, matched_chunk_indices, matched_evidence_indices)
