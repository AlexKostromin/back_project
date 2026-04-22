from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from pydantic import ValidationError

from app.parsers.base import BaseParser
from app.parsers.exceptions import ParseError, SourceUnavailableError
from app.parsers.registry import parser_registry
from app.parsers.schemas import ParsedDecision, RawDecision


class FileParser(BaseParser):
    """Reference parser reading decisions from JSON fixtures."""

    source_key = "file"

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir.resolve()

        if not self.fixtures_dir.is_dir():
            raise ValueError(f"Fixtures directory does not exist: {self.fixtures_dir}")

    def _validate_path(self, filename: str) -> Path:
        """Validate that resolved path stays within fixtures_dir."""
        target = (self.fixtures_dir / filename).resolve()

        if not target.is_relative_to(self.fixtures_dir):
            raise ValueError(f"Path traversal detected: {filename}")

        return target

    async def fetch_list(
        self,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RawDecision]:
        """Iterate over JSON fixtures in directory."""
        json_files = sorted(self.fixtures_dir.glob("*.json"))[:limit]

        for json_path in json_files:
            async with aiofiles.open(json_path, mode="r", encoding="utf-8") as f:
                raw_content = await f.read()

            yield RawDecision(
                source=self.source_key,
                source_id=json_path.stem,
                url=None,
                raw_content=raw_content,
                fetched_at=datetime.now(timezone.utc),
            )

    async def fetch_document(self, source_id: str) -> RawDecision:
        """Fetch single JSON fixture by source_id."""
        file_path = self._validate_path(f"{source_id}.json")

        if not file_path.exists():
            raise SourceUnavailableError(f"Document not found: {source_id}")

        async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
            raw_content = await f.read()

        return RawDecision(
            source=self.source_key,
            source_id=source_id,
            url=None,
            raw_content=raw_content,
            fetched_at=datetime.now(timezone.utc),
        )

    async def parse(self, raw: RawDecision) -> ParsedDecision:
        """Parse JSON content into ParsedDecision."""
        try:
            data = json.loads(raw.raw_content)
            return ParsedDecision(
                **data,
                source=raw.source,
                source_id=raw.source_id,
                url=raw.url,
                fetched_at=raw.fetched_at,
                parsed_at=datetime.now(timezone.utc),
            )
        except (json.JSONDecodeError, ValidationError) as e:
            raise ParseError(f"Failed to parse document {raw.source_id}: {e}") from e


parser_registry.register(FileParser)
