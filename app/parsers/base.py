from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import date
from typing import ClassVar

import structlog

from app.parsers.schemas import ParsedDecision, RawDocument

logger = structlog.get_logger()


class BaseParser(ABC):
    """Abstract base class for court decision parsers."""

    source_key: ClassVar[str]

    @abstractmethod
    async def crawl(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[RawDocument]:
        """Iterate over documents from source within date range."""
        ...

    @abstractmethod
    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch single raw document by source id."""
        ...

    @abstractmethod
    async def parse(self, raw: RawDocument) -> ParsedDecision:
        """Parse raw document into structured format."""
        ...

    async def health_check(self) -> bool:
        """Check if the parser source is healthy and accessible.

        Default implementation always returns True.
        Subclasses should override when meaningful health checks are available.
        """
        return True

    async def get_pdf(self, source_id: str) -> bytes | None:
        """Retrieve PDF bytes for a document if available.

        Default implementation returns None.
        Subclasses should override if the source provides PDFs.
        """
        return None

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
