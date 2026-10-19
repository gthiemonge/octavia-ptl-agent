# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Claude provider: wraps the Claude Agent SDK.

Vertex AI is auto-detected by the SDK from CLAUDE_CODE_USE_VERTEX,
ANTHROPIC_VERTEX_PROJECT_ID and CLOUD_ML_REGION.
"""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .base import AgentProvider, AgentResult


class ClaudeProvider(AgentProvider):
    name = "claude"

    async def run(self, *, model: str, max_turns: int, system_prompt: str,
                  prompt: str, console: Console, verbose: bool) -> AgentResult:
        try:
            from claude_agent_sdk import (
                query,
                ClaudeAgentOptions,
                AssistantMessage,
                ResultMessage,
                TextBlock,
                ThinkingBlock,
                ToolUseBlock,
            )
        except ImportError as e:
            raise RuntimeError(
                "The 'claude-agent-sdk' package is required for the claude "
                "provider. Install it with: pip install claude-agent-sdk"
            ) from e

        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system_prompt,
            allowed_tools=["WebFetch", "WebSearch", "Bash", "Read"],
            max_turns=max_turns,
        )

        result = AgentResult(provider=self.name)

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result.text_parts.append(block.text)
                        console.print(Markdown(block.text))
                    elif isinstance(block, ThinkingBlock) and verbose:
                        console.print(Panel(block.thinking, title="Thinking",
                                            border_style="yellow", expand=False))
                    elif isinstance(block, ToolUseBlock) and verbose:
                        console.print(f"  [dim]> {block.name}({block.input})[/dim]")

            elif isinstance(message, ResultMessage):
                result.subtype = message.subtype
                result.success = message.subtype == "success"
                result.usage = getattr(message, "usage", None)
                result.model_usage = getattr(message, "model_usage", None)
                result.total_cost_usd = getattr(message, "total_cost_usd", None)

        return result
