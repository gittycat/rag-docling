"""Evaluation v2 metrics: retrieval, citation, and utility helpers."""

from __future__ import annotations

import math
from typing import Iterable


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _chunk_is_relevant(
    chunk_text: str,
    chunk_doc_id: str | None,
    gold_evidence_texts: list[str],
    gold_document_ids: list[str],
) -> bool:
    if gold_evidence_texts:
        normalized_chunk = _normalize(chunk_text)
        return any(_normalize(ev) in normalized_chunk for ev in gold_evidence_texts if ev)
    if gold_document_ids and chunk_doc_id:
        return chunk_doc_id in gold_document_ids
    return False


def _relevance_list(
    retrieved_chunks: list[dict],
    gold_evidence_texts: list[str],
    gold_document_ids: list[str],
) -> list[int]:
    relevances: list[int] = []
    for chunk in retrieved_chunks:
        chunk_text = chunk.get("text", "") or ""
        chunk_doc_id = chunk.get("document_id")
        relevances.append(
            1
            if _chunk_is_relevant(
                chunk_text,
                chunk_doc_id,
                gold_evidence_texts,
                gold_document_ids,
            )
            else 0
        )
    return relevances


def precision_at_k(
    retrieved_chunks: list[dict],
    gold_evidence_texts: list[str],
    gold_document_ids: list[str],
    k: int,
) -> float:
    if not retrieved_chunks or k <= 0:
        return 0.0
    top_k = retrieved_chunks[:k]
    relevances = _relevance_list(top_k, gold_evidence_texts, gold_document_ids)
    return sum(relevances) / len(top_k)


def recall_at_k(
    retrieved_chunks: list[dict],
    gold_evidence_texts: list[str],
    gold_document_ids: list[str],
    k: int,
) -> float:
    if not retrieved_chunks or k <= 0:
        return 0.0

    top_k = retrieved_chunks[:k]

    if gold_evidence_texts:
        covered = 0
        normalized_chunks = [_normalize(c.get("text", "")) for c in top_k]
        for evidence in gold_evidence_texts:
            if not evidence:
                continue
            ev_norm = _normalize(evidence)
            if any(ev_norm in chunk_text for chunk_text in normalized_chunks):
                covered += 1
        return covered / max(len([e for e in gold_evidence_texts if e]), 1)

    if gold_document_ids:
        retrieved_docs = {c.get("document_id") for c in top_k if c.get("document_id")}
        hits = retrieved_docs.intersection(set(gold_document_ids))
        return len(hits) / len(set(gold_document_ids))

    return 0.0


def mean_reciprocal_rank(
    retrieved_chunks: list[dict],
    gold_evidence_texts: list[str],
    gold_document_ids: list[str],
) -> float:
    for idx, chunk in enumerate(retrieved_chunks, start=1):
        if _chunk_is_relevant(
            chunk.get("text", ""),
            chunk.get("document_id"),
            gold_evidence_texts,
            gold_document_ids,
        ):
            return 1.0 / idx
    return 0.0


def ndcg_at_k(
    retrieved_chunks: list[dict],
    gold_evidence_texts: list[str],
    gold_document_ids: list[str],
    k: int,
) -> float:
    if not retrieved_chunks or k <= 0:
        return 0.0
    top_k = retrieved_chunks[:k]
    relevances = _relevance_list(top_k, gold_evidence_texts, gold_document_ids)
    dcg = sum((2**rel - 1) / math.log2(idx + 2) for idx, rel in enumerate(relevances))
    ideal = sorted(relevances, reverse=True)
    idcg = sum((2**rel - 1) / math.log2(idx + 2) for idx, rel in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def citation_precision(
    retrieved_chunks: list[dict],
    gold_evidence_texts: list[str],
    gold_document_ids: list[str],
) -> float:
    if not retrieved_chunks:
        return 0.0
    relevances = _relevance_list(retrieved_chunks, gold_evidence_texts, gold_document_ids)
    return sum(relevances) / len(relevances)


def citation_recall(
    retrieved_chunks: list[dict],
    gold_evidence_texts: list[str],
    gold_document_ids: list[str],
) -> float:
    if not retrieved_chunks:
        return 0.0
    return recall_at_k(retrieved_chunks, gold_evidence_texts, gold_document_ids, k=len(retrieved_chunks))


def aggregate_metric(values: Iterable[float]) -> float:
    values_list = list(values)
    return sum(values_list) / len(values_list) if values_list else 0.0


def is_abstained(answer: str, abstention_phrases: list[str] | None = None) -> bool:
    """Detect abstention response for unanswerable questions."""
    if not answer:
        return False
    normalized = _normalize(answer)
    phrases = abstention_phrases or [
        "I don't have enough information to answer this question.",
        "I do not have enough information to answer this question.",
        "I don't have enough information to answer the question.",
        "I do not have enough information to answer the question.",
        "Not enough information to answer.",
        "Insufficient information to answer.",
    ]
    return any(_normalize(phrase) in normalized for phrase in phrases)


def is_long_form(test_case_metadata: dict, expected_answer: str, question: str) -> bool:
    if test_case_metadata.get("long_form") is True:
        return True
    if test_case_metadata.get("task_type") == "long_form":
        return True
    if len(expected_answer.split()) >= 80:
        return True
    long_form_starters = ("summarize", "summarise", "report", "list all", "provide a report")
    normalized_q = _normalize(question)
    return any(normalized_q.startswith(prefix) for prefix in long_form_starters)


def long_form_evidence_coverage(
    answer: str,
    gold_evidence_texts: list[str],
) -> float:
    if not gold_evidence_texts:
        return 0.0
    normalized_answer = _normalize(answer)
    covered = 0
    total = 0
    for evidence in gold_evidence_texts:
        if not evidence:
            continue
        total += 1
        ev_norm = _normalize(evidence)
        if ev_norm and ev_norm in normalized_answer:
            covered += 1
    return covered / total if total else 0.0
