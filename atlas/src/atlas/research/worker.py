"""Multi-hop research worker.

Phase 1: optional Perplexity Sonar scan — fast, cheap, identifies landscape + sources.
Phase 2: Claude deep-dive — visits actual URLs via fetch_url, fills gaps, validates
         low-confidence claims.

If Perplexity isn't configured, we skip Phase 1 and run Claude with web_search +
fetch_url tools end-to-end.
"""

from __future__ import annotations

import json
import os

from anthropic import Anthropic

from ..config import default_config
from ..prompts.builder import PromptBuilder
from ..tools.web import FetchUrlHandler, WebSearchHandler


_WORKER_TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web. Returns answer text and source URLs.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch and read the text content of a web page.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full URL to fetch"}},
            "required": ["url"],
        },
    },
]


def _parse_perplexity_response(content: str, citations: list) -> dict:
    """Parse Sonar's response. Handles JSON, JSON-in-fence, or prose."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_nl + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        findings = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return {
            "summary": content[:2000],
            "findings": [],
            "sources": citations,
            "gaps": ["Response was not structured JSON — needs deep-dive"],
            "raw": True,
        }

    if citations:
        existing = set(findings.get("sources", []))
        for url in citations:
            if url not in existing:
                findings.setdefault("sources", []).append(url)
                existing.add(url)
    return findings


def _run_perplexity_scan(brief: str, config) -> dict:
    """Phase 1: Perplexity Sonar scan."""
    try:
        from openai import OpenAI
    except ImportError:
        return {"ok": False, "error": "openai package required for Perplexity"}

    client = OpenAI(api_key=config.perplexity_api_key, base_url="https://api.perplexity.ai")
    system = PromptBuilder(owner=config.owner_name).build_worker(brief)
    try:
        response = client.chat.completions.create(
            model=config.perplexity_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": brief},
            ],
            max_tokens=4096,
            temperature=0.1,
        )
    except Exception as e:
        return {"ok": False, "error": f"perplexity_error: {e}"}

    content = response.choices[0].message.content.strip()
    citations = list(getattr(response, "citations", None) or [])
    return {"ok": True, "findings": _parse_perplexity_response(content, citations)}


def _needs_deep_dive(findings: dict) -> bool:
    if findings.get("gaps"):
        return True
    if len(findings.get("sources", [])) < 3:
        return True
    low_conf = [
        f for f in findings.get("findings", [])
        if isinstance(f, dict) and f.get("confidence") in ("low", "medium")
    ]
    if len(low_conf) >= 2:
        return True
    return findings.get("raw", False)


def _claude_loop(
    system_prompt: str,
    user_message: str,
    config,
    max_turns: int = 12,
) -> dict:
    """Run a Claude loop with web_search + fetch_url tools until end_turn."""
    client = Anthropic(api_key=config.anthropic_api_key, max_retries=0)
    web_search = WebSearchHandler()
    fetch_url = FetchUrlHandler()
    dedup: dict[str, str] = {}

    def _exec(name: str, args: dict) -> str:
        key = f"{name}:{json.dumps(args, sort_keys=True)}"
        if key in dedup:
            return dedup[key]
        if name == "web_search":
            result = web_search.execute(args, storage=None)
        elif name == "fetch_url":
            result = fetch_url.execute(args, storage=None)
        else:
            result = {"ok": False, "error": {"code": "UNKNOWN_TOOL", "message": name}}
        result_str = json.dumps(result, default=str)
        dedup[key] = result_str
        return result_str

    messages = [{"role": "user", "content": user_message}]

    for _ in range(max_turns):
        try:
            response = client.messages.create(
                model=config.worker_model,
                max_tokens=4096,
                system=system_prompt,
                tools=_WORKER_TOOLS,
                messages=messages,
            )
        except Exception as e:
            return {"ok": False, "error": f"claude_error: {e}"}

        if response.stop_reason == "end_turn":
            text = "".join(b.text for b in response.content if hasattr(b, "text"))
            try:
                return {"ok": True, "findings": json.loads(text)}
            except json.JSONDecodeError:
                return {"ok": True, "findings": {"summary": text, "raw": True}}

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _exec(block.name, block.input),
                })
        if tool_results:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    return {"ok": False, "error": "max_turns reached"}


def _run_claude_deep_dive(brief: str, phase1: dict, config) -> dict:
    """Phase 2: Claude visits URLs from Phase 1, fills gaps, validates claims."""
    gaps = phase1.get("gaps", [])
    sources = phase1.get("sources", [])
    low_conf = [
        f for f in phase1.get("findings", [])
        if isinstance(f, dict) and f.get("confidence") in ("low", "medium")
    ]
    phase1_str = json.dumps(phase1, indent=2, default=str)[:3000]

    system_prompt = f"""You are a research analyst doing TARGETED FOLLOW-UP research.

ORIGINAL TASK:
{brief}

PHASE 1 FINDINGS (from initial web scan):
{phase1_str}

YOUR JOB — targeted deep-dive to strengthen these findings:

1. VISIT ACTUAL SOURCE URLS from Phase 1 using fetch_url — read pricing pages,
   about pages, case studies, customer reviews. Don't trust search snippets.

2. FILL THESE GAPS: {json.dumps(gaps)[:800] if gaps else "Look for missing context."}

3. VALIDATE LOW-CONFIDENCE CLAIMS by finding additional sources:
   {json.dumps(low_conf)[:800] if low_conf else "All claims are high confidence."}

4. SEARCH FOR WHAT PHASE 1 MISSED.

RULES:
- READ actual web pages (fetch_url), don't just search.
- Every new claim needs a source URL.
- Cross-reference: if Phase 1 said "X costs $200", verify on their pricing page.

OUTPUT FORMAT — JSON only (no markdown fences):
{{
  "new_findings": [{{"claim": "...", "source_url": "...", "confidence": "high|medium|low"}}],
  "validated": [{{"original_claim": "...", "validation": "confirmed|revised|contradicted", "source_url": "...", "notes": "..."}}],
  "gaps_filled": ["description"],
  "remaining_gaps": ["..."],
  "sources": ["all URLs you actually visited"],
  "summary": "2-3 sentence synthesis of what this deep-dive added"
}}"""

    user_msg = (
        "Conduct a targeted deep-dive on this research. "
        f"Phase 1 summary: {phase1.get('summary', '')[:500]}. "
        "Priority: Visit source URLs and fill gaps."
    )
    return _claude_loop(system_prompt, user_msg, config, max_turns=10)


def _claude_fallback(brief: str, config) -> dict:
    """No Perplexity → run Claude end-to-end with web tools."""
    system_prompt = f"""You are a research analyst working for Atlas, a strategy consultant.

YOUR TASK:
{brief}

RESEARCH INSTRUCTIONS:
- Use web_search to find relevant information.
- Use fetch_url to read full web pages — don't just summarize snippets.
- Follow links to primary sources.
- Cross-reference claims across multiple sources.

OUTPUT FORMAT — JSON only:
{{
  "findings": [{{"claim": "...", "source_url": "...", "confidence": "high|medium|low"}}],
  "sources": ["URLs you actually read"],
  "gaps": ["things you couldn't find"],
  "summary": "2-3 sentence synthesis"
}}

Every claim must have a source URL."""
    return _claude_loop(system_prompt, brief, config, max_turns=15)


def _merge_findings(phase1: dict, phase2: dict) -> dict:
    f1 = phase1.get("findings", {})
    f2 = phase2.get("findings", {})

    all_sources = list(set(f1.get("sources", []) + f2.get("sources", [])))
    all_findings = f1.get("findings", []) + f2.get("new_findings", [])

    validated = {
        v.get("original_claim", ""): v
        for v in f2.get("validated", [])
        if isinstance(v, dict)
    }
    for finding in all_findings:
        if isinstance(finding, dict) and finding.get("claim", "") in validated:
            v = validated[finding["claim"]]
            if v.get("validation") == "confirmed":
                finding["confidence"] = "high"
            elif v.get("validation") == "contradicted":
                finding["confidence"] = "contradicted"
                finding["notes"] = v.get("notes", "")

    gaps_filled = set(f2.get("gaps_filled", []))
    remaining = f2.get("remaining_gaps", [])
    original = [g for g in f1.get("gaps", []) if g not in gaps_filled]
    all_gaps = list(set(original + remaining))

    summary = f1.get("summary", "")
    if f2.get("summary"):
        summary = f"{summary} [Deep-dive: {f2['summary']}]"

    return {
        "ok": True,
        "findings": {
            "findings": all_findings,
            "sources": all_sources,
            "gaps": all_gaps,
            "summary": summary,
            "phases_completed": 2,
        },
    }


def run_research_worker(brief: str, config=None, deep: bool = True) -> dict:
    """Run a research worker. Multi-hop if both Perplexity and Anthropic keys are
    configured; otherwise Claude end-to-end with web_search + fetch_url.

    Returns: {"ok": bool, "findings": {...}}
    """
    if config is None:
        config = default_config()

    if not config.anthropic_api_key and not config.perplexity_api_key:
        return {
            "ok": False,
            "error": "Neither ANTHROPIC_API_KEY nor PERPLEXITY_API_KEY configured",
        }

    # No Perplexity → Claude fallback
    if not config.perplexity_api_key:
        if not config.anthropic_api_key:
            return {"ok": False, "error": "ANTHROPIC_API_KEY required for Claude fallback"}
        return _claude_fallback(brief, config)

    # Phase 1: Perplexity scan
    scan = _run_perplexity_scan(brief, config)
    if not scan.get("ok"):
        # Phase 1 failed — fall back to Claude
        if config.anthropic_api_key:
            return _claude_fallback(brief, config)
        return scan

    findings = scan.get("findings", {})

    if not deep or not _needs_deep_dive(findings):
        return scan

    if not config.anthropic_api_key:
        return scan  # No Claude → can't deep-dive; ship Phase 1

    deep_result = _run_claude_deep_dive(brief, findings, config)
    if not deep_result.get("ok"):
        return scan  # Deep-dive failed → Phase 1 results still useful

    return _merge_findings(scan, deep_result)
