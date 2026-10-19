# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Provider factory. Providers are imported lazily so that only the selected
provider's SDK needs to be installed."""

from .base import AgentProvider, AgentResult

__all__ = ["AgentProvider", "AgentResult", "get_provider"]


def get_provider(name: str, *, openai_base_url: str | None = None,
                 openai_price_input: float | None = None,
                 openai_price_output: float | None = None) -> AgentProvider:
    """Return a provider instance for "claude" or "openai"."""
    key = (name or "").lower()
    if key == "claude":
        from .claude import ClaudeProvider

        return ClaudeProvider()
    if key == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            base_url=openai_base_url,
            price_input=openai_price_input,
            price_output=openai_price_output,
        )
    raise ValueError(f"Unknown provider '{name}'. Available: claude, openai")
