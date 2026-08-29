"""Postgres persistence and query builders for evaluation experiments."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict
from typing import Any
from urllib.parse import quote

from evals.attribution import FailureAttribution
from evals.schemas import EvalQuestion, EvalResponse, EvalRun

def _json(value: Any) -> Any:
    """Return JSON-safe data without silently stringifying unknown structures."""
    return json.loads(json.dumps(value, default=str))


def code_version() -> str:
    """Prefer an explicit deployment version, with a local git revision fallback."""
    configured = os.environ.get("CODE_VERSION")
    if configured:
        return configured
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def corpus_snapshot_id(datasets: list[Any], questions: list[EvalQuestion]) -> str:
    """Stable identifier for exactly the documents/questions an eval run used."""
    payload = {
        "datasets": [
            {"name": name, "version": version}
            for name, version in sorted({(dataset.name, dataset.version) for dataset in datasets})
        ],
        "questions": [
            {
                "id": question.id,
                "gold": sorted(
                    ((passage.doc_id, passage.chunk_id) for passage in question.gold_passages),
                    key=lambda item: (item[0], item[1] or ""),
                ),
                "evidence": [
                    {
                        "document_hash": item.document_hash,
                        "source_format": item.source_format,
                        "locator": item.locator,
                        "text_hash": item.normalized_text_hash,
                    }
                    for item in question.evidence
                ],
            }
            for question in sorted(questions, key=lambda item: item.id)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"eval:{hashlib.sha256(encoded.encode()).hexdigest()}"


def judging_mode(judge_enabled: bool) -> str:
    """Record whether judging shared the answer worker's execution path."""
    if not judge_enabled:
        return "none"
    configured = os.environ.get("EVAL_JUDGING_MODE", "inline").lower()
    if configured not in {"inline", "out_of_band"}:
        raise ValueError("EVAL_JUDGING_MODE must be inline or out_of_band")
    return configured


def database_url_from_environment() -> str | None:
    """Build the private Postgres URL without exposing credentials in logs."""
    if configured := os.environ.get("EVAL_DATABASE_URL"):
        return configured
    user = _environment_or_secret("RAG_SERVER_DB_USER")
    password = _environment_or_secret("RAG_SERVER_DB_PASSWORD")
    if not user or not password:
        return None
    host = os.environ.get("DATABASE_HOST", "postgres")
    port = os.environ.get("DATABASE_PORT", "5432")
    database = os.environ.get("DATABASE_NAME", "ragbench")
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{quote(database, safe='')}"


def _environment_or_secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        value = open(f"/run/secrets/{name}").read().strip()
    except OSError:
        return None
    return value or None


def _experiment_id(run: EvalRun) -> str:
    identity = {
        "corpus_snapshot_id": run.metadata["corpus_snapshot_id"],
        "chunking": {
            "size": run.config.chunk_size,
            "overlap": run.config.chunk_overlap,
            "chunker": run.config.chunker,
        },
        "embedding_model": run.config.embedding_model,
        "retrieval": run.config.additional.get("retrieval", {}),
        "reranker": run.config.reranker_model,
        "prompts_hash": run.config.prompt_fingerprint,
        "judge_model": run.metadata.get("judge_model"),
        "judge_execution_boundary": run.metadata.get("judge_execution_boundary"),
        "judging_mode": run.metadata.get("judging_mode"),
        "code_version": run.metadata.get("code_version"),
    }
    encoded = json.dumps(identity, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _question_data(question: EvalQuestion) -> dict[str, Any]:
    return _json(
        {
            "question": question.question,
            "expected_answer": question.expected_answer,
            "answer_nuggets": question.answer_nuggets,
            "gold_passages": [asdict(item) for item in question.gold_passages],
            "evidence": [asdict(item) for item in question.evidence],
            "query_type": question.query_type.value,
            "difficulty": question.difficulty.value,
            "domain": question.domain,
            "is_unanswerable": question.is_unanswerable,
            "metadata": question.metadata,
        }
    )


def _response_data(response: EvalResponse) -> dict[str, Any]:
    return _json(
        {
            "answer": response.answer,
            "retrieved_chunks": [asdict(item) for item in response.retrieved_chunks],
            "citations": [asdict(item) for item in response.citations],
            "metrics": asdict(response.metrics) if response.metrics else None,
        }
    )


class ExperimentStore:
    """Explicit-SQL Postgres store for experiments and per-question provenance."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    @classmethod
    def from_environment(cls) -> "ExperimentStore | None":
        database_url = database_url_from_environment()
        return cls(database_url) if database_url else None

    async def persist_run(
        self,
        run: EvalRun,
        questions: list[EvalQuestion],
        responses: list[EvalResponse],
        attributions: list[FailureAttribution],
    ) -> str:
        """Atomically persist an aggregate run and every per-question decision."""
        if len(questions) != len(responses) or len(questions) != len(attributions):
            raise ValueError("questions, responses, and attributions must be aligned")

        import asyncpg

        experiment_id = _experiment_id(run)
        connection = await asyncpg.connect(self.database_url)
        try:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO experiments (
                        id, name, corpus_snapshot_id, chunking_config, embedding_model,
                        retrieval_settings, reranker_model, prompts_hash, judge_model,
                        judge_execution_boundary, judging_mode, code_version, identity
                    ) VALUES (
                        $1, $2, $3, $4::jsonb, $5, $6::jsonb, $7, $8, $9, $10, $11, $12, $13::jsonb
                    ) ON CONFLICT (id) DO NOTHING
                    """,
                    experiment_id,
                    run.name,
                    run.metadata["corpus_snapshot_id"],
                    json.dumps({"size": run.config.chunk_size, "overlap": run.config.chunk_overlap, "chunker": run.config.chunker}),
                    run.config.embedding_model,
                    json.dumps(run.config.additional.get("retrieval", {})),
                    run.config.reranker_model,
                    run.config.prompt_fingerprint,
                    run.metadata.get("judge_model"),
                    run.metadata.get("judge_execution_boundary"),
                    run.metadata.get("judging_mode"),
                    run.metadata.get("code_version"),
                    json.dumps(_json(run.config.additional)),
                )
                await connection.execute(
                    """
                    INSERT INTO runs (
                        id, experiment_id, name, created_at, completed_at, datasets,
                        question_count, error_count, config, metadata, weighted_score
                    ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb)
                    """,
                    run.id,
                    experiment_id,
                    run.name,
                    run.created_at,
                    run.completed_at,
                    json.dumps(run.datasets),
                    run.question_count,
                    run.error_count,
                    json.dumps(_json(asdict(run.config))),
                    json.dumps(_json(run.metadata)),
                    json.dumps(_json(asdict(run.weighted_score))) if run.weighted_score else None,
                )
                if run.scorecard:
                    for metric in run.scorecard.metrics:
                        await connection.execute(
                            """
                            INSERT INTO run_metrics (run_id, metric_name, metric_group, value, sample_size, details)
                            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                            """,
                            run.id,
                            metric.name,
                            metric.group.value,
                            metric.value,
                            metric.sample_size,
                            json.dumps(_json(metric.details)),
                        )
                for question, response, attribution in zip(questions, responses, attributions):
                    question_row_id = await connection.fetchval(
                        """
                        INSERT INTO run_questions (
                            run_id, question_id, question, response, primary_failure_stage, failure_labels
                        ) VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6::text[])
                        RETURNING id
                        """,
                        run.id,
                        question.id,
                        json.dumps(_question_data(question)),
                        json.dumps(_response_data(response)),
                        attribution.primary_failure_stage,
                        attribution.failure_labels,
                    )
                    for stage, evidence in attribution.stage_evidence.items():
                        await connection.execute(
                            """
                            INSERT INTO question_stages (run_question_id, stage, supported, assessable, evidence)
                            VALUES ($1, $2, $3, $4, $5::jsonb)
                            """,
                            question_row_id,
                            stage,
                            evidence.get("supported", False),
                            evidence.get("assessable", False),
                            json.dumps(_json(evidence)),
                        )
        finally:
            await connection.close()
        return experiment_id

    async def questions_with_failure_label(
        self, label: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return questions supported by a failure label, using indexed stage rows."""
        if label not in FAILURE_STAGES:
            raise ValueError(f"Unknown failure label: {label}")
        import asyncpg

        connection = await asyncpg.connect(self.database_url)
        try:
            rows = await connection.fetch(
                """
                SELECT r.id AS run_id, r.name AS run_name, rq.question_id, rq.question,
                       rq.primary_failure_stage, qs.evidence
                FROM question_stages qs
                JOIN run_questions rq ON rq.id = qs.run_question_id
                JOIN runs r ON r.id = rq.run_id
                WHERE qs.stage = $1 AND qs.supported = TRUE
                ORDER BY r.completed_at DESC NULLS LAST, rq.id
                LIMIT $2
                """,
                label,
                limit,
            )
            return [dict(row) for row in rows]
        finally:
            await connection.close()
