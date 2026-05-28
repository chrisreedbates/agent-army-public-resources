"""Filesystem-backed storage. JSON files under a state directory.

Layout:
    <root>/
        docs/<key>.json              # current version
        docs/.history/<key>/v<n>.json # prior versions
        memory/<category>/<key>.json
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import Storage


_SAFE_KEY = re.compile(r"[^a-zA-Z0-9_.-]+")


def _safe(name: str) -> str:
    """Strip characters that would be unsafe as a filename."""
    cleaned = _SAFE_KEY.sub("_", name).strip("._")
    return cleaned or "unnamed"


class LocalStorage(Storage):
    """JSON-on-disk storage. The default backend for `atlas`."""

    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).expanduser().resolve()
        (self.root / "docs" / ".history").mkdir(parents=True, exist_ok=True)
        (self.root / "memory").mkdir(parents=True, exist_ok=True)

    # ----- strategy_docs -----

    def _doc_path(self, key: str) -> Path:
        return self.root / "docs" / f"{_safe(key)}.json"

    def read_doc(self, key: str) -> Optional[dict]:
        path = self._doc_path(key)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def write_doc(self, key: str, doc: dict) -> int:
        path = self._doc_path(key)
        version = 1
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                existing = json.load(f)
            version = int(existing.get("version", 1)) + 1
            # Archive previous version
            history_dir = self.root / "docs" / ".history" / _safe(key)
            history_dir.mkdir(parents=True, exist_ok=True)
            with (history_dir / f"v{existing.get('version', 1)}.json").open(
                "w", encoding="utf-8"
            ) as f:
                json.dump(existing, f, indent=2, default=str)

        doc = dict(doc)  # don't mutate caller's dict
        doc["key"] = key
        doc["version"] = version
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Append a change_log entry
        log = list(doc.get("change_log") or [])
        log.append({
            "version": version,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "change": doc.pop("change_description", "Updated"),
        })
        doc["change_log"] = log

        with path.open("w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, default=str)
        return version

    def list_docs(self, category: Optional[str] = None) -> list[dict]:
        docs_dir = self.root / "docs"
        if not docs_dir.exists():
            return []
        out: list[dict] = []
        for path in sorted(docs_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if category and data.get("category") != category:
                continue
            out.append({
                "key": data.get("key", path.stem),
                "title": data.get("title", ""),
                "category": data.get("category", ""),
                "summary": data.get("summary", ""),
                "confidence": data.get("confidence", ""),
                "version": data.get("version", 1),
                "updated_at": data.get("updated_at", ""),
            })
        return out

    # ----- memory -----

    def _memory_dir(self, category: str) -> Path:
        return self.root / "memory" / _safe(category)

    def read_memory(
        self,
        category: str = "all",
        key: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        if key:
            # Look up across categories or a specific one
            categories = [category] if category and category != "all" else self._list_memory_categories()
            for cat in categories:
                path = self._memory_dir(cat) / f"{_safe(key)}.json"
                if path.exists():
                    with path.open("r", encoding="utf-8") as f:
                        return [json.load(f)]
            return []

        results: list[dict] = []
        categories = [category] if category and category != "all" else self._list_memory_categories()
        for cat in categories:
            cat_dir = self._memory_dir(cat)
            if not cat_dir.exists():
                continue
            for path in cat_dir.glob("*.json"):
                with path.open("r", encoding="utf-8") as f:
                    results.append(json.load(f))

        if search:
            needle = search.lower()
            results = [
                r for r in results
                if needle in (r.get("content", "") or "").lower()
                or needle in (r.get("key", "") or "").lower()
                or needle in (r.get("title", "") or "").lower()
            ]

        results.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        return results[:limit]

    def write_memory(self, category: str, key: str, title: str, content: str) -> None:
        cat_dir = self._memory_dir(category)
        cat_dir.mkdir(parents=True, exist_ok=True)
        path = cat_dir / f"{_safe(key)}.json"
        now = datetime.now(timezone.utc).isoformat()
        existing = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                existing = json.load(f)
        entry = {
            "category": category,
            "key": key,
            "title": title or key,
            "content": content,
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2, default=str)

    def _list_memory_categories(self) -> list[str]:
        memory_root = self.root / "memory"
        if not memory_root.exists():
            return []
        return [p.name for p in memory_root.iterdir() if p.is_dir()]
