"""Persistent memory for Atlas — research findings, preferences, notes."""

from __future__ import annotations

from ..storage import Storage
from .base import ToolHandler


class MemoryReadHandler(ToolHandler):
    @property
    def name(self) -> str:
        return "memory_read"

    @property
    def description(self) -> str:
        return (
            "Read from your persistent memory. Use to recall research notes, "
            "preferences, past findings, or any context you previously saved. "
            "Categories: 'research' (research findings/journal), 'preferences' "
            "(user communication preferences), 'notes' (general notes/learnings)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Memory category to read",
                    "enum": ["research", "preferences", "notes", "all"],
                },
                "key": {
                    "type": "string",
                    "description": "Optional: specific key to read",
                },
                "search": {
                    "type": "string",
                    "description": "Optional: search term to filter memories",
                },
            },
            "required": ["category"],
        }

    def execute(self, args: dict, storage: Storage, **kwargs) -> dict:
        category = self.validate_enum(
            args.get("category"), ["research", "preferences", "notes", "all"], "all"
        )
        key = self.validate_string(args.get("key"), None, 100)
        search = self.validate_string(args.get("search"), None, 200)

        entries = storage.read_memory(category=category, key=key, search=search, limit=20)
        if key and not entries:
            return self.success_response(
                key=key, content=None, message=f"No memory found for key '{key}'"
            )

        if key:
            entry = entries[0]
            return self.success_response(
                key=entry.get("key", key),
                content=entry.get("content", ""),
                category=entry.get("category", category),
                updated_at=str(entry.get("updated_at", "")),
            )

        memories = [
            {
                "key": e.get("key", ""),
                "title": e.get("title", e.get("key", "")),
                "category": e.get("category", ""),
                "content": (e.get("content", "") or "")[:500],
                "updated_at": str(e.get("updated_at", "")),
            }
            for e in entries
        ]
        return self.success_response(
            category=category, count=len(memories), memories=memories
        )


class MemoryWriteHandler(ToolHandler):
    @property
    def name(self) -> str:
        return "memory_write"

    @property
    def description(self) -> str:
        return (
            "Save something to your persistent memory. Use to remember research "
            "findings, user preferences, key decisions, or anything you want to "
            "recall in future conversations."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Memory category",
                    "enum": ["research", "preferences", "notes"],
                },
                "key": {
                    "type": "string",
                    "description": "Unique key (e.g. 'pricing_research_q3', 'user_preferences')",
                },
                "title": {"type": "string", "description": "Short title for this memory"},
                "content": {
                    "type": "string",
                    "description": "The content to remember (max 2000 chars)",
                },
            },
            "required": ["category", "key", "content"],
        }

    def execute(self, args: dict, storage: Storage, **kwargs) -> dict:
        category = self.validate_enum(
            args.get("category"), ["research", "preferences", "notes"], None
        )
        key = self.validate_string(args.get("key"), None, 100)
        title = self.validate_string(args.get("title"), "", 200) or ""
        content = self.validate_string(args.get("content"), None, 2000)

        if not category:
            return self.error_response("MISSING_PARAM", "category is required", retryable=False)
        if not key:
            return self.error_response("MISSING_PARAM", "key is required", retryable=False)
        if not content:
            return self.error_response("MISSING_PARAM", "content is required", retryable=False)

        storage.write_memory(category=category, key=key, title=title, content=content)
        return self.success_response(
            key=f"{category}:{key}",
            message=f"Saved to memory: {title or key}",
        )
