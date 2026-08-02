"""
Find and optionally delete ChromaDB vectors whose owning document no longer
exists in Postgres.

Before docs/suggestions.md #4.1 was fixed, document deletion never cleaned up
ChromaDB — every document deleted before that fix left orphaned, retrievable
vectors behind. This script finds and removes them.

Usage (inside the rag-server container, which has DB + ChromaDB network access):
    uv run python scripts/reconcile_vectors.py            # dry run, reports counts
    uv run python scripts/reconcile_vectors.py --apply     # actually deletes orphans

Invoked via `just reconcile-vectors` / `just reconcile-vectors-apply`.
"""

import argparse
import asyncio
import sys

from sqlalchemy import text

from infrastructure.database.postgres import get_session
from infrastructure.search.vector_store import (
    delete_document_vectors,
    list_chroma_document_ids,
)


async def _postgres_document_ids() -> set[str]:
    async with get_session() as session:
        result = await session.execute(text("SELECT id FROM public.documents"))
        return {str(row[0]) for row in result.all()}


async def reconcile(apply: bool) -> int:
    postgres_ids = await _postgres_document_ids()
    chroma_ids = list_chroma_document_ids()
    orphans = chroma_ids - postgres_ids

    print(f"Postgres documents: {len(postgres_ids)}")
    print(f"Chroma document_ids: {len(chroma_ids)}")
    print(f"Orphaned (in Chroma, not in Postgres): {len(orphans)}")

    if not orphans:
        print("Nothing to reconcile.")
        return 0

    for doc_id in sorted(orphans):
        print(f"  orphan: {doc_id}")

    if not apply:
        print("\nDry run — no vectors deleted. Re-run with --apply to delete these.")
        return 0

    print(f"\nDeleting vectors for {len(orphans)} orphaned document(s)...")
    for doc_id in sorted(orphans):
        delete_document_vectors(doc_id)
    print("Done.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete orphaned vectors (default: dry run, report only)",
    )
    args = parser.parse_args()
    return asyncio.run(reconcile(apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
