"""Strategy document CRUD — the deliverables Atlas builds."""

from __future__ import annotations

import json

from ..storage import Storage
from .base import ToolHandler


class StrategyReadHandler(ToolHandler):
    @property
    def name(self) -> str:
        return "strategy_read"

    @property
    def description(self) -> str:
        return (
            "Read a strategy document by key. Common keys: engagement_tracker, "
            "company_assessment, executive_brief, icp, competitive_landscape, "
            "battlecards, pricing_positioning, opportunity_map, market_trends, "
            "workplan."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Document key (e.g. 'icp')"},
            },
            "required": ["key"],
        }

    def execute(self, args: dict, storage: Storage, **kwargs) -> dict:
        key = self.validate_string(args.get("key"), None, 100)
        if not key:
            return self.error_response("MISSING_KEY", "key is required", retryable=False)
        doc = storage.read_doc(key)
        if doc is None:
            return self.error_response("NOT_FOUND", f"No strategy doc: {key}", retryable=False)
        return self.success_response(key=key, data=doc)


class StrategyWriteHandler(ToolHandler):
    @property
    def name(self) -> str:
        return "strategy_write"

    @property
    def description(self) -> str:
        return (
            "Write or update a strategy document. Auto-versions and keeps history. "
            "Include a sources array (URLs) for analysis or recommendations — the "
            "handler warns if an analysis doc is saved with zero sources."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Document key"},
                "title": {"type": "string", "description": "Human-readable title"},
                "category": {
                    "type": "string",
                    "enum": ["context", "analysis", "recommendations"],
                    "description": "Document category",
                },
                "content": {
                    "type": "string",
                    "description": "JSON content string (will be parsed) or free text",
                },
                "summary": {"type": "string", "description": "Brief summary of the document"},
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Confidence level in this analysis",
                },
                "confidence_note": {
                    "type": "string",
                    "description": "Explanation of confidence level",
                },
                "change_description": {
                    "type": "string",
                    "description": "What changed in this update",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source URLs backing the claims. Required for analysis/recommendations.",
                },
            },
            "required": ["key", "content"],
        }

    def execute(self, args: dict, storage: Storage, **kwargs) -> dict:
        key = self.validate_string(args.get("key"), None, 100)
        title = self.validate_string(args.get("title"), None, 200)
        category = self.validate_enum(
            args.get("category"), ["context", "analysis", "recommendations"], None
        )
        content_str = self.validate_string(args.get("content"), None, 500000)
        summary = self.validate_string(args.get("summary"), None, 1000)
        confidence = self.validate_enum(args.get("confidence"), ["high", "medium", "low"], None)
        confidence_note = self.validate_string(args.get("confidence_note"), None, 500)
        change_desc = self.validate_string(args.get("change_description"), None, 500)

        sources = args.get("sources")
        if sources and not isinstance(sources, list):
            sources = None

        if not key or not content_str:
            return self.error_response("MISSING_PARAMS", "key and content required", retryable=False)

        try:
            parsed_content = json.loads(content_str)
        except json.JSONDecodeError:
            parsed_content = content_str

        doc = {"content": parsed_content}
        if title:
            doc["title"] = title
        if category:
            doc["category"] = category
        if summary:
            doc["summary"] = summary
        if confidence:
            doc["confidence"] = confidence
        if confidence_note:
            doc["confidence_note"] = confidence_note
        if sources:
            doc["sources"] = sources
        if change_desc:
            doc["change_description"] = change_desc

        version = storage.write_doc(key, doc)

        source_count = len(sources) if sources else 0
        if isinstance(parsed_content, dict):
            embedded = parsed_content.get("sources", [])
            if isinstance(embedded, list):
                source_count += len(embedded)

        response = {
            "key": key,
            "version": version,
            "source_count": source_count,
            "message": f"Saved {key} v{version}",
        }
        if category in ("analysis", "recommendations") and source_count == 0:
            response["source_warning"] = (
                "No sources provided for this analysis document. Include a 'sources' "
                "array of URLs to ensure traceability and prevent hallucinated conclusions."
            )
        return self.success_response(**response)


class StrategyListHandler(ToolHandler):
    @property
    def name(self) -> str:
        return "strategy_list"

    @property
    def description(self) -> str:
        return "List all strategy documents, optionally filtered by category."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["context", "analysis", "recommendations"],
                    "description": "Optional category filter",
                }
            },
        }

    def execute(self, args: dict, storage: Storage, **kwargs) -> dict:
        category = self.validate_enum(
            args.get("category"), ["context", "analysis", "recommendations"], None
        )
        docs = storage.list_docs(category=category)
        return self.success_response(count=len(docs), documents=docs)
