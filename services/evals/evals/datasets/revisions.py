"""Pinned HuggingFace dataset revisions.

Loading `load_dataset(repo_id)` without a `revision=` resolves whatever the
default branch currently points to — an eval run today and the "same" run
next quarter can silently see different upstream data (rows added/removed/
relabeled). Pinning to an immutable commit SHA makes runs reproducible and
makes the cache fingerprint (see registry.py) meaningful: a cache built
against one snapshot is never confused with a cache built against another.

To refresh a SHA after a deliberate upgrade to a newer snapshot, run this
from a machine with network access to huggingface.co:

    uv run python -c "from huggingface_hub import dataset_info; print(dataset_info('<repo_id>').sha)"

For a ref other than the default branch (qasper below pins the `parquet`
conversion branch, not `main`, because the loader needs the parquet layout):

    uv run python -c "from huggingface_hub import dataset_info; print(dataset_info('<repo_id>', revision='refs/convert/parquet').sha)"
"""

# repo_id -> immutable commit SHA. A None value means "unpinned" (today's
# default HF-resolves-the-ref-itself behaviour) — used only when a SHA could
# not be resolved (e.g. no network access) and must be filled in later.
HF_REVISIONS: dict[str, str | None] = {
    "hotpotqa/hotpot_qa": "1908d6afbbead072334abe2965f91bd2709910ab",
    "microsoft/ms_marco": "a47ee7aae8d7d466ba15f9f0bfac3b3681087b3a",
    "rajpurkar/squad_v2": "3ffb306f725f7d2ce8394bc1873b24868140c412",
    "galileo-ai/ragbench": "97808f3e5fd16ede40bbff6c2949af8139b2eb7b",
    # Pinned to the `refs/convert/parquet` conversion branch's commit, not
    # `main` — the loader depends on the parquet layout, whose sha differs
    # from the source-format main branch.
    "allenai/qasper": "06806e4608976fc2fac0a090ac425d5b2b29caf4",
}
