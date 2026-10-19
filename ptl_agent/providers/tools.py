# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Local tool implementations for providers without a built-in agentic toolset
(currently OpenAI).

Reimplements the Claude SDK tools used by the PTL agent (Read, Bash, WebFetch)
with matching names, exposes JSON schemas for function calling, and provides a
dispatch() executor.
"""

import html
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

# Cap on characters returned by any single tool call, to protect the context.
MAX_OUTPUT_CHARS = 60000


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more chars]"


def tool_read(file_path: str, offset: int | None = None,
              limit: int | None = None) -> str:
    path = Path(file_path)
    try:
        lines = path.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except IsADirectoryError:
        return f"Error: {path} is a directory"
    except Exception as e:
        return f"Error reading {path}: {e}"

    start = (offset - 1) if offset and offset > 0 else 0
    end = (start + limit) if limit else len(lines)
    numbered = [f"{i}\t{line}" for i, line in enumerate(lines[start:end], start=start + 1)]
    return _truncate("\n".join(numbered))


def tool_bash(command: str, description: str = "", timeout: int = 120) -> str:
    try:
        proc = subprocess.run(command, shell=True, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error running command: {e}"

    parts = []
    if proc.stdout:
        parts.append(proc.stdout)
    if proc.stderr:
        parts.append(f"[stderr]\n{proc.stderr}")
    if proc.returncode != 0:
        parts.append(f"[exit code: {proc.returncode}]")
    return _truncate("\n".join(parts) if parts else "(no output)")


def tool_webfetch(url: str, prompt: str = "") -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ptl-agent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error fetching {url}: {e}"

    # Gerrit prepends )]}' to JSON responses.
    stripped = raw.lstrip()
    if stripped.startswith(")]}'"):
        raw = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[4:]
    elif "html" in ctype:
        raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
        raw = html.unescape(re.sub(r"(?s)<[^>]+>", "", raw))
    return _truncate(raw)


OPENAI_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "Read",
        "description": "Read a file from the filesystem. Returns line-numbered content.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file."},
                "offset": {"type": "integer", "description": "1-based line to start from (optional)."},
                "limit": {"type": "integer", "description": "Max number of lines to read (optional)."},
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "Bash",
        "description": "Run a shell command and return its output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
                "description": {"type": "string", "description": "One short sentence on why you run it."},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "WebFetch",
        "description": "Fetch the contents of a URL and return the text (HTML is stripped to text).",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch."},
                "prompt": {"type": "string", "description": "What you are looking for (optional)."},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
]

_DISPATCH = {
    "Read": tool_read,
    "Bash": tool_bash,
    "WebFetch": tool_webfetch,
}


def dispatch(name: str, args: dict[str, Any]) -> str:
    """Execute a tool by name with keyword args from the model."""
    func = _DISPATCH.get(name)
    if func is None:
        return f"Error: unknown tool '{name}'"
    try:
        return func(**args)
    except TypeError as e:
        return f"Error: bad arguments for {name}: {e}"
    except Exception as e:
        return f"Error executing {name}: {e}"
