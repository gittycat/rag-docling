"""Citation quality metrics.

Measures how well the RAG system cites sources for its claims.
"""

from typing import Any

from evals.metrics.base import BaseMetric
from evals.metrics.text_match import _token_overlap
from evals.schemas import (
    EvalQuestion,
    EvalResponse,
    MetricResult,
    MetricGroup,
)


def chunk_by_rank(response: EvalResponse) -> dict[int, Any]:
    """Build lookup from 1-based rank to RetrievedChunk.

    A citation's `source_index` is the 1-based position of the chunk as it was
    shown to the model, which is the same numbering `rank` carries. Shared with
    the groundedness metrics so both resolve a marker to a chunk identically.
    """
    return {c.rank: c for c in response.retrieved_chunks if c.rank is not None}


def _doc_only_gold_ids(question: EvalQuestion) -> set[str]:
    """Doc ids of gold passages annotated at document level (no passage text).

    `gold_doc_ids` in a golden_qa.json entry produces these. They can only ever be
    matched by document, so chunk-id and text comparison would score them 0.
    """
    return {p.doc_id for p in question.gold_passages if not p.text}


def _cited_doc_ids(citation: Any, retrieved: Any) -> set[str]:
    """Doc ids a citation resolves to, directly or via the chunk it points at."""
    ids = set()
    if citation.doc_id:
        ids.add(citation.doc_id)
    if retrieved and retrieved.doc_id:
        ids.add(retrieved.doc_id)
    return ids


def _undefined(metric: "BaseMetric") -> MetricResult:
    """Citation quality is undefined without gold passages to score against.

    Previously these returned 1.0, so any dataset lacking retrieval annotations
    (the golden set, until it gained optional gold_passages) displayed perfect
    citation precision and recall that measured nothing at all.
    """
    return MetricResult(
        name=metric.name,
        value=None,
        group=metric.group,
        sample_size=0,
        details={"note": "No gold passages defined — citation quality is undefined"},
    )


class CitationPrecision(BaseMetric):
    """Citation precision measures the fraction of citations that are relevant.

    Citation Precision = |Cited ∩ Relevant| / |Cited|

    Higher is better. 1.0 means all citations are relevant.
    """

    @property
    def name(self) -> str:
        return "citation_precision"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.CITATION

    @property
    def description(self) -> str:
        return "Fraction of citations that point to relevant passages"

    def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        citations = response.citations
        if not citations:
            return MetricResult(
                name=self.name,
                value=0.0,
                group=self.group,
                sample_size=1,
                details={"note": "No citations in answer"},
            )

        if not question.gold_passages:
            return _undefined(self)

        gold_chunk_ids = {p.chunk_id for p in question.gold_passages}
        doc_only_ids = _doc_only_gold_ids(question)
        chunk_lookup = chunk_by_rank(response)

        hits = 0
        for citation in citations:
            # Exact chunk_id match
            if citation.chunk_id and citation.chunk_id in gold_chunk_ids:
                hits += 1
                continue
            retrieved = chunk_lookup.get(citation.source_index)
            # Document-level annotation: the only resolution available is the doc
            if doc_only_ids and _cited_doc_ids(citation, retrieved) & doc_only_ids:
                hits += 1
                continue
            # Look up the source chunk by rank and do text overlap
            if retrieved and retrieved.text:
                for gold in question.gold_passages:
                    if gold.text and _token_overlap(retrieved.text, gold.text) >= 0.3:
                        hits += 1
                        break

        precision = hits / len(citations)

        return MetricResult(
            name=self.name,
            value=precision,
            group=self.group,
            sample_size=1,
            details={
                "hits": hits,
                "cited_count": len(citations),
                "gold_count": len(question.gold_passages),
            },
        )


class CitationRecall(BaseMetric):
    """Citation recall measures the fraction of relevant passages that are cited.

    Citation Recall = |Cited ∩ Relevant| / |Relevant|

    Higher is better. 1.0 means all relevant passages are cited.
    """

    @property
    def name(self) -> str:
        return "citation_recall"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.CITATION

    @property
    def description(self) -> str:
        return "Fraction of relevant passages that are cited"

    def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        if not question.gold_passages:
            return _undefined(self)

        citations = response.citations
        gold_chunk_ids = {p.chunk_id for p in question.gold_passages}
        chunk_lookup = chunk_by_rank(response)

        # Collect texts of cited chunks (exact id + text fallback)
        cited_texts: list[str] = []
        cited_exact_ids: set[str] = set()
        cited_doc_ids: set[str] = set()
        for citation in citations:
            if citation.chunk_id:
                cited_exact_ids.add(citation.chunk_id)
            retrieved = chunk_lookup.get(citation.source_index)
            cited_doc_ids |= _cited_doc_ids(citation, retrieved)
            if retrieved and retrieved.text:
                cited_texts.append(retrieved.text)

        hits = 0
        for gold in question.gold_passages:
            if gold.chunk_id in cited_exact_ids:
                hits += 1
                continue
            if not gold.text:
                # Document-level annotation — resolvable only by doc id
                if gold.doc_id in cited_doc_ids:
                    hits += 1
                continue
            for cited_text in cited_texts:
                if _token_overlap(cited_text, gold.text) >= 0.3:
                    hits += 1
                    break

        recall = hits / len(question.gold_passages)

        return MetricResult(
            name=self.name,
            value=recall,
            group=self.group,
            sample_size=1,
            details={
                "hits": hits,
                "cited_count": len(citations),
                "gold_count": len(question.gold_passages),
            },
        )


class SectionAccuracy(BaseMetric):
    """Section accuracy measures accuracy at the document+section level.

    Checks if citations point to the correct document AND the correct
    section/chunk within that document.

    Higher is better. 1.0 means perfect section-level accuracy.
    """

    @property
    def name(self) -> str:
        return "section_accuracy"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.CITATION

    @property
    def description(self) -> str:
        return "Accuracy of citations at document+section level"

    def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        gold_passages = {(p.doc_id, p.chunk_id) for p in question.gold_passages}
        gold_doc_ids = {p.doc_id for p in question.gold_passages}

        if not gold_passages:
            return _undefined(self)

        citations = response.citations
        if not citations:
            return MetricResult(
                name=self.name,
                value=0.0,
                group=self.group,
                sample_size=1,
                details={"note": "No citations in answer"},
            )

        chunk_lookup = chunk_by_rank(response)
        doc_correct = 0
        section_correct = 0

        for citation in citations:
            # Exact (doc_id, chunk_id) match
            if citation.doc_id and citation.chunk_id:
                if citation.doc_id in gold_doc_ids:
                    doc_correct += 1
                    if (citation.doc_id, citation.chunk_id) in gold_passages:
                        section_correct += 1
                    continue

            # Text-based fallback via retrieved chunk
            retrieved = chunk_lookup.get(citation.source_index)
            if retrieved and retrieved.text:
                for gold in question.gold_passages:
                    if gold.text and _token_overlap(retrieved.text, gold.text) >= 0.3:
                        doc_correct += 1
                        section_correct += 1  # text match implies section match
                        break

        total_citations = len(citations)
        doc_accuracy = doc_correct / total_citations
        section_accuracy = section_correct / total_citations

        return MetricResult(
            name=self.name,
            value=section_accuracy,
            group=self.group,
            sample_size=1,
            details={
                "doc_accuracy": doc_accuracy,
                "section_accuracy": section_accuracy,
                "doc_correct": doc_correct,
                "section_correct": section_correct,
                "total_citations": total_citations,
            },
        )
