"""Golden dataset loader for local curated Q&A pairs."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from evals.datasets.base import BaseDatasetLoader
from evals.schemas import EvalDataset, EvalQuestion, GoldPassage, QueryType, Difficulty


class GoldenDatasetLoader(BaseDatasetLoader):
    """Loader for the local golden Q&A dataset.

    Loads curated question-answer pairs from evals/data/golden_qa.json.
    This dataset is used for quick local testing without requiring
    external dataset downloads.
    """

    # Path for local development
    GOLDEN_PATH = Path("evals/data/golden_qa.json")
    # Path inside Docker container
    GOLDEN_PATH_DOCKER = Path("/app/evals/data/golden_qa.json")

    @property
    def name(self) -> str:
        return "golden"

    @property
    def description(self) -> str:
        return "Curated Q&A pairs from your indexed documents"

    @property
    def source_url(self) -> str:
        return "local"

    @property
    def primary_aspects(self) -> list[str]:
        return ["generation", "retrieval"]

    @property
    def domains(self) -> list[str]:
        return ["user documents"]

    def _get_path(self) -> Path:
        """Get the appropriate path based on environment."""
        if self.GOLDEN_PATH_DOCKER.exists():
            return self.GOLDEN_PATH_DOCKER
        if self.GOLDEN_PATH.exists():
            return self.GOLDEN_PATH
        raise FileNotFoundError(
            f"Golden dataset not found at {self.GOLDEN_PATH} or {self.GOLDEN_PATH_DOCKER}"
        )

    @staticmethod
    def _parse_passages(item: dict[str, Any], key: str, fallback_doc: str) -> list[GoldPassage]:
        """Parse optional passage annotations from one golden_qa.json entry.

        Three accepted shapes, in decreasing fidelity:
          "gold_passages": [{"doc_id": ..., "chunk_id": ..., "text": ...}, ...]
          "gold_passages": ["raw passage text", ...]      (ids derived from `document`)
          "gold_doc_ids":  ["report.pdf", ...]            (doc-level only, no text)

        Doc-level-only entries support retrieval metrics but not the text-overlap
        path in the citation metrics, which is why the richer form is preferred.
        """
        passages: list[GoldPassage] = []

        for idx, raw in enumerate(item.get(key) or []):
            if isinstance(raw, str):
                doc_id = fallback_doc
                passages.append(
                    GoldPassage(
                        doc_id=doc_id,
                        chunk_id=f"{doc_id}:{key}:{idx}",
                        text=raw,
                    )
                )
                continue
            doc_id = raw.get("doc_id") or fallback_doc
            passages.append(
                GoldPassage(
                    doc_id=doc_id,
                    chunk_id=raw.get("chunk_id") or f"{doc_id}:{key}:{idx}",
                    text=raw.get("text", ""),
                    relevance_score=raw.get("relevance_score", 1.0),
                )
            )

        if key == "gold_passages":
            for doc_id in item.get("gold_doc_ids") or []:
                if any(p.doc_id == doc_id for p in passages):
                    continue
                passages.append(
                    GoldPassage(doc_id=doc_id, chunk_id=f"{doc_id}:doc", text="")
                )

        return passages

    def _map_query_type(self, qt: str) -> QueryType:
        """Map golden dataset query types to QueryType enum."""
        mapping = {
            "factual": QueryType.FACTOID,
            "factoid": QueryType.FACTOID,
            "reasoning": QueryType.MULTI_HOP,
            "multi_hop": QueryType.MULTI_HOP,
            "summary": QueryType.SUMMARY,
            "procedural": QueryType.PROCEDURAL,
            "comparison": QueryType.COMPARISON,
            "unanswerable": QueryType.UNANSWERABLE,
        }
        return mapping.get(qt.lower(), QueryType.FACTOID)

    def load(
        self,
        split: str = "test",
        max_samples: int | None = None,
        seed: int | None = None,
    ) -> EvalDataset:
        """Load the golden dataset.

        Args:
            split: Ignored for golden dataset (only one split)
            max_samples: Maximum number of samples to load
            seed: Random seed for sampling

        Returns:
            EvalDataset with loaded questions
        """
        path = self._get_path()

        with open(path) as f:
            data = json.load(f)

        questions = []
        annotated = 0
        for idx, item in enumerate(data):
            fallback_doc = item.get("document") or f"golden:{idx}"
            gold_passages = self._parse_passages(item, "gold_passages", fallback_doc)
            context_passages = self._parse_passages(item, "context_passages", fallback_doc)
            if gold_passages:
                annotated += 1

            question = EvalQuestion(
                id=self._create_question_id("golden", idx),
                question=item["question"],
                expected_answer=item.get("answer"),
                gold_passages=gold_passages,
                context_passages=context_passages,
                query_type=self._map_query_type(item.get("query_type", "factual")),
                difficulty=Difficulty.MEDIUM,
                domain=item.get("document", "unknown"),
                is_unanswerable=item.get("is_unanswerable", False),
                metadata={
                    "document": item.get("document"),
                    "context_hint": item.get("context_hint"),
                },
            )
            questions.append(question)

        if annotated < len(questions):
            # Retrieval and citation metrics now return "undefined" for these rather
            # than 0.0 / 1.0, so the run stays honest — but the user should know why
            # those columns are blank.
            logger.info(
                "[GOLDEN] %d of %d questions have gold_passages; retrieval and "
                "citation metrics are undefined for the rest. Add 'gold_passages' "
                "or 'gold_doc_ids' to golden_qa.json entries to measure them.",
                annotated,
                len(questions),
            )

        # Sample if max_samples specified
        if max_samples and len(questions) > max_samples:
            questions = self._rng(seed).sample(questions, max_samples)

        return EvalDataset(
            name=self.name,
            version="1.0",
            questions=questions,
            description=self.description,
            source_url=self.source_url,
            domains=self.domains,
            metadata={"path": str(path)},
        )

    def get_metadata(self) -> dict[str, Any]:
        """Get metadata about this dataset."""
        size = 0
        try:
            path = self._get_path()
            with open(path) as f:
                size = len(json.load(f))
        except FileNotFoundError:
            pass

        return {
            "id": self.name,
            "name": "Golden Dataset (Local)",
            "description": self.description,
            "size": size,
            "domains": self.domains,
            "primary_aspects": self.primary_aspects,
            "requires_download": False,
            "download_size_mb": 0,
        }
