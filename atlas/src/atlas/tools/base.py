"""Base class for tool handlers.

A tool handler exposes:
- A name and description (what the LLM sees in its tool list)
- A JSON Schema for its input
- An `execute(args, storage)` method that returns a dict
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..storage import Storage


class ToolHandler(ABC):
    """Abstract base class for all tool handlers."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for tool inputs."""

    @abstractmethod
    def execute(self, args: dict, storage: Storage, **kwargs) -> dict:
        """Run the tool. Return a dict with `ok: bool` and either result fields
        or an `error` key (use `error_response`)."""

    def to_anthropic_tool(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    # ----- input validation helpers -----

    @staticmethod
    def validate_string(value: Any, default: Optional[str], max_length: int = 1000) -> Optional[str]:
        if value is None:
            return default
        return str(value)[:max_length]

    @staticmethod
    def validate_int(value: Any, default: int, min_val: int, max_val: int) -> int:
        if value is None:
            return default
        try:
            return max(min_val, min(max_val, int(value)))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def validate_enum(value: Any, allowed: list, default: Optional[str]) -> Optional[str]:
        if value is None:
            return default
        return value if value in allowed else default

    @staticmethod
    def error_response(code: str, message: str, retryable: bool = True) -> dict:
        return {
            "ok": False,
            "error": {"code": code, "message": message[:300], "retryable": retryable},
        }

    @staticmethod
    def success_response(**kwargs) -> dict:
        return {"ok": True, **kwargs}
