# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python project using the Claude Agent SDK (`claude-agent-sdk`) to build an OpenStack Octavia PTL daily briefing agent. All code lives in the `ptl_agent/` package.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install .
```

Requires either `ANTHROPIC_API_KEY` or Vertex AI credentials (`CLAUDE_CODE_USE_VERTEX`, `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID` + gcloud ADC).

## Running

```bash
# PTL daily briefing (all sources, last 1 day)
ptl

# Specific sources, 7-day window, verbose
ptl -s gerrit zuul schedule -d 7 -v

# Personal Gerrit activity (patches, reviews, comments)
ptl -u gthiemon -d 7

# Choose model
ptl -m claude-sonnet-5

# Save briefing to file
ptl -d 7 -o briefing.md

# Or run directly
python -m ptl_agent.cli -d 3
```

## Container

```bash
podman build -f Containerfile.dev -t octavia-ptl .
podman run --userns=keep-id \
    -v ~/.config/gcloud:/home/claude/.config/gcloud:ro \
    -v .ptl_cache:/app/.ptl_cache \
    -e GOOGLE_APPLICATION_CREDENTIALS=/home/claude/.config/gcloud/application_default_credentials.json \
    -e CLAUDE_CODE_USE_VERTEX -e CLOUD_ML_REGION -e ANTHROPIC_VERTEX_PROJECT_ID \
    octavia-ptl ptl -d 3
```

## Architecture

### PTL Agent (`ptl_agent/cli.py`)

The agent works in two phases:
1. **Pre-fetch** — Python modules fetch and filter data from APIs before the agent runs, producing compact JSON files in `.ptl_cache/`
2. **Agent analysis** — The Claude agent reads the pre-fetched files via the `Read` tool and synthesizes a structured briefing

This design minimizes token usage — raw API responses are large and verbose; the pre-fetch modules extract only relevant fields and produce summaries.

### Pre-fetch Modules

| Module | Source | What it does |
|--------|--------|-------------|
| `ptl_agent/fetch_gerrit.py` | Gerrit (review.opendev.org) | Fetches open reviews for all 5 Octavia projects, extracts review state/labels/owner |
| `ptl_agent/fetch_zuul.py` | Zuul CI (zuul.opendev.org) | Fetches CI failures, summarizes by job and project, flags gate failures |
| `ptl_agent/fetch_launchpad.py` | Launchpad (api.launchpad.net) | Fetches open bugs, groups by status/importance |
| `ptl_agent/fetch_schedule.py` | Release schedule (releases.openstack.org) | Scrapes current cycle milestones, computes countdown to deadlines |
| `ptl_agent/fetch_mailinglist.py` | openstack-discuss (lists.openstack.org) | Fetches mbox archive, groups threads by category: octavia, ptl-tagged, general |
| `ptl_agent/fetch_gerrit_activity.py` | Gerrit (review.opendev.org) | Fetches personal activity: patches authored, reviews given, comments posted |

IRC logs are cached differently: past days (immutable) are fetched and stored in `.ptl_cache/`, today's log is fetched live by the agent via `WebFetch`.

### Octavia Team Projects

Gerrit and Zuul queries cover all 5 repos: `octavia`, `octavia-tempest-plugin`, `octavia-lib`, `python-octaviaclient`, `octavia-dashboard`.

## Key SDK Patterns

- `query(prompt, options)` is an async generator yielding `AssistantMessage` and `ResultMessage`
- `ClaudeAgentOptions` controls model, allowed tools, max turns, system prompt, and permissions
- Built-in tools: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebSearch`, `WebFetch`
- `ResultMessage` carries `total_cost_usd` and `model_usage` dict (camelCase keys: `inputTokens`, `outputTokens`, `costUSD`)
- `AssistantMessage.content` can contain `TextBlock`, `ThinkingBlock`, `ToolUseBlock`
