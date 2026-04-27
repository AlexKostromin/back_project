#!/usr/bin/env python
"""Backfill Elasticsearch from Postgres.

Default: picks up CourtDecision rows with ``es_indexed=False`` (the
secondary-write failure path from ingest), indexes them in ES, marks
them as indexed.

With ``--all``: re-indexes every row regardless of the flag. Useful
after a mapping change (via reindex-to-new-name in ES) or when the
index was dropped and recreated.

Dry-run: counts what would happen, no writes.

Exit codes:
    0 — backfill finished (0 or more docs indexed)
    1 — any failure (DB unreachable, ES unreachable, bulk errors)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# When invoked as ``python scripts/reindex_es.py`` the project root is
# not on sys.path — prepend it so ``app.*`` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog  # noqa: E402
from elasticsearch.helpers import async_bulk  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.es.client import get_es_client  # noqa: E402
from app.modules.search.repositories.court_decision import (  # noqa: E402
    CourtDecisionRepository,
)
from app.modules.search.services.es_document import serialize_decision  # noqa: E402

log = structlog.get_logger(__name__)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    index_name = settings.es_court_decisions_index
    sessionmaker = get_sessionmaker()
    es = get_es_client()

    total_indexed = 0
    total_errors = 0

    try:
        async with sessionmaker() as session:
            repo = CourtDecisionRepository(session)
            source = repo.iter_all if args.all else repo.iter_unindexed

            async for batch in source(batch_size=args.batch_size):
                if not batch:
                    continue

                if args.dry_run:
                    print(
                        f"[dry-run] would index {len(batch)} docs "
                        f"(first id={batch[0].id}, last id={batch[-1].id})"
                    )
                    total_indexed += len(batch)
                    continue

                actions = [
                    {
                        "_op_type": "index",
                        "_index": index_name,
                        "_id": str(d.id),
                        "_source": serialize_decision(d),
                    }
                    for d in batch
                ]
                ok, errors = await async_bulk(
                    es,
                    actions,
                    raise_on_error=False,
                    refresh=False,  # bulk: let ES refresh on its own cadence
                )
                total_indexed += ok
                batch_errors = len(errors) if isinstance(errors, list) else 0
                total_errors += batch_errors
                if batch_errors:
                    log.warning("reindex.bulk_errors", count=batch_errors)

                if not args.all:
                    # Only in the unindexed-backfill path: flip the flag
                    # so the next run won't pick these up again. In --all
                    # mode we're rebuilding the whole index, so the flag
                    # state in PG is irrelevant to the run.
                    await repo.mark_indexed([d.id for d in batch])
                    await session.commit()

                print(
                    f"✓ batch: {ok}/{len(batch)} indexed, "
                    f"{batch_errors} errors"
                )
    except Exception as exc:  # noqa: BLE001 — top-level CLI wants every reason
        print(f"✗ reindex failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await es.close()

    print(f"✓ done: {total_indexed} indexed, {total_errors} errors")
    return 1 if total_errors else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill ES from Postgres.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Reindex every row (not only es_indexed=False). "
            "Use after a mapping change."
        ),
    )
    return parser.parse_args()


def main() -> None:
    sys.exit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
