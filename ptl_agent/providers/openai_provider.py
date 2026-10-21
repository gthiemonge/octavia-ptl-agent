# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""OpenAI provider: a hand-written agentic loop on the OpenAI Responses API.

A custom endpoint (Azure / OpenAI-compatible / proxy / self-hosted) is supported
via base_url: --openai-base-url -> OPENAI_BASE_URL -> official API default.
"""

import json
import os
from typing import Any

from rich.console import Console
from rich.markdown import Markdown

from . import tools as _tools
from .base import AgentProvider, AgentResult

# Response headers used by OpenAI-compatible gateways (litellm, ...) to report
# per-request cost in USD.
_COST_HEADERS = ("x-litellm-response-cost", "x-response-cost", "x-cost-usd")


class OpenAIProvider(AgentProvider):
    name = "openai"

    def __init__(self, base_url: str | None = None,
                 price_input: float | None = None,
                 price_output: float | None = None):
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or None
        self.price_input = _first_float(price_input, os.getenv("OPENAI_PRICE_INPUT"))
        self.price_output = _first_float(price_output, os.getenv("OPENAI_PRICE_OUTPUT"))

    async def run(self, *, model: str, effort: str | None = None,
                  max_turns: int,
                  system_prompt: str,
                  prompt: str, console: Console, verbose: bool) -> AgentResult:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "The 'openai' package is required for the openai provider. "
                "Install it with: pip install openai"
            ) from e

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Export it before running with "
                "--provider openai."
            )

        client_kwargs = {"api_key": api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        if os.getenv("OPENAI_ORG"):
            client_kwargs["organization"] = os.getenv("OPENAI_ORG")

        console.print(
            f"Using OpenAI endpoint: {self.base_url or 'https://api.openai.com/v1 (default)'}"
        )
        client = OpenAI(**client_kwargs)

        result = AgentResult(provider=self.name)
        total_input = total_output = 0
        api_cost = 0.0
        api_cost_seen = False

        # Keep the history client-side (no previous_response_id): OpenAI-compatible
        # backends typically don't persist responses.
        input_items = [{"role": "user", "content": prompt}]

        for _ in range(max_turns):
            request: dict[str, Any] = {
                "model": model,
                "instructions": system_prompt,
                "input": input_items,
                "tools": _tools.OPENAI_TOOL_SCHEMAS,
            }
            if effort is not None:
                request["reasoning"] = {"effort": effort}
            raw = client.responses.with_raw_response.create(**request)
            response = raw.parse()

            turn_cost = _header_cost(raw)
            if turn_cost is not None:
                api_cost += turn_cost
                api_cost_seen = True

            usage = getattr(response, "usage", None)
            if usage is not None:
                total_input += getattr(usage, "input_tokens", 0) or 0
                total_output += getattr(usage, "output_tokens", 0) or 0

            tool_calls = []
            for item in response.output:
                itype = getattr(item, "type", None)
                if itype == "message":
                    text = _message_text(item)
                    if text:
                        result.text_parts.append(text)
                        console.print(Markdown(text))
                        input_items.append({"role": "assistant", "content": text})
                elif itype == "function_call":
                    tool_calls.append(item)
                    input_items.append({
                        "type": "function_call",
                        "call_id": item.call_id,
                        "name": item.name,
                        "arguments": item.arguments,
                    })

            if not tool_calls:
                result.success = True
                result.subtype = "success"
                break

            for call in tool_calls:
                try:
                    args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if verbose:
                    console.print(f"  [dim]> {call.name}({args})[/dim]")
                input_items.append({
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": _tools.dispatch(call.name, args),
                })
        else:
            result.success = False
            result.subtype = "error_max_turns"

        result.usage = {"input_tokens": total_input, "output_tokens": total_output}

        # Gateway-reported cost is authoritative; else compute from token rates.
        if api_cost_seen:
            result.total_cost_usd = api_cost
        else:
            rates = self._resolve_rates(model)
            if rates is not None:
                result.total_cost_usd = (
                    total_input * rates["input"] + total_output * rates["output"]
                ) / 1_000_000
            else:
                result.notes.append(
                    f"Cost: unknown — no cost reported for model '{model}'."
                )

        return result

    def _resolve_rates(self, model: str) -> dict | None:
        if self.price_input is not None and self.price_output is not None:
            return {"input": self.price_input, "output": self.price_output}
        from ptl_agent.config import get_openai_pricing
        return get_openai_pricing(model)


def _header_cost(raw) -> float | None:
    headers = getattr(raw, "headers", None)
    if not headers:
        return None
    for key in _COST_HEADERS:
        value = headers.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _first_float(*values) -> float | None:
    for v in values:
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _message_text(item) -> str:
    parts = []
    for block in getattr(item, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)
