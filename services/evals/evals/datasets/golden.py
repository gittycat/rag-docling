"""Golden dataset loader for local curated Q&A pairs."""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from evals.datasets.base import BaseDatasetLoader
from evals.schemas import EvalDataset, EvalQuestion, GoldPassage, QueryType, Difficulty
from evals.schemas.dataset import EvidenceLocator


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

    # The corpus contract: source documents a question's evidence can anchor to.
    # A locator's document_hash is the sha256 of the file's bytes, which is what
    # documents.file_hash records after ingestion — so a locator authored here
    # resolves against the real ingested document rather than a synthesized one.
    CORPUS_DIR = Path("evals/data/documents")
    CORPUS_DIR_DOCKER = Path("/app/evals/data/documents")

    SOURCE_FORMAT_BY_SUFFIX = {
        ".txt": "txt", ".md": "md", ".html": "html", ".htm": "htm",
        ".pdf": "pdf", ".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx",
    }

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

    def _corpus_dir(self) -> Path | None:
        for candidate in (self.CORPUS_DIR_DOCKER, self.CORPUS_DIR):
            if candidate.is_dir():
                return candidate
        return None

    def _source_path(self, document: str | None) -> Path | None:
        corpus = self._corpus_dir()
        if corpus is None or not document:
            return None
        # Basename only: a dataset file must not be able to read outside the corpus.
        candidate = corpus / Path(document).name
        return candidate if candidate.is_file() else None

    @staticmethod
    def _normalize(text: str) -> str:
        # Same rule the server applies when it records chunk lineage
        # (rag_server/pipelines/ingestion.py `_normalized_text`), so an authored
        # evidence hash is comparable to an ingested chunk's.
        return re.sub(r"\s+", " ", text).strip()

    def _parse_evidence(self, item: dict[str, Any], idx: int) -> list[EvidenceLocator]:
        """Build source-coordinate locators anchored to a real corpus file.

        Authored per the plan's rules: from the source document, never from a
        chunk. A locator whose source file is missing is dropped with a warning
        rather than anchored to a hash that will never match anything — a
        silently unresolvable locator is worse than an absent one.
        """
        raw_evidence = item.get("evidence") or []
        if not raw_evidence:
            return []

        document = item.get("source_file") or item.get("document")
        source_path = self._source_path(document)
        if source_path is None:
            logger.warning(
                "[GOLDEN] Question %d declares evidence but its source document "
                "%r is not in the corpus directory; dropping the locators. "
                "Retrieval metrics fall back to the chunk_id ground truth.",
                idx, document,
            )
            return []

        document_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        source_format = self.SOURCE_FORMAT_BY_SUFFIX.get(source_path.suffix.lower())
        if source_format is None:
            logger.warning(
                "[GOLDEN] Unsupported source format %r for question %d; dropping locators.",
                source_path.suffix, idx,
            )
            return []

        locators: list[EvidenceLocator] = []
        for position, raw in enumerate(raw_evidence):
            text = raw.get("text") or raw.get("normalized_text") or ""
            if not text or not raw.get("locator"):
                logger.warning(
                    "[GOLDEN] Question %d evidence %d needs both 'text' and "
                    "'locator'; skipping it.", idx, position,
                )
                continue
            normalized = self._normalize(text)
            locators.append(
                EvidenceLocator(
                    document_hash=document_hash,
                    source_format=raw.get("source_format") or source_format,
                    locator=raw["locator"],
                    normalized_text=normalized,
                    normalized_text_hash=hashlib.sha256(normalized.encode()).hexdigest(),
                    evidence_set_id=raw.get("evidence_set_id"),
                )
            )
        return locators

    def fingerprint(self) -> dict[str, Any]:
        """Cache-key inputs. The locator payload and the bytes of every corpus
        file it anchors to are included: re-authoring a locator, or replacing a
        source document, must not be served a cache entry built against the old
        one.
        """
        try:
            path = self._get_path()
            with open(path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

        evidence_payload = [
            {"index": idx, "evidence": item.get("evidence"),
             "source_file": item.get("source_file") or item.get("document")}
            for idx, item in enumerate(data)
            if item.get("evidence")
        ]
        source_hashes = {}
        for entry in evidence_payload:
            source_path = self._source_path(entry["source_file"])
            if source_path is not None:
                source_hashes[source_path.name] = hashlib.sha256(
                    source_path.read_bytes()
                ).hexdigest()
        if not evidence_payload:
            return {}
        return {
            "evidence": json.dumps(evidence_payload, sort_keys=True),
            "source_documents": source_hashes,
        }

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

            evidence = self._parse_evidence(item, idx)
            source_path = self._source_path(item.get("source_file") or item.get("document"))
            question = EvalQuestion(
                id=self._create_question_id("golden", idx),
                question=item["question"],
                expected_answer=item.get("answer"),
                gold_passages=gold_passages,
                evidence=evidence,
                context_passages=context_passages,
                query_type=self._map_query_type(item.get("query_type", "factual")),
                difficulty=Difficulty.MEDIUM,
                domain=item.get("document", "unknown"),
                is_unanswerable=item.get("is_unanswerable", False),
                metadata={
                    "document": item.get("document"),
                    "context_hint": item.get("context_hint"),
                    # The runner uploads these bytes verbatim so the ingested
                    # document's file_hash equals the locator's document_hash.
                    "source_path": str(source_path) if source_path else None,
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
