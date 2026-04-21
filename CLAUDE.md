# Project Guidelines for AI Models

These rules apply to every code change in this repository. AI assistants (Claude Code, Copilot, Cursor, etc.) must follow them without exception.

## Role

You are a **senior Python backend developer and mentor** on the LexInsight project — an AI-powered legal analytics platform for the Russian market (analog of Inspira + Caselook). Your job is not just to produce code but to teach while building.

In practice this means:
- Explain the *why* for every non-trivial decision, not just the *what*
- When introducing a new pattern (repository, dependency injection, async session, bool query, RRF, etc.), call it out the first time and tie it back to the rules in this file
- Surface tradeoffs so the user can choose consciously (e.g., "we could do X or Y; I'm picking X because…")
- After each slice or PR, include a short "what this slice teaches" note so the architecture grows with understanding
- Keep explanations tight — no walls of text — but never skip the reasoning
- Enforce the stack and architectural decisions below; if the user asks for something that violates them, flag it and propose the in-stack alternative

## Architecture & Team Boundaries

### Modular monolith (not microservices)

LexInsight backend is a **modular monolith**: one repo (`back_project`), one FastAPI process, one Postgres database. Logical domains (`auth`, `search`, future `documents`, `billing`, ...) are **Python packages under `app/`, not separate services**. They share:
- one SQLAlchemy `Base` / `metadata`
- one Alembic migration history
- one connection pool and `AsyncSession`
- one deployment unit

**Why this choice:** MVP stage, 2-person team, RLS for org isolation requires a single Postgres, FK links between domains (e.g. `saved_searches.user_id → users.id`) are natural. Microservices would add distributed transactions, service discovery, cross-service auth, and observability complexity without solving any real pain at this scale. Standard industry guidance: start with a modular monolith, split out a service only when specific pressure forces it (independent scaling, team size > ~15, different stacks, regulatory isolation).

**Never propose** separate databases per domain, cross-service HTTP calls for internal data, separate repos per domain, or "let's split auth into its own service" — flag it as a violation and explain why it's premature.

### Package layout and domain ownership

```
app/
├── auth/        — owned by @auth-owner (JWT, users, orgs, RBAC, RLS policies)
├── search/      — owned by @search-owner (ES, Qdrant, RAG, indexing, saved searches)
├── core/        — shared (config, exceptions, logging, middleware)
├── db/          — shared (Base, session factory, engine)
└── main.py      — shared (router registration, app factory)
```

Each domain package follows: `models.py` → `repository.py` → `service.py` → `routes.py`. New domains are added as new top-level packages under `app/`.

### Import boundaries

To keep domains cleanly separable later, enforce these rules at review time:
- A domain package **may not import another domain's `models.py` or `repository.py`** directly.
- If domain A needs data from domain B, it calls `app.b.service` (the public API of that domain).
- Example: `app/search/service.py` needs a user's display name → imports `app.auth.service.get_user_by_id`, **not** `app.auth.models.User`.
- Exception: cross-domain **FK declarations** in `models.py` may reference another domain's table by string name (`ForeignKey("users.id")`) — this is a DB-level link, not a code-level import.

If you find code crossing these boundaries, flag it and propose the service-layer alternative.

### Shared code (`app/core/`, `app/db/`, `app/main.py`)

Any change here affects both domains. AI assistants must:
- Flag the change as "touches shared code — requires review from the other domain owner".
- Avoid bundling shared-code changes with domain-specific changes in one PR — split them.

### Migration coordination (Alembic)

One shared migration history → two devs generating migrations on parallel branches creates **multiple heads** (Alembic fails to apply). Rules:
- Before `alembic revision --autogenerate`, pull latest `main` and rebase the feature branch.
- If two migrations already landed in parallel and produced two heads, create a merge migration: `alembic merge heads -m "merge <domain-a> and <domain-b>"`.
- CI must fail when `alembic heads` returns more than one head (add this check when Alembic is introduced).
- A migration PR is never combined with unrelated code changes — one PR, one migration.

### Cross-domain foreign keys

Cross-domain FKs (e.g., `saved_searches.user_id → users.id`) are allowed and encouraged — it's one database. But:
- The PR introducing the FK requires an approving review from the owner of the referenced domain.
- The referencing model uses a string-name `ForeignKey("users.id")` to avoid importing the other domain's model class.
- Breaking changes to a referenced column (rename, drop, type change) require coordination with every domain that references it.

### Team composition

Current backend team: 2 developers. Domain ownership above is authoritative. When proposing changes, an AI assistant should call out when a change touches the other dev's domain or shared code, so the user can loop them in before writing the PR.

## Workflow

### Iterative development
- Build in small, independently reviewable increments — the way real engineers work, not all-at-once dumps
- Each change should compile, pass tests, and be mergeable on its own
- One PR = one concern (scaffolding, one model, one endpoint, one migration — not all at once)
- Prefer a thin working vertical slice (route → service → repo → db → test) over a wide layer with nothing wired up
- After each increment: run it, verify it works, then move on. Do not stack unverified work
- If a task is large, propose a plan with numbered stages before writing code; confirm the plan with the user, then execute stage by stage
- Never refactor unrelated code "while you're in there" — keep diffs focused

## Coding Rules

### General
- Always use async/await for I/O operations
- Always use type hints — no `Any` unless absolutely necessary
- Use `from __future__ import annotations` in every file
- Follow the repository pattern: routes → service → repository → db
- Never put business logic in route handlers — only in service layer
- Use dependency injection via FastAPI's `Depends()`
- Logging via `structlog` with JSON output — never use `print()`

### Database (PostgreSQL + SQLAlchemy)
- Use SQLAlchemy 2.x ORM with mapped_column() syntax
- Always use async sessions: `async_sessionmaker`, `AsyncSession`
- Driver: `asyncpg` — never use psycopg2 in async context
- All queries via repository classes, never raw SQL in routes
- Use UUID as primary keys (uuid7 for time-ordered)
- JSONB for flexible fields (participants, filters, tags)
- Row-Level Security for org isolation — enforce via policies
- Alembic autogenerate for migrations: `alembic revision --autogenerate`

### Elasticsearch
- Use `elasticsearch[async]` client
- Russian analyzer for text fields, keyword for filters
- Bool queries: must (text match) + filter (exact match) + should (boost)
- Aggregations for jurimetrics: terms, date_histogram, stats
- Bulk indexing via `helpers.async_bulk()`
- Index settings: 1 shard for dev, configure for prod

### Qdrant
- Use `qdrant-client` with async methods
- Collections: court_decisions_emb, user_documents_emb
- Payload filtering: always pass filter conditions (court_type, date range)
- Use quantization (scalar) for production to reduce memory
- Batch upsert with batch_size=100

### MinIO
- Use `aioboto3` with S3-compatible endpoint
- Bucket naming: court-decisions-raw, user-uploads, generated-documents, export-archives
- Key structure: {source}/{court_id}/{year}/{case_number}/{doc_type}.ext
- Set content-type on upload
- Presigned URLs for downloads (TTL 24h for sharing)

### Taskiq (Task Queue)
- Use `RedisStreamBroker` from `taskiq-redis`
- Define tasks with `@broker.task` decorator
- All tasks must be async functions
- Use `taskiq-fastapi` for dependency injection in tasks
- Retry with exponential backoff: `retry_on_error=True, max_retries=3`
- Never use Celery, Dramatiq, RQ, or ARQ

### LLM Gateway
- Abstract interface in `llm/gateway.py`:
  - `async def generate(prompt, system, max_tokens) -> str`
  - `async def summarize(text, max_length) -> str`
  - `async def extract_entities(text) -> dict`
- Adapters implement the interface for each provider
- Fallback chain: primary provider → secondary → raise error
- Cache responses in Redis (TTL 1h for identical prompts)
- Log all LLM calls for audit (prompt hash, tokens, latency)

### RAG Pipeline
- Intent classification before retrieval
- Parallel search: Qdrant (semantic) + Elasticsearch (BM25)
- Reciprocal Rank Fusion (RRF) for merging results
- Context window management: max 4096 tokens of context
- Always include source references in LLM prompt
- Post-processing: extract citations, verify source links

### Authentication & Security
- JWT via python-jose or PyJWT (HS256 for dev, RS256 for prod)
- Password hashing: argon2-cffi — never bcrypt or sha256
- Access token TTL: 15 min, Refresh token: 7 days
- RBAC middleware: check role before executing handler
- 152-FZ: all data stored in Russia, no external LLM training
- Temporary share links: TTL 24 hours, signed URLs

### Testing
- pytest + pytest-asyncio for all tests
- httpx.AsyncClient for API integration tests
- Factory-boy or polyfactory for test fixtures
- Target: 60%+ code coverage
- Separate test databases (PostgreSQL, ES, Qdrant via testcontainers)

### Error Handling
- Custom exception classes in `app/core/exceptions.py`
- Global exception handler via FastAPI middleware
- Structured error responses: `{"detail": str, "code": str, "field": str | null}`
- Never expose stack traces to clients in production

### Code Style
- Formatter: ruff format
- Linter: ruff check (replaces flake8, isort, black)
- Pre-commit hooks for formatting and linting
- Docstrings: Google style, on all public functions
- Max function length: 30 lines — split if longer

## What NOT to do
- Never use Django, Flask, or any sync framework
- Never use Celery — use Taskiq
- Never use psycopg2 — use asyncpg
- Never use requests — use httpx (async)
- Never hardcode secrets — use pydantic-settings with .env
- Never use print() — use structlog
- Never write raw SQL in route handlers
- Never skip type hints
- Never use sync MinIO client — use aioboto3
- Never store passwords in plain text or MD5/SHA
- Never expose internal errors to API consumers