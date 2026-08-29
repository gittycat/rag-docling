"""Resolve source-coordinate gold evidence against the current chunk lineage."""

import re
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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalized_text_disagrees(evidence: EvidenceLocator, source_locator: dict[str, Any]) -> bool:
    """True only when the chunk's lineage actively contradicts the evidence
    text at a coordinate-matched location - the real coordinate-drift signal.

    A real chunk's normalized_text_hash hashes the WHOLE node's content
    (services/rag_server/pipelines/ingestion.py `_source_locator`), a strict
    superset of any evidence span it resolves - not the evidence span itself.
    So containment, not hash equality, is the correct secondary check: the
    evidence's normalized_text must appear as a substring of the chunk's.
    Hash equality is kept as a fast path (identical hash implies identical,
    and therefore trivially containing, text) but hash INEQUALITY alone must
    never be treated as disagreement - on a real corpus it is the norm, not
    the exception. When the chunk's lineage carries neither a matching hash
    nor a normalized_text to test containment against, there is no signal
    either way, so the coordinate match stands rather than manufacturing a
    failure out of a lineage field that was never recorded. Do not
    "simplify" this back to hash equality.
    """
    chunk_hash = source_locator.get("normalized_text_hash")
    if chunk_hash is not None and chunk_hash == evidence.normalized_text_hash:
        return False
    chunk_text = source_locator.get("normalized_text")
    if not isinstance(chunk_text, str):
        return False
    return _normalize_text(evidence.normalized_text) not in _normalize_text(chunk_text)


def _ranges_overlap(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


def _normalized_bbox(value: Any) -> tuple[float, float, float, float] | None:
    """A bbox as (min_x, min_y, max_x, max_y), or None if it is not a real box.

    Docling emits PDF provenance with `coord_origin: BOTTOMLEFT`, where the
    top edge has a LARGER y than the bottom edge. Assuming a top-left origin
    (y0 < y1) rejected every real PDF bbox as malformed, which made every PDF
    locator unusable and turned the whole PDF path into a lineage failure.
    Ordering the pairs makes the comparison origin-agnostic; a box with zero
    extent on either axis is still not a box.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
        return None
    x0, x1 = sorted((float(value[0]), float(value[2])))
    y0, y1 = sorted((float(value[1]), float(value[3])))
    if x0 == x1 or y0 == y1:
        return None
    return x0, y0, x1, y1


def _valid_bbox(value: Any) -> bool:
    return _normalized_bbox(value) is not None


def _bbox_overlap(left: Any, right: Any) -> bool:
    left_box = _normalized_bbox(left)
    right_box = _normalized_bbox(right)
    if left_box is None or right_box is None:
        return False
    return _ranges_overlap(left_box[0], left_box[2], right_box[0], right_box[2]) and _ranges_overlap(
        left_box[1], left_box[3], right_box[1], right_box[3]
    )


def _rect_contains(outer: tuple[float, float, float, float], inner: tuple[float, float, float, float]) -> bool:
    """Generic 4-tuple (min0, min1, max0, max1) containment, shared by bbox and xlsx rectangles."""
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def _bbox_contains(outer: Any, inner: Any) -> bool:
    outer_box = _normalized_bbox(outer)
    inner_box = _normalized_bbox(inner)
    if outer_box is None or inner_box is None:
        return False
    return _rect_contains(outer_box, inner_box)


def _parse_a1_cell(ref: str) -> tuple[int, int] | None:
    """Parse an A1-style cell reference (e.g. 'B2') into zero-indexed (row, col)."""
    match = re.fullmatch(r"([A-Za-z]+)(\d+)", ref.strip())
    if not match:
        return None
    col_letters, row_digits = match.groups()
    col = 0
    for char in col_letters.upper():
        col = col * 26 + (ord(char) - ord("A") + 1)
    return int(row_digits) - 1, col - 1


def _parse_xlsx_range(value: Any) -> tuple[int, int, int, int] | None:
    """Parse an A1-style range ('Sheet1!B2:D10' or 'B2:D10', or a bare cell) into
    an inclusive zero-indexed (row_start, col_start, row_end, col_end) rectangle.
    Malformed input returns None so it is treated as unusable, never as a match."""
    if not isinstance(value, str) or not value:
        return None
    range_part = value.split("!")[-1]
    parts = range_part.split(":")
    if len(parts) == 1:
        cell = _parse_a1_cell(parts[0])
        if cell is None:
            return None
        row, col = cell
        return row, col, row, col
    if len(parts) != 2:
        return None
    start = _parse_a1_cell(parts[0])
    end = _parse_a1_cell(parts[1])
    if start is None or end is None:
        return None
    row_start, col_start = start
    row_end, col_end = end
    if row_start > row_end or col_start > col_end:
        return None
    return row_start, col_start, row_end, col_end


def _xlsx_rectangle(locator: dict[str, Any]) -> tuple[int, int, int, int] | None:
    """A locator's cell/range as a rectangle. A bare row/col is a 1x1 rectangle
    so it compares uniformly against a 'range' locator. Returns None (unusable)
    for a locator with neither a parseable range nor a row/col pair."""
    range_value = locator.get("range")
    if range_value is not None:
        return _parse_xlsx_range(range_value)
    row, col = locator.get("row"), locator.get("col")
    if isinstance(row, int) and isinstance(col, int):
        return row, col, row, col
    return None


def _xlsx_rect_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    left_row0, left_col0, left_row1, left_col1 = left
    right_row0, right_col0, right_row1, right_col1 = right
    return left_row0 <= right_row1 and right_row0 <= left_row1 and left_col0 <= right_col1 and right_col0 <= left_col1


def _locator_contains(source_format: str, outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    """True if `outer` (typically a chunk's locator) wholly contains `inner`
    (typically the evidence's), per source format. `outer.regions`, when present,
    are checked recursively — any one region containing `inner` is sufficient,
    mirroring how `_locators_overlap` treats a chunk's regions. `None` on either
    side of a required coordinate is never treated as a match.
    """
    source_format = source_format.lower()
    regions = outer.get("regions")
    if isinstance(regions, list):
        return any(
            _locator_contains(source_format, region, inner)
            for region in regions
            if isinstance(region, dict)
        )
    if source_format in {"txt", "md", "html", "htm"}:
        return (
            outer.get("element_path") == inner.get("element_path")
            and isinstance(outer.get("start_char"), int)
            and isinstance(outer.get("end_char"), int)
            and isinstance(inner.get("start_char"), int)
            and isinstance(inner.get("end_char"), int)
            and outer["start_char"] <= inner["start_char"]
            and outer["end_char"] >= inner["end_char"]
        )
    if source_format == "pdf":
        if outer.get("page") is None or outer.get("page") != inner.get("page"):
            return False
        if outer.get("block_id") and inner.get("block_id"):
            return outer["block_id"] == inner["block_id"]
        return _bbox_contains(outer.get("bbox"), inner.get("bbox"))
    if source_format in {"docx", "pptx"}:
        return bool(outer.get("element_id")) and outer.get("element_id") == inner.get("element_id")
    if source_format == "xlsx":
        if outer.get("sheet") is None or outer.get("sheet") != inner.get("sheet"):
            return False
        outer_rect = _xlsx_rectangle(outer)
        inner_rect = _xlsx_rectangle(inner)
        if outer_rect is None or inner_rect is None:
            return False
        return _rect_contains(outer_rect, inner_rect)
    return False


def _locator_is_usable(source_format: str, locator: dict[str, Any]) -> bool:
    source_format = source_format.lower()
    if source_format in {"txt", "md", "html", "htm"}:
        return all(isinstance(locator.get(key), int) for key in ("start_char", "end_char"))
    regions = locator.get("regions")
    candidates = [region for region in regions if isinstance(region, dict)] if isinstance(regions, list) else [locator]
    if source_format == "pdf":
        # Docling's provenance carries `element_id` (its self_ref), not
        # `block_id`; accepting only block_id or a bbox made every real Docling
        # PDF locator unusable.
        return any(
            candidate.get("page") is not None
            and (
                candidate.get("block_id") is not None
                or candidate.get("element_id") is not None
                or _valid_bbox(candidate.get("bbox"))
            )
            for candidate in candidates
        )
    if source_format in {"docx", "pptx"}:
        return any(candidate.get("element_id") for candidate in candidates)
    if source_format == "xlsx":
        # A locator is usable only when its range/cell actually parses to a
        # rectangle - a malformed `range` string is unusable, not silently
        # accepted and then never compared (see _locators_overlap).
        return any(
            candidate.get("sheet") is not None and _xlsx_rectangle(candidate) is not None
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
        # A page is a required positive assertion: both sides absent must never
        # compare equal as a match.
        if evidence.get("page") is None or evidence.get("page") != chunk.get("page"):
            return False
        if evidence.get("block_id") and chunk.get("block_id"):
            return evidence["block_id"] == chunk["block_id"]
        return _bbox_overlap(evidence.get("bbox"), chunk.get("bbox"))
    if source_format in {"docx", "pptx"}:
        return bool(evidence.get("element_id")) and evidence.get("element_id") == chunk.get("element_id")
    if source_format == "xlsx":
        if evidence.get("sheet") is None or evidence.get("sheet") != chunk.get("sheet"):
            return False
        # row/col and range locators must compare uniformly: parse both to
        # rectangles and test real rectangle overlap. Two range locators that
        # neither carry row/col must never compare equal by coincidence.
        evidence_rect = _xlsx_rectangle(evidence)
        chunk_rect = _xlsx_rectangle(chunk)
        if evidence_rect is None or chunk_rect is None:
            return False
        return _xlsx_rect_overlap(evidence_rect, chunk_rect)
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
            if not _locators_overlap(source_format, item.locator, locator):
                continue
            # Secondary check: see _normalized_text_disagrees. Catches genuine
            # coordinate drift (a re-parse that shifts offsets but still
            # parses and still overlaps) without flagging every ordinary
            # match, since a chunk's normalized_text is a superset of the
            # evidence span by construction.
            if _normalized_text_disagrees(item, source_locator):
                return EvidenceResolution(
                    set(), set(), set(),
                    f"chunk {chunk.chunk_id} matched evidence coordinates but its normalized_text does not "
                    "contain the evidence span (possible lineage drift)",
                )
            matched_ids.add(chunk.chunk_id)
            matched_chunk_indices.add(index)
            matched_evidence_indices.add(evidence_index)

    return EvidenceResolution(matched_ids, matched_chunk_indices, matched_evidence_indices)
