"""Atlas — an open-source strategy consultant agent.

Atlas thinks like a McKinsey engagement manager: hypothesis-driven, source-traceable,
opinionated, and willing to push back. It maintains an engagement tracker across
sessions, runs multi-hop research with quality gates, and produces structured
deliverables (ICP, competitive landscape, executive brief, etc.).

Quick start:

    from atlas import Assistant
    a = Assistant.from_env()
    result = a.chat("Help me think through a pricing change for our SaaS.")
    print(result["text"])
"""

from .assistant import Assistant
from .config import Config, default_config
from .prompts import PromptBuilder
from .research import ResearchOrchestrator, run_research_worker
from .storage import LocalStorage, Storage

__version__ = "0.1.0"

__all__ = [
    "Assistant",
    "Config",
    "default_config",
    "PromptBuilder",
    "ResearchOrchestrator",
    "run_research_worker",
    "Storage",
    "LocalStorage",
]
