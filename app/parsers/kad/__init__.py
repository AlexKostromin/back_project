from __future__ import annotations

from app.parsers.kad.parser import KadArbitrParser
from app.parsers.registry import parser_registry

parser_registry.register(KadArbitrParser)

__all__ = ["KadArbitrParser"]
