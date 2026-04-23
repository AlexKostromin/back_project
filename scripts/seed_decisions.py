#!/usr/bin/env python
"""Seed script: post every JSON fixture from scripts/seed/ into the local
ingest endpoint so the search API has real-looking data to filter against.

Usage:
    python scripts/seed_decisions.py
    python scripts/seed_decisions.py --api-url http://localhost:8000
    python scripts/seed_decisions.py --fixtures-dir scripts/seed

Each fixture is a single RawDecision JSON document. Duplicates (same
full_text) are tolerated — the ingest endpoint returns status=duplicate
and the script logs them but does not treat them as failures. Missing
required fields or enum drift fail fast with the server's 422 body.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

DEFAULT_API = "http://localhost:8000"
DEFAULT_DIR = Path(__file__).parent / "seed"
INGEST_PATH = "/api/v1/search/ingest/decision"


async def _post_one(
    client: httpx.AsyncClient, fixture: Path
) -> tuple[str, dict | None, str | None]:
    """Return (fixture name, response body, error message)."""

    try:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fixture.name, None, f"invalid JSON: {exc}"

    try:
        response = await client.post(INGEST_PATH, json=payload)
    except httpx.HTTPError as exc:
        return fixture.name, None, f"network error: {exc}"

    if response.status_code >= 400:
        return fixture.name, None, f"HTTP {response.status_code}: {response.text}"

    return fixture.name, response.json(), None


async def _run(api_url: str, fixtures_dir: Path) -> int:
    fixtures = sorted(fixtures_dir.glob("*.json"))
    if not fixtures:
        print(f"no fixtures under {fixtures_dir}", file=sys.stderr)
        return 1

    created = duplicate = failed = 0

    async with httpx.AsyncClient(base_url=api_url, timeout=30.0) as client:
        for fixture in fixtures:
            name, body, error = await _post_one(client, fixture)
            if error:
                failed += 1
                print(f"✗ {name}: {error}", file=sys.stderr)
                continue

            status = body["status"] if body else "unknown"
            decision_id = body.get("decision_id") if body else None
            if status == "created":
                created += 1
            elif status == "duplicate":
                duplicate += 1
            print(f"{'+' if status == 'created' else '='} {name}: {status} (id={decision_id})")

    print(
        f"\ndone: created={created} duplicate={duplicate} failed={failed} "
        f"total={len(fixtures)}"
    )
    return 0 if failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=DEFAULT_DIR,
        help="directory of *.json RawDecision fixtures",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(_run(args.api_url, args.fixtures_dir))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
