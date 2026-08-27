"""Dataset loaders must return a *sample*, not a prefix.

The defect this guards: `HotpotQALoader` and `MSMarcoLoader` broke out of their
conversion loop at `>= max_samples`, which made the `> max_samples` guard on the
next line unreachable, so `random.sample` never ran. Both loaders returned the
first N rows of the split and the seed changed nothing. Every comparison drawn
from them rested on a biased sample that looked seeded.

`test_rag_eval.py::test_sampling_is_reproducible` could not catch this: a prefix
is perfectly reproducible. The assertion that catches it is that *different*
seeds must select *different* ids.

No network: `load_dataset` is monkeypatched with an in-memory fake throughout.
"""

import random
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.datasets import registry
from evals.datasets.hotpotqa import HotpotQALoader
from evals.datasets.msmarco import MSMarcoLoader


CORPUS_SIZE = 200


class FakeSplit:
    """Enough of a HuggingFace `Dataset` for the loaders: len, index, iterate."""

    def __init__(self, rows):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, idx):
        return self._rows[idx]

    def __iter__(self):
        return iter(self._rows)

    def select(self, indices):
        return FakeSplit([self._rows[i] for i in indices])


def _hotpot_rows(n=CORPUS_SIZE):
    return [
        {
            "id": f"hp-{i}",
            "question": f"question {i}?",
            "answer": f"answer {i}",
            "level": "hard",
            "type": "bridge",
            "supporting_facts": {"title": [], "sent_id": []},
            "context": {"title": [], "sentences": []},
        }
        for i in range(n)
    ]


def _msmarco_rows(n=CORPUS_SIZE):
    return [
        {
            "query_id": i,
            "query": f"query {i}?",
            "query_type": "description",
            "answers": [f"answer {i}"],
            "passages": {
                "passage_text": [f"passage {i}"],
                "is_selected": [1],
                "url": [f"http://example.invalid/{i}"],
            },
        }
        for i in range(n)
    ]


@pytest.fixture
def fake_hotpot(monkeypatch):
    monkeypatch.setattr(
        "evals.datasets.hotpotqa.load_dataset",
        lambda *a, **kw: FakeSplit(_hotpot_rows()),
    )


@pytest.fixture
def fake_msmarco(monkeypatch):
    monkeypatch.setattr(
        "evals.datasets.msmarco.load_dataset",
        lambda *a, **kw: FakeSplit(_msmarco_rows()),
    )


def _ids(dataset):
    return {q.id for q in dataset.questions}


# ── The sample is a sample ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "loader_factory, fixture_name",
    [(HotpotQALoader, "fake_hotpot"), (MSMarcoLoader, "fake_msmarco")],
)
def test_different_seeds_select_different_questions(loader_factory, fixture_name, request):
    """THE regression assertion. A prefix is identical for every seed; a sample
    is not. Over 200 rows choosing 20, two seeds agreeing exactly is possible in
    principle and overwhelmingly unlikely in practice."""
    request.getfixturevalue(fixture_name)
    loader = loader_factory()

    first = _ids(loader.load(max_samples=20, seed=1))
    second = _ids(loader.load(max_samples=20, seed=2))

    assert len(first) == 20
    assert len(second) == 20
    assert first != second


@pytest.mark.parametrize(
    "loader_factory, fixture_name",
    [(HotpotQALoader, "fake_hotpot"), (MSMarcoLoader, "fake_msmarco")],
)
def test_the_same_seed_selects_the_same_questions(loader_factory, fixture_name, request):
    request.getfixturevalue(fixture_name)
    loader = loader_factory()

    assert _ids(loader.load(max_samples=20, seed=7)) == _ids(loader.load(max_samples=20, seed=7))


@pytest.mark.parametrize(
    "loader_factory, fixture_name",
    [(HotpotQALoader, "fake_hotpot"), (MSMarcoLoader, "fake_msmarco")],
)
def test_the_sample_is_drawn_from_the_whole_split(loader_factory, fixture_name, request):
    """A prefix of 20 out of 200 can only contain ids 0-19. A real sample reaches
    past that, and this is what the old `break` made impossible."""
    request.getfixturevalue(fixture_name)
    loader = loader_factory()

    # Row number is carried in the question text ("question 12?" / "query 12?"),
    # which every loader passes through verbatim.
    seen = set()
    for seed in range(6):
        for q in loader.load(max_samples=20, seed=seed).questions:
            seen.add(int(re.search(r"\d+", q.question).group()))

    assert max(seen) >= 20, "every selected question came from the first 20 rows"


def test_max_samples_none_loads_everything(fake_hotpot):
    assert len(HotpotQALoader().load(max_samples=None).questions) == CORPUS_SIZE


# ── Loading must not touch process-wide RNG state ─────────────────────────────


@pytest.mark.parametrize(
    "loader_factory, fixture_name",
    [(HotpotQALoader, "fake_hotpot"), (MSMarcoLoader, "fake_msmarco")],
)
def test_a_load_leaves_the_global_rng_stream_alone(loader_factory, fixture_name, request):
    """Every loader used to call `random.seed(seed)`, reseeding the process-wide
    RNG as a side effect of loading data. Anything else drawing from `random`
    then silently became a function of the eval seed."""
    request.getfixturevalue(fixture_name)

    random.seed(12345)
    expected = [random.random() for _ in range(3)]

    random.seed(12345)
    loader_factory().load(max_samples=10, seed=999)
    actual = [random.random() for _ in range(3)]

    assert actual == expected


# ── The cache key tells two upstream snapshots apart ──────────────────────────


def test_the_cache_key_changes_with_the_pinned_revision():
    base = dict(name="hotpotqa", split="test", max_samples=10, seed=42)
    old = registry._cache_key(**base, fingerprint={"revision": "aaaa"})
    new = registry._cache_key(**base, fingerprint={"revision": "bbbb"})

    assert old != new, "two upstream snapshots would share a cache entry"


def test_the_cache_key_is_stable_for_the_same_fingerprint():
    base = dict(name="hotpotqa", split="test", max_samples=10, seed=42)
    fp = {"revision": "aaaa", "subsets": ["a", "b"]}
    assert registry._cache_key(**base, fingerprint=fp) == registry._cache_key(**base, fingerprint=fp)


def test_loaders_expose_their_pinned_revision_in_the_fingerprint():
    assert HotpotQALoader().fingerprint()["revision"]
    assert MSMarcoLoader().fingerprint()["revision"]


def test_a_cache_file_from_a_different_fingerprint_is_not_served(tmp_path, monkeypatch):
    """Second line of defence behind the key itself."""
    monkeypatch.setattr(registry, "CACHE_DIR", tmp_path)
    from evals.schemas import EvalDataset

    ds = EvalDataset(name="hotpotqa", version="1.0", questions=[])
    registry._write_cache("k", ds, {"revision": "aaaa"})

    assert registry._read_cache("k", {"revision": "aaaa"}) is not None
    assert registry._read_cache("k", {"revision": "bbbb"}) is None


# ── A failed dataset stops the run ────────────────────────────────────────────


def test_load_datasets_raises_on_a_failing_dataset(monkeypatch):
    """Silently covering fewer datasets than were asked for makes a scorecard
    describe a different mix than its label claims."""
    def boom(*a, **kw):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(registry, "get_dataset", boom)

    with pytest.raises(RuntimeError, match="failed to load"):
        registry.load_datasets(["hotpotqa"])


def test_load_datasets_skips_only_when_asked(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(registry, "get_dataset", boom)

    assert registry.load_datasets(["hotpotqa"], skip_failures=True) == []
