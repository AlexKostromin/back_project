from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import ClassVar

import structlog

from app.parsers.schemas import ParsedDecision, RawDecision

logger = structlog.get_logger()


class BaseParser(ABC):
    """Abstract base class for court decision parsers."""

    source_key: ClassVar[str]

    @abstractmethod
    async def fetch_list(
        self,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RawDecision]:
        """Iterate over decisions from source, starting from since date."""
        ...

    @abstractmethod
    async def fetch_document(self, source_id: str) -> RawDecision:
        """Fetch single raw document by source id."""
        ...

    @abstractmethod
    async def parse(self, raw: RawDecision) -> ParsedDecision:
        """Parse raw decision into structured format."""
        ...

    async def fetch_and_parse(self, source_id: str) -> ParsedDecision:
        """Fetch and parse a document in one call."""
        start = time.monotonic()
        logger.info(
            "parser.fetch_and_parse.start",
            source=self.source_key,
            source_id=source_id,
        )

        raw = await self.fetch_document(source_id)
        parsed = await self.parse(raw)

        elapsed = time.monotonic() - start
        logger.info(
            "parser.fetch_and_parse.complete",
            source=self.source_key,
            source_id=source_id,
            latency_ms=round(elapsed * 1000, 2),
        )

        return parsed
