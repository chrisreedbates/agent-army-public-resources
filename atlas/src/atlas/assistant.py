"""The Atlas chat assistant.

Holds a Storage + Config, exposes a tool registry to Claude, and runs the
conversation loop. State (strategy docs + memory) persists between sessions
via Storage.

Two ways to use:

    # 1. One-shot
    a = Assistant.from_env()
    reply = a.chat("Should I expand into the LATAM market?")

    # 2. Multi-turn (you manage the history)
    a = Assistant.from_env()
    history = []
    while True:
        text = input("> ")
        result = a.chat(text, history=history)
        history = result["history"]
        print(result["text"])
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from anthropic import Anthropic

from .config import Config, default_config
from .prompts.builder import PromptBuilder
from .storage import LocalStorage, Storage
from .tools import default_handlers
from .tools.base import ToolHandler


_START_RESEARCH_TOOL = {
    "name": "start_research",
    "description": (
        "Kick off a full multi-worker research cycle for a complex strategic "
        "question. The orchestrator does MECE disaggregation, dispatches parallel "
        "research workers, applies quality gates, and saves deliverables to "
        "strategy docs. Use for big questions (sizing a market, mapping a "
        "competitive landscape, building an ICP from scratch). Cheaper, single-shot "
        "questions should use web_search + fetch_url directly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "problem_statement": {
                "type": "string",
                "description": "The strategic question to research (be specific).",
            },
        },
        "required": ["problem_statement"],
    },
}


class Assistant:
    """The Atlas chat assistant."""

    def __init__(
        self,
        storage: Storage,
        config: Optional[Config] = None,
        extra_tools: Optional[list[ToolHandler]] = None,
    ):
        self.config = config or default_config()
        if not self.config.anthropic_api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required. Set it in your environment or pass "
                "Config(anthropic_api_key=...)."
            )
        self.storage = storage
        self.client = Anthropic(api_key=self.config.anthropic_api_key, max_retries=0)
        self.prompt_builder = PromptBuilder(owner=self.config.owner_name)

        handlers = default_handlers()
        if extra_tools:
            handlers.extend(extra_tools)
        self._handlers: dict[str, ToolHandler] = {h.name: h for h in handlers}

        self._tools = [h.to_anthropic_tool() for h in handlers] + [_START_RESEARCH_TOOL]

    # ----- construction helpers -----

    @classmethod
    def from_env(cls, state_dir: Optional[str] = None) -> "Assistant":
        """Build an Assistant from env vars + LocalStorage."""
        config = Config.from_env()
        if state_dir:
            config.state_dir = state_dir
        storage = LocalStorage(config.state_dir)
        return cls(storage, config)

    # ----- engagement state -----

    def project_state(self) -> str:
        """Render a compact engagement dashboard from the saved tracker. Loaded
        into the system prompt at the start of each chat call so Atlas orients
        itself without burning tool turns."""
        tracker = self.storage.read_doc("engagement_tracker")
        if not tracker:
            return (
                "No engagement tracker found. After processing the first piece of "
                "information, create one using strategy_write(key=\"engagement_tracker\") "
                "with deliverable statuses, data_inventory, key_metrics, and next priorities."
            )

        content = tracker.get("content", {})
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                content = {}

        lines = ["ENGAGEMENT DASHBOARD:"]
        key_metrics = content.get("key_metrics", {})
        if key_metrics:
            parts = [f"{k}={v}" for k, v in key_metrics.items()]
            lines.append(f"  KEY METRICS: {', '.join(parts)}")
        deliverables = content.get("deliverables", {})
        if deliverables:
            lines.append("  DELIVERABLES:")
            for key, status in deliverables.items():
                lines.append(f"    {key}: {status}")
        data_inv = content.get("data_inventory", {})
        provided = data_inv.get("provided", [])
        needed = data_inv.get("needed", [])
        if provided:
            lines.append(f"  DATA ON FILE: {', '.join(str(p)[:60] for p in provided[:10])}")
        if needed:
            lines.append(f"  DATA NEEDED: {', '.join(str(n)[:60] for n in needed[:10])}")
        focus = content.get("current_focus", "")
        if focus:
            lines.append(f"  FOCUS: {focus}")
        blockers = content.get("blockers", [])
        if blockers:
            if isinstance(blockers, list):
                lines.append(f"  BLOCKERS: {'; '.join(str(b) for b in blockers)}")
            else:
                lines.append(f"  BLOCKERS: {blockers}")
        notes = content.get("last_session_notes", "")
        if notes:
            lines.append(f"  LAST SESSION: {str(notes)[:300]}")
        lines.append(
            "\nUse strategy_read(\"engagement_tracker\") for full details. "
            "Use strategy_read(\"<key>\") to load any deliverable. "
            "Use strategy_list() to see all documents."
        )
        return "\n".join(lines)

    # ----- chat loop -----

    def _execute_tool(self, name: str, args: dict, on_status: Optional[Callable[[str], None]] = None) -> str:
        if name == "start_research":
            return self._start_research(args.get("problem_statement", ""), on_status)
        if name in self._handlers:
            try:
                result = self._handlers[name].execute(args, self.storage)
                return json.dumps(result, default=str)
            except Exception as e:
                return json.dumps({"ok": False, "error": {"code": "TOOL_ERROR", "message": str(e)}})
        return json.dumps({"ok": False, "error": {"code": "UNKNOWN_TOOL", "message": name}})

    def _start_research(self, problem_statement: str, on_status: Optional[Callable[[str], None]]) -> str:
        from .research.orchestrator import ResearchOrchestrator
        try:
            orch = ResearchOrchestrator(self.storage, self.config, on_status=on_status)
            ctx_doc = self.storage.read_doc("company_assessment")
            business_context = ""
            if ctx_doc:
                content = ctx_doc.get("content", {})
                business_context = json.dumps(content, indent=2, default=str)
            result = orch.run(problem_statement, business_context)
            return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def chat(
        self,
        user_message: str,
        history: Optional[list[dict]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, dict], None]] = None,
    ) -> dict[str, Any]:
        """Process one user message. Returns:
            {"text": str, "history": list[dict], "turns_used": int}

        If you pass `history`, the returned `history` includes both the
        new user message and the assistant's response — pass it back next turn.
        """
        on_status = on_status or (lambda _msg: None)
        on_tool_call = on_tool_call or (lambda _n, _a: None)

        messages = list(history or [])
        messages.append({"role": "user", "content": user_message})

        system_prompt = self.prompt_builder.build_chat(project_state=self.project_state())

        for turn in range(self.config.max_turns):
            try:
                response = self.client.messages.create(
                    model=self.config.chat_model,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=self._tools,
                    messages=messages,
                )
            except Exception as e:
                return {
                    "text": f"API error: {e}",
                    "history": messages,
                    "turns_used": turn + 1,
                }

            if response.stop_reason == "end_turn":
                text = "".join(b.text for b in response.content if hasattr(b, "text"))
                messages.append({"role": "assistant", "content": response.content})
                return {"text": text, "history": messages, "turns_used": turn + 1}

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    on_tool_call(block.name, block.input)
                    result_str = self._execute_tool(block.name, block.input, on_status)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

            if tool_results:
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                # Stopped but no tool calls and no end_turn — bail to avoid infinite loop.
                text = "".join(b.text for b in response.content if hasattr(b, "text"))
                messages.append({"role": "assistant", "content": response.content})
                return {"text": text, "history": messages, "turns_used": turn + 1}

        return {
            "text": "Reached the max turn limit for this conversation. Continue with a new message.",
            "history": messages,
            "turns_used": self.config.max_turns,
        }
