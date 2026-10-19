# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Provider/model configuration for the PTL agent.

Presets are organized by provider. Customize PRESETS to match the models
available on your plan/account.

Environment variable overrides (same as the openstack-review skill):
    AGENT_PROVIDER=openai ptl
    AGENT_PRESET=thorough ptl
    AGENT_MODEL=gpt-5 ptl
"""

import os
from typing import Any

# Default provider when none is specified (--provider / AGENT_PROVIDER override).
DEFAULT_PROVIDER = "claude"

DEFAULT_MAX_TURNS = 15

PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "claude": {
        "quick": {
            "model": "claude-haiku-4-5",
            "max_turns": 10,
            "description": "Fast, cheap briefing",
        },
        "standard": {
            "model": "claude-sonnet-4-6",
            "max_turns": 15,
            "description": "Standard briefing",
        },
        "thorough": {
            "model": "claude-opus-4-8",
            "max_turns": 25,
            "description": "Deeper analysis",
        },
    },
    # OpenAI model names are account-dependent — adjust to what you have access to.
    "openai": {
        "quick": {
            "model": "gpt-5-mini",
            "max_turns": 10,
            "description": "Fast, cheap briefing",
        },
        "standard": {
            "model": "gpt-5",
            "max_turns": 15,
            "description": "Standard briefing",
        },
        "thorough": {
            "model": "gpt-5",
            "max_turns": 25,
            "description": "Deeper analysis",
        },
    },
}

DEFAULT_PRESET = "standard"

# OpenAI (and OpenAI-compatible) pricing, in USD per 1M tokens. The Responses
# API returns no cost, so it is computed from token usage. Override at runtime
# with --openai-price-input/--openai-price-output or OPENAI_PRICE_INPUT /
# OPENAI_PRICE_OUTPUT. Models not listed here report no cost.
OPENAI_PRICING = {
    "gpt-5": {"input": 1.25, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
}


def get_openai_pricing(model: str) -> dict | None:
    """Return {'input', 'output'} USD-per-1M-token rates for a model, or None."""
    return OPENAI_PRICING.get(model)


def _resolve_provider(provider: str | None = None) -> str:
    """Active provider: flag > AGENT_PROVIDER env > default."""
    name = (provider or os.getenv("AGENT_PROVIDER") or DEFAULT_PROVIDER).lower()
    if name not in PRESETS:
        raise ValueError(
            f"Unknown provider '{name}'. Available: {', '.join(PRESETS)}"
        )
    return name


def get_model_config(provider: str | None = None, preset: str | None = None,
                     model_override: str | None = None) -> dict[str, Any]:
    """Resolve provider, model and default max_turns.

    Model priority: --model > AGENT_MODEL > --preset > AGENT_PRESET > default.
    Returns a dict with 'provider', 'model', 'max_turns' and 'source'.
    """
    provider_name = _resolve_provider(provider)
    provider_presets = PRESETS[provider_name]

    model = model_override or os.getenv("AGENT_MODEL")
    if model:
        source = f"--model {model}" if model_override else f"AGENT_MODEL={model}"
        return {"provider": provider_name, "model": model,
                "max_turns": DEFAULT_MAX_TURNS, "source": source}

    preset_name = preset or os.getenv("AGENT_PRESET") or DEFAULT_PRESET
    if preset_name not in provider_presets:
        raise ValueError(
            f"Unknown preset '{preset_name}' for provider '{provider_name}'. "
            f"Available: {', '.join(provider_presets)}"
        )

    config = provider_presets[preset_name].copy()
    config["provider"] = provider_name
    config["source"] = f"preset '{preset_name}' (provider '{provider_name}')"
    return config


def list_presets() -> str:
    """Formatted list of available presets, grouped by provider."""
    lines = ["Available presets (by provider):"]
    for provider_name, provider_presets in PRESETS.items():
        marker = " (default provider)" if provider_name == DEFAULT_PROVIDER else ""
        lines.append(f"\n{provider_name}{marker}:")
        for name, cfg in provider_presets.items():
            default = " (default preset)" if name == DEFAULT_PRESET else ""
            lines.append(
                f"  {name:10s} - {cfg['description']}\n"
                f"               Model: {cfg['model']}, "
                f"Max turns: {cfg['max_turns']}{default}"
            )
    return "\n".join(lines)
