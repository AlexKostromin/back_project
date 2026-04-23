# Seed fixtures — court decisions

Twelve `RawDecision` JSON documents that cover the filter space of the search API: arbitrazh + general-jurisdiction courts, first + appeal instances, Moscow / SPb / Ekaterinburg / Novosibirsk / Kazan / Rostov / Krasnodar, `satisfied` / `partial` / `denied`, civil / admin / bankruptcy disputes, claim amounts from 380K to 8.75M RUB, and a mix of one- and three-judge panels.

The texts are **fabricated for demo purposes** — plausible structure, real article numbers, no personal data. They are meant for local filter demos and ES full-text smoke tests, not real data analysis.

## Usage

```bash
docker compose up -d postgres
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app &
python scripts/seed_decisions.py
```

The script posts every file to `POST /api/v1/search/ingest/decision`. Re-runs are idempotent — the second run reports every fixture as `status=duplicate` because the processor dedups by SHA-256 of `full_text`.

## Adding more

Drop another `NN_<slug>.json` in this directory. Filenames are sorted, so prefix with a two-digit index to keep ordering stable. Every file must be a valid `RawDecision` (strict schema, `extra="forbid"`) — the ingest endpoint rejects drift as 422.
