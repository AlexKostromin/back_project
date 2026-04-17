# Project Guidelines for AI Models

These rules apply to every code change in this repository. AI assistants (Claude Code, Copilot, Cursor, etc.) must follow them without exception.

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