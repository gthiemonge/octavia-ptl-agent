# Octavia PTL Daily Briefing Agent

A CLI tool that generates daily activity summaries for the OpenStack Octavia PTL (Project Team Lead). Built with the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk), it fetches data from multiple community sources, filters it in Python to minimize token usage, then uses a Claude agent to analyze and synthesize a structured briefing.

## Sources

| Source | Data |
|--------|------|
| **Gerrit** (review.opendev.org) | Open reviews across all Octavia projects, grouped by review state |
| **Zuul CI** (zuul.opendev.org) | CI failures, patterns by job/project, gate failures |
| **Launchpad** (api.launchpad.net) | Open bugs by status/importance, new bugs |
| **IRC/Matrix** (meetings.opendev.org) | Channel logs from #openstack-lbaas |
| **Release Schedule** (releases.openstack.org) | Upcoming milestones, feature freeze countdown |

All sources are public and require no authentication.

### Octavia Team Projects

Gerrit and Zuul queries cover all 5 repositories:
- `openstack/octavia`
- `openstack/octavia-tempest-plugin`
- `openstack/octavia-lib`
- `openstack/python-octaviaclient`
- `openstack/octavia-dashboard`

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install .
```

### Authentication

The agent needs credentials for the Claude API. Either:

- **Anthropic API**: `export ANTHROPIC_API_KEY="sk-ant-..."`
- **Vertex AI**: set `CLAUDE_CODE_USE_VERTEX`, `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID`, and configure gcloud ADC (`gcloud auth application-default login`)

## Usage

```bash
# Daily briefing (all sources, last 1 day)
ptl

# Look back 7 days, verbose output
ptl -d 7 -v

# Specific sources only
ptl -s gerrit zuul
ptl -s schedule launchpad

# Choose model
ptl -m claude-sonnet-5

# Save briefing to a markdown file
ptl -d 7 -o briefing.md

# Add a follow-up question
ptl "also check if there are any stable branch backports pending"
```

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `prompt` (positional) | generate briefing | Optional follow-up question |
| `--model` / `-m` | `claude-sonnet-4-6` | Model ID |
| `--days` / `-d` | `1` | Days to look back |
| `--sources` / `-s` | all | Sources to include: `gerrit`, `zuul`, `launchpad`, `irc`, `schedule` |
| `--max-turns` / `-t` | `15` | Max agent turns |
| `--output` / `-o` | stdout | Write briefing to a file |
| `--verbose` / `-v` | off | Show tool calls, thinking, and env var check |

## Container

```bash
# Build
podman build -t octavia-ptl .

# Run with Vertex AI credentials
podman run \
    -v ~/.config/gcloud:/root/.config/gcloud:ro \
    -e CLAUDE_CODE_USE_VERTEX \
    -e CLOUD_ML_REGION \
    -e ANTHROPIC_VERTEX_PROJECT_ID \
    octavia-ptl

# Run with Anthropic API key
podman run -e ANTHROPIC_API_KEY octavia-ptl

# Pass extra flags
podman run \
    -v ~/.config/gcloud:/root/.config/gcloud:ro \
    -e CLAUDE_CODE_USE_VERTEX \
    -e CLOUD_ML_REGION \
    -e ANTHROPIC_VERTEX_PROJECT_ID \
    octavia-ptl -d 7 -s gerrit schedule -v
```

A `Containerfile.dev` is also available for development (no entrypoint set).

## Architecture

The agent works in two phases:

1. **Pre-fetch** — Python modules fetch and filter data from APIs before the agent starts, producing compact JSON files in `.ptl_cache/`. This strips irrelevant fields and pre-computes summaries, significantly reducing token usage.

2. **Agent analysis** — The Claude agent reads the pre-fetched files via its built-in `Read` tool and synthesizes a structured briefing with sections for reviews, CI health, bugs, release schedule, and action items.

### Project Structure

```
ptl_agent/
├── __init__.py
├── cli.py               # Agent runner, system prompt, CLI
├── fetch_gerrit.py       # Gerrit review pre-fetch
├── fetch_zuul.py         # Zuul CI failure pre-fetch
├── fetch_launchpad.py    # Launchpad bug pre-fetch
└── fetch_schedule.py     # Release schedule pre-fetch
```

### Caching

- **IRC logs** for past days are cached in `.ptl_cache/` (immutable — a past day's log never changes). Today's log is fetched live.
- **API data** (Gerrit, Zuul, Launchpad, schedule) is fetched fresh on each run and saved to `.ptl_cache/` for the agent to read.

## Output

The briefing includes these sections:

- **Reviews Needing Attention** — changes with no +2, sorted by age
- **Ready to Merge** — changes with +2 / W+1
- **CI Health** — failure patterns, recurring job failures, gate failures
- **Bug Tracker** — new bugs, critical/high bugs, counts by status
- **IRC Activity** — key discussions and decisions from #openstack-lbaas
- **Release Schedule** — upcoming milestones with countdown, at-risk feature patches
- **Action Items** — concrete PTL to-dos derived from the data

## Cost

A typical full briefing with all sources costs approximately $0.05–0.30 depending on the model and data volume. Use `--verbose` to see per-model token usage and cost breakdown. Use `-s` to limit sources for cheaper runs.
