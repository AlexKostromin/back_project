#!/usr/bin/env python
"""One-shot: create the ``court_decisions`` ES index if it doesn't exist.

Intended to run once per environment during setup — the same way
``alembic upgrade head`` is run once to create the Postgres schema.
In dev: call it after ``docker compose up -d elasticsearch``. In CI:
called before the test suite. In prod: part of the deploy job.

Exit codes:
    0 — index is now present (either just created or already existed)
    1 — anything else (unreachable ES, mapping conflict, etc.)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# When invoked as ``python scripts/ensure_es_index.py`` the project
# root is not on sys.path — prepend it so ``app.*`` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.es.client import get_es_client  # noqa: E402
from app.es.mapping import COURT_DECISIONS_INDEX, ensure_court_decisions_index  # noqa: E402


async def _run() -> int:
    es = get_es_client()
    try:
        created = await ensure_court_decisions_index(es)
    except Exception as exc:  # noqa: BLE001 — top-level CLI wants every reason
        print(f"✗ ensure_court_decisions_index failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await es.close()

    verb = "created" if created else "already exists"
    print(f"✓ index '{COURT_DECISIONS_INDEX}' {verb}")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
