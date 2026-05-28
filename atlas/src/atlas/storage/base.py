"""Storage interface for Atlas.

Atlas keeps two kinds of state:

- strategy_docs: versioned analytical artifacts (engagement_tracker, icp,
  competitive_landscape, executive_brief, etc.). These are the deliverables.
- memory: free-form notes and preferences keyed by category (research, notes,
  preferences). Persists across sessions.

Implement this interface to plug Atlas into a different backend (Firestore, S3,
Postgres, SQLite, etc.). The default LocalStorage writes JSON to disk and is
plenty for personal use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class Storage(ABC):
    """Pluggable storage backend for Atlas state."""

    # ----- strategy_docs -----

    @abstractmethod
    def read_doc(self, key: str) -> Optional[dict]:
        """Return the document with the given key, or None if not found.

        Shape: {"key", "content" (dict or str), "version", "title", "category",
        "summary", "confidence", "sources", "updated_at", "change_log"}.
        """

    @abstractmethod
    def write_doc(self, key: str, doc: dict) -> int:
        """Write a document. Returns the new version number (1 for first write,
        n+1 for updates). Implementations should archive the previous version
        if they support history."""

    @abstractmethod
    def list_docs(self, category: Optional[str] = None) -> list[dict]:
        """List all documents, optionally filtered by category. Each entry is a
        compact summary (no full content): {"key", "title", "category",
        "summary", "confidence", "version", "updated_at"}."""

    # ----- memory -----

    @abstractmethod
    def read_memory(
        self,
        category: str = "all",
        key: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Read memory entries. If `key` is provided, returns the matching one;
        otherwise returns up to `limit` entries, filtered by category and
        optional search term."""

    @abstractmethod
    def write_memory(self, category: str, key: str, title: str, content: str) -> None:
        """Save a memory entry. Overwrites if (category, key) already exists."""
