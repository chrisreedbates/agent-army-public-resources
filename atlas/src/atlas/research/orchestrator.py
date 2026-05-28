"""Research orchestrator — Bulletproof Problem Solving with quality gates.

The orchestrator is a Claude loop that thinks at the engagement-manager level:
1. Define the problem
2. Disaggregate (MECE)
3. Prioritize
4. Workplan — dispatch parallel research workers
5. Critical analysis — evaluate against quality thresholds, dispatch follow-ups
6. Synthesize via the Pyramid Principle
7. Save deliverables via strategy_write

Up to 3 research rounds. Per-task quality thresholds: 3+ sources, ≤50% gap ratio,
≤40% low-confidence claims.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from anthropic import Anthropic

from ..config import Config, default_config
from ..prompts.builder import PromptBuilder
from ..storage import Storage
from ..tools.strategy import StrategyReadHandler, StrategyWriteHandler
from .worker import run_research_worker


QUALITY_THRESHOLDS = {
    "min_sources_per_task": 3,
    "max_gap_ratio": 0.5,
    "max_low_confidence_ratio": 0.4,
}


_DISPATCH_RESEARCH_TOOL = {
    "name": "dispatch_research",
    "description": (
        "Send research tasks to analyst workers who search the web, read websites, "
        "and return structured findings. Tasks run in parallel. Workers use "
        "multi-hop research (Perplexity scan + Claude deep-dive) when available."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Short task identifier"},
                        "brief": {"type": "string", "description": "Detailed research instructions"},
                        "deep": {
                            "type": "boolean",
                            "description": "Enable multi-hop deep-dive (default true).",
                            "default": True,
                        },
                    },
                    "required": ["id", "brief"],
                },
                "description": "List of research tasks to execute in parallel",
            }
        },
        "required": ["tasks"],
    },
}


def _evaluate_quality(results: dict) -> dict:
    total_tasks = len(results)
    if total_tasks == 0:
        return {"pass": False, "reason": "No results", "follow_up_needed": []}

    tasks_with_gaps = 0
    total_findings = 0
    low_conf = 0
    thin_tasks: list[dict] = []
    all_gaps: list[str] = []

    for task_id, result in results.items():
        if not result.get("ok"):
            tasks_with_gaps += 1
            thin_tasks.append({"id": task_id, "reason": "Task failed"})
            continue
        findings = result.get("findings", {})
        gaps = findings.get("gaps", [])
        sources = findings.get("sources", [])
        claims = findings.get("findings", [])

        if gaps:
            tasks_with_gaps += 1
            all_gaps.extend(gaps)
        if len(sources) < QUALITY_THRESHOLDS["min_sources_per_task"]:
            thin_tasks.append({
                "id": task_id,
                "reason": f"Only {len(sources)} sources",
                "gaps": gaps,
            })
        for c in claims:
            if isinstance(c, dict):
                total_findings += 1
                if c.get("confidence") in ("low", "medium"):
                    low_conf += 1

    gap_ratio = tasks_with_gaps / total_tasks
    low_conf_ratio = low_conf / total_findings if total_findings else 0
    passed = (
        gap_ratio <= QUALITY_THRESHOLDS["max_gap_ratio"]
        and low_conf_ratio <= QUALITY_THRESHOLDS["max_low_confidence_ratio"]
        and not thin_tasks
    )
    report = {
        "pass": passed,
        "total_tasks": total_tasks,
        "tasks_with_gaps": tasks_with_gaps,
        "gap_ratio": round(gap_ratio, 2),
        "total_findings": total_findings,
        "low_confidence_findings": low_conf,
        "low_confidence_ratio": round(low_conf_ratio, 2),
        "thin_tasks": thin_tasks,
        "all_gaps": all_gaps[:20],
    }
    if not passed:
        follow_up = []
        for t in thin_tasks[:5]:
            follow_up.append(f"Task '{t['id']}' needs more research: {t.get('reason', '')}")
        if all_gaps:
            follow_up.append(f"Unresolved gaps: {', '.join(str(g) for g in all_gaps[:5])}")
        report["follow_up_needed"] = follow_up
    else:
        report["follow_up_needed"] = []
    return report


class ResearchOrchestrator:
    """Drive the BPS loop end-to-end."""

    def __init__(
        self,
        storage: Storage,
        config: Optional[Config] = None,
        on_status=None,
    ):
        self.config = config or default_config()
        if not self.config.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY required for ResearchOrchestrator")
        self.storage = storage
        self.client = Anthropic(api_key=self.config.anthropic_api_key, max_retries=0)
        self._strategy_read = StrategyReadHandler()
        self._strategy_write = StrategyWriteHandler()
        self._on_status = on_status or (lambda msg: None)
        self._rounds = 0

        self.tools = [
            _DISPATCH_RESEARCH_TOOL,
            self._strategy_write.to_anthropic_tool(),
            self._strategy_read.to_anthropic_tool(),
        ]

    def _execute_tool(self, name: str, args: dict) -> str:
        if name == "dispatch_research":
            return self._dispatch_workers(args.get("tasks", []))
        if name == "strategy_write":
            return json.dumps(self._strategy_write.execute(args, self.storage), default=str)
        if name == "strategy_read":
            return json.dumps(self._strategy_read.execute(args, self.storage), default=str)
        return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})

    def _dispatch_workers(self, tasks: list[dict]) -> str:
        if not tasks:
            return json.dumps({"ok": False, "error": "No tasks provided"})
        self._rounds += 1
        self._on_status(f"Round {self._rounds}: dispatching {len(tasks)} research worker(s)...")

        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as ex:
            futures = {}
            for task in tasks:
                task_id = task.get("id", "unknown")
                brief = task.get("brief", "")
                deep = task.get("deep", True)
                futures[ex.submit(run_research_worker, brief, self.config, deep)] = task_id

            for fut in as_completed(futures):
                task_id = futures[fut]
                try:
                    results[task_id] = fut.result()
                except Exception as e:
                    results[task_id] = {"ok": False, "error": str(e)}

        quality = _evaluate_quality(results)
        self._on_status(
            f"Round {self._rounds} complete. Quality pass={quality['pass']}, "
            f"findings={quality['total_findings']}, gaps={quality['tasks_with_gaps']}."
        )

        response = {"ok": True, "results": results, "quality_report": quality}
        if not quality["pass"] and self._rounds < 3:
            response["quality_warning"] = (
                f"QUALITY GATE: Round {self._rounds} did not meet thresholds. "
                f"Issues: {'; '.join(quality['follow_up_needed'][:3])}. "
                f"You SHOULD dispatch a follow-up round on the gaps and thin areas. "
                f"Round limit: 3 (currently on round {self._rounds})."
            )
        elif not quality["pass"]:
            response["quality_warning"] = (
                f"Quality thresholds not fully met after {self._rounds} rounds. "
                "Proceeding with available findings — flag low-confidence claims."
            )
        return json.dumps(response, default=str)

    def run(
        self,
        problem_statement: str,
        business_context: str = "",
        max_turns: int = 25,
    ) -> dict:
        """Run the full BPS loop. Returns:
        {"ok": bool, "turns", "deliverables": [keys], "research_rounds", "summary"}
        """
        prompt_builder = PromptBuilder(owner=self.config.owner_name)
        system_prompt = prompt_builder.build_research(problem_statement, business_context)

        self._on_status(f"Starting research: {problem_statement[:200]}")
        self._rounds = 0

        messages = [{
            "role": "user",
            "content": (
                f"Research problem: {problem_statement}\n\n"
                "Follow the BPS framework:\n"
                "1. Define the problem precisely\n"
                "2. Disaggregate into MECE sub-problems\n"
                "3. Prioritize by impact x researchability\n"
                "4. Use dispatch_research to send tasks to your research team\n"
                "5. Evaluate the findings critically — CHECK THE QUALITY REPORT\n"
                "   - If quality_report.pass is false, dispatch a follow-up round\n"
                "   - Up to 3 rounds total\n"
                "6. Synthesize into actionable recommendations\n"
                "7. Save deliverables using strategy_write\n\n"
                "QUALITY REQUIREMENTS:\n"
                "- Competitive landscape: 10+ competitors (direct, platform, vertical, adjacent)\n"
                "- Each claim must trace to a source URL\n"
                "- Financial calculations must show inputs and methodology\n"
                "- Flag low-confidence claims explicitly\n"
                "- Include a sources list with every strategy_write call"
            ),
        }]

        deliverables: list[str] = []

        for turn in range(max_turns):
            try:
                response = self.client.messages.create(
                    model=self.config.orchestrator_model,
                    max_tokens=8192,
                    system=system_prompt,
                    tools=self.tools,
                    messages=messages,
                )
            except Exception as e:
                return {"ok": False, "error": str(e), "turns": turn + 1}

            if response.stop_reason == "end_turn":
                text = "".join(b.text for b in response.content if hasattr(b, "text"))
                self._on_status(
                    f"Research complete. {len(deliverables)} deliverable(s) saved "
                    f"across {self._rounds} round(s)."
                )
                return {
                    "ok": True,
                    "turns": turn + 1,
                    "deliverables": deliverables,
                    "research_rounds": self._rounds,
                    "summary": text,
                }

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if block.name == "strategy_write":
                        deliverables.append(block.input.get("key", "unknown"))
                    result_str = self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

            if tool_results:
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

        return {
            "ok": False,
            "error": f"Reached max turns ({max_turns})",
            "deliverables": deliverables,
            "research_rounds": self._rounds,
        }
