# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Provider abstraction for the PTL agent.

A provider drives a model through an agentic run (system prompt + task prompt,
with Read/Bash/WebFetch tools) and returns a normalized AgentResult.

  - ClaudeProvider  (providers/claude.py)          -> Claude Agent SDK
  - OpenAIProvider  (providers/openai_provider.py) -> OpenAI Responses API
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console


@dataclass
class AgentResult:
    """Outcome of an agent run, normalized across providers."""

    success: bool = False
    # "success", "error_max_turns", ...
    subtype: str = "success"
    # Text blocks produced by the assistant, in order.
    text_parts: list[str] = field(default_factory=list)
    # Claude populates the SDK dict shape; OpenAI uses {"input_tokens", "output_tokens"}.
    usage: dict[str, Any] | None = None
    # Per-model breakdown (Claude SDK only).
    model_usage: dict[str, Any] | None = None
    # Total cost in USD when known.
    total_cost_usd: float | None = None
    provider: str = ""
    notes: list[str] = field(default_factory=list)


class AgentProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def run(self, *, model: str, effort: str | None = None,
                  max_turns: int,
                  system_prompt: str,
                  prompt: str, console: Console, verbose: bool) -> AgentResult:
        """Run the agent end-to-end, printing output to the console."""
        raise NotImplementedError
