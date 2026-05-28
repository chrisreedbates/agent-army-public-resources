"""Compose system prompts for chat mode and research mode."""

from datetime import datetime
from typing import Optional

from . import sections


class PromptBuilder:
    """Assembles Atlas's system prompts from the modular sections."""

    VERSION = "1.0.0"

    def __init__(self, owner: str = "the user"):
        self.owner = owner

    @staticmethod
    def _format_datetime(date: Optional[datetime] = None) -> str:
        if date is None:
            date = datetime.now()
        return date.strftime("%A, %B %d, %Y at %I:%M %p")

    def build_chat(
        self,
        project_state: str = "",
        date: Optional[datetime] = None,
    ) -> str:
        """System prompt for interactive chat — the full consulting brain."""
        parts = [
            sections.identity(self.owner),
            f"\nCURRENT DATE & TIME: {self._format_datetime(date)}",
        ]

        if project_state:
            parts.append(f"\n=== ENGAGEMENT DASHBOARD ===\n{project_state}")

        parts.extend([
            f"\n{sections.judgment(self.owner)}",
            f"\n{sections.engagement_model(self.owner)}",
            f"\n{sections.TOOL_CALLING}",
            f"\n{sections.conversation_style(self.owner)}",
            f"\n{sections.working_assumptions(self.owner)}",
            f"\n{sections.no_hallucinations(self.owner)}",
            f"\n{sections.SECURITY}",
        ])

        return "\n".join(parts)

    def build_research(
        self,
        problem_statement: str,
        business_context: str = "",
        date: Optional[datetime] = None,
    ) -> str:
        """System prompt for the research orchestrator."""
        parts = [
            sections.identity(self.owner),
            f"\nCURRENT DATE & TIME: {self._format_datetime(date)}",
            f"\n=== CURRENT RESEARCH PROBLEM ===\n{problem_statement}",
        ]

        if business_context:
            parts.append(f"\n=== BUSINESS CONTEXT ===\n{business_context}")

        parts.extend([
            f"\n{sections.judgment(self.owner)}",
            f"\n{sections.BPS_FRAMEWORK}",
            f"\n{sections.no_hallucinations(self.owner)}",
        ])

        return "\n".join(parts)

    def build_worker(self, research_brief: str) -> str:
        """System prompt for individual research workers."""
        return sections.worker_prompt(research_brief)
