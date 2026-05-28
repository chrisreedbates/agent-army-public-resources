"""Runtime configuration for Atlas.

Everything is overridable via environment variables, but you can also build a
Config in code and hand it to the Assistant directly. The package never reads
secrets from anywhere except env vars and explicit constructor arguments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val


@dataclass
class Config:
    """Atlas runtime config.

    Anthropic models — the defaults track the latest Claude family. Override
    only if you have a reason (cost, region, model availability).
    """

    # Identity
    owner_name: str = "the user"

    # Required: Anthropic
    anthropic_api_key: Optional[str] = None
    chat_model: str = "claude-opus-4-7"
    worker_model: str = "claude-sonnet-4-6"
    orchestrator_model: str = "claude-sonnet-4-6"

    # Optional: Perplexity for fast first-pass research
    perplexity_api_key: Optional[str] = None
    perplexity_model: str = "sonar"

    # Conversation loop
    max_turns: int = 40

    # Storage location (filesystem). Used by the CLI; library users pass a
    # Storage instance directly.
    state_dir: str = "./atlas_state"

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from environment variables and .env (if python-dotenv installed)."""
        try:
            from dotenv import load_dotenv  # type: ignore
            load_dotenv()
        except ImportError:
            pass

        return cls(
            owner_name=_env("ATLAS_OWNER_NAME", "the user"),
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            chat_model=_env("ATLAS_CHAT_MODEL", "claude-opus-4-7"),
            worker_model=_env("ATLAS_WORKER_MODEL", "claude-sonnet-4-6"),
            orchestrator_model=_env("ATLAS_ORCHESTRATOR_MODEL", "claude-sonnet-4-6"),
            perplexity_api_key=_env("PERPLEXITY_API_KEY"),
            perplexity_model=_env("PERPLEXITY_MODEL", "sonar"),
            max_turns=int(_env("ATLAS_MAX_TURNS", "40") or 40),
            state_dir=_env("ATLAS_STATE_DIR", "./atlas_state"),
        )

    def validate(self) -> list[str]:
        """Return a list of human-readable problems with this config (empty if OK)."""
        problems: list[str] = []
        if not self.anthropic_api_key:
            problems.append("ANTHROPIC_API_KEY is required")
        if not self.perplexity_api_key:
            # Not a blocker — just informational
            pass
        return problems


def default_config() -> Config:
    """Convenience for callers that just want env-driven defaults."""
    return Config.from_env()
