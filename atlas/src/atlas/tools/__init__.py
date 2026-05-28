"""Tool registry. The handlers here are the only things the LLM can call."""

from __future__ import annotations

from .base import ToolHandler
from .memory import MemoryReadHandler, MemoryWriteHandler
from .strategy import StrategyListHandler, StrategyReadHandler, StrategyWriteHandler
from .web import FetchUrlHandler, WebSearchHandler


def default_handlers() -> list[ToolHandler]:
    """Handlers always available in chat mode (research adds `start_research`)."""
    return [
        StrategyReadHandler(),
        StrategyWriteHandler(),
        StrategyListHandler(),
        MemoryReadHandler(),
        MemoryWriteHandler(),
        WebSearchHandler(),
        FetchUrlHandler(),
    ]


__all__ = [
    "ToolHandler",
    "StrategyReadHandler",
    "StrategyWriteHandler",
    "StrategyListHandler",
    "MemoryReadHandler",
    "MemoryWriteHandler",
    "WebSearchHandler",
    "FetchUrlHandler",
    "default_handlers",
]
