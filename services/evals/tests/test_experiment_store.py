"""Phase-6 experiment store tests: the failure query and corpus identity."""

import asyncio

import asyncpg
import pytest

from evals.experiment_store import FAILURE_STAGES, ExperimentStore, corpus_snapshot_id
from evals.schemas import EvalDataset, EvalQuestion, GoldPassage


def _dataset(name: str = "fixture", version: str = "1") -> EvalDataset:
    return EvalDataset(name=name, version=version, questions=[])


def _question(gold_text: str, context_text: str | None = None) -> EvalQuestion:
    context_passages = [GoldPassage(doc_id="doc-1", chunk_id=None, text=context_text)] if context_text else []
    return EvalQuestion(
        id="q1",
        question="Where is the evidence?",
        expected_answer="Here.",
        gold_passages=[GoldPassage(doc_id="doc-1", chunk_id="gold", text=gold_text)],
        context_passages=context_passages,
    )


class TestFailureQueryDoesNotCrashBeforeConnecting:
    """R4: questions_with_failure_label used to raise NameError('FAILURE_STAGES')
    before ever attempting a connection, because experiment_store.py referenced
    the name without importing it. The label-validation step must run cleanly for
    every supported label; only a connection attempt should follow.
    """

    def test_every_supported_label_passes_validation_without_nameerror(self, monkeypatch):
        class _Sentinel(Exception):
            pass

        async def _fake_connect(*args, **kwargs):
            raise _Sentinel("validation passed; this is the connection attempt")

        monkeypatch.setattr(asyncpg, "connect", _fake_connect)
        store = ExperimentStore("postgresql://u:p@127.0.0.1:1/db")

        for label in FAILURE_STAGES:
            with pytest.raises(_Sentinel):
                asyncio.run(store.questions_with_failure_label(label, 5))

    def test_unknown_label_still_rejected_before_connecting(self, monkeypatch):
        def _fail_if_called(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("must not attempt a connection for an unknown label")

        monkeypatch.setattr(asyncpg, "connect", _fail_if_called)
        store = ExperimentStore("postgresql://u:p@127.0.0.1:1/db")

        with pytest.raises(ValueError):
            asyncio.run(store.questions_with_failure_label("not_a_real_label", 5))

    def test_r4_reproduction_reaches_a_real_connection_attempt(self):
        # Nothing listens on 127.0.0.1:1 — a ConnectionRefusedError/OSError here
        # is the success signal: it proves execution got past FAILURE_STAGES
        # validation and asyncpg import into an actual connect() call, rather
        # than dying on NameError first.
        store = ExperimentStore("postgresql://u:p@127.0.0.1:1/db")
        with pytest.raises(OSError):
            asyncio.run(store.questions_with_failure_label("rerank_drop", 5))


class TestCorpusSnapshotIdHashesCorpusContent:
    def test_changing_gold_passage_text_changes_the_snapshot_id(self):
        datasets = [_dataset()]
        original = corpus_snapshot_id(datasets, [_question("The evidence is here.")])
        edited = corpus_snapshot_id(datasets, [_question("The evidence has been silently edited.")])

        assert original != edited

    def test_changing_distractor_text_changes_the_snapshot_id(self):
        datasets = [_dataset()]
        base = corpus_snapshot_id(
            datasets, [_question("The evidence is here.", context_text="distractor one")]
        )
        edited = corpus_snapshot_id(
            datasets, [_question("The evidence is here.", context_text="distractor TWO")]
        )

        assert base != edited

    def test_identical_corpus_and_questions_are_deterministic(self):
        datasets = [_dataset()]
        first = corpus_snapshot_id(datasets, [_question("The evidence is here.")])
        second = corpus_snapshot_id(datasets, [_question("The evidence is here.")])

        assert first == second
