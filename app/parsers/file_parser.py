from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from hashlib import sha256
from itertools import islice
from pathlib import Path

import aiofiles
import structlog
from pydantic import ValidationError

from app.parsers.base import BaseParser
from app.parsers.exceptions import ParseError, SourceUnavailableError
from app.parsers.registry import parser_registry
from app.parsers.schemas import ParsedDecision, RawDocument

logger = structlog.get_logger(__name__)

MAX_JSON_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


class FileParser(BaseParser):
    """Reference parser reading decisions from JSON fixtures."""

    source_key = "file"

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir.resolve()

        if not self.fixtures_dir.is_dir():
            raise ValueError(f"Fixtures directory does not exist: {self.fixtures_dir}")

    def _validate_path(self, filename: str) -> Path:
        """Validate that resolved path stays within fixtures_dir."""
        if "\x00" in filename:
            raise ValueError(f"Null byte in filename: {filename!r}")
        stem = Path(filename).stem.upper()
        if stem in _WINDOWS_RESERVED_NAMES:
            raise ValueError(f"Reserved Windows filename: {filename}")

        target = (self.fixtures_dir / filename).resolve()

        if not target.is_relative_to(self.fixtures_dir):
            raise ValueError(f"Path traversal detected: {filename}")

        return target

    async def crawl(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[RawDocument]:
        """Iterate over JSON fixtures in directory."""
        json_files = sorted(self.fixtures_dir.glob("*.json"))
        if limit is not None:
            json_files = list(islice(json_files, limit))

        for json_path in json_files:
            async with aiofiles.open(json_path, mode="r", encoding="utf-8") as f:
                raw_content = await f.read()

            yield RawDocument(
                source_name=self.source_key,
                source_id=json_path.stem,
                html=raw_content,
                pdf_bytes=None,
                url=None,
                crawled_at=datetime.now(timezone.utc),
            )

    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch single JSON fixture by source_id."""
        file_path = self._validate_path(f"{source_id}.json")

        if not file_path.exists():
            raise SourceUnavailableError(f"Document not found: {source_id}")

        async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
            raw_content = await f.read()

        return RawDocument(
            source_name=self.source_key,
            source_id=source_id,
            html=raw_content,
            pdf_bytes=None,
            url=None,
            crawled_at=datetime.now(timezone.utc),
        )

    async def parse(self, raw: RawDocument) -> ParsedDecision:
        """Parse JSON content into ParsedDecision."""
        try:
            if raw.html is None:
                raise ParseError(f"No HTML content in raw document {raw.source_id}")

            # Check size limit before parsing
            size_bytes = len(raw.html.encode("utf-8"))
            if size_bytes > MAX_JSON_SIZE_BYTES:
                logger.warning(
                    "parser.parse.size_limit_exceeded",
                    source_id=raw.source_id,
                    size_bytes=size_bytes,
                )
                raise ParseError(f"Document too large: {raw.source_id}")

            data = json.loads(raw.html)

            # Compute text_hash from full_text if not provided
            full_text = data.get("full_text", "")
            text_hash = sha256(full_text.encode("utf-8")).hexdigest()

            # Build source_url: use raw.url if available, otherwise construct file:// URL
            source_url = raw.url or f"file://{self.fixtures_dir / raw.source_id}.json"

            return ParsedDecision(
                **data,
                source_name=self.source_key,
                source_id=raw.source_id,
                text_hash=text_hash,
                source_url=source_url,
                crawled_at=raw.crawled_at,
                parsed_at=datetime.now(timezone.utc),
            )
        except json.JSONDecodeError as e:
            logger.warning("parser.parse.json_failed", source_id=raw.source_id, error=str(e))
            raise ParseError(f"Failed to parse document {raw.source_id}") from e
        except ValidationError as e:
            logger.warning("parser.parse.validation_failed", source_id=raw.source_id, errors=e.errors())
            raise ParseError(f"Failed to parse document {raw.source_id}") from e


parser_registry.register(FileParser)
