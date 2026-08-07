# Octavia PTL Daily Briefing Agent — Plan & Status

## Goal

Build a CLI tool using the Claude Agent SDK that gives the Octavia PTL a morning briefing by fetching and summarizing community activity across multiple OpenStack sources.

## Architecture

Python package (`ptl_agent/`) that:
1. Builds a detailed system prompt with exact URLs, response format notes, and output structure
2. Lets the Claude agent autonomously fetch data sources via its built-in `WebFetch` tool
3. Synthesizes a structured briefing and prints cost/tokens at the end

## Data Sources

| Source | API | Format | Status |
|--------|-----|--------|--------|
| Gerrit reviews | `review.opendev.org/changes/` | JSON (strip `)]}'` prefix) | Done |
| Zuul CI failures | `zuul.opendev.org/api/tenant/openstack/builds` | JSON | Done |
| Launchpad bugs | `api.launchpad.net/devel/octavia` | JSON | Done |
| IRC/Matrix logs | `meetings.opendev.org/irclogs/#openstack-lbaas` | HTML (cached) | Done |
| Release schedule | `releases.openstack.org/{release}/schedule.html` | HTML (pre-fetched) | Done |
| openstack-discuss mailing list | `lists.openstack.org/archives/` | HTML / mbox | Planned |

Gerrit and Zuul query all 5 Octavia team projects: `octavia`, `octavia-tempest-plugin`, `octavia-lib`, `python-octaviaclient`, `octavia-dashboard`.

All sources are public and require no authentication.

## CLI Options

| Flag | Default | Description | Status |
|------|---------|-------------|--------|
| `prompt` (positional) | generate briefing | Optional follow-up question | Done |
| `--model` / `-m` | SDK default | Model ID (e.g. `claude-sonnet-5`) | Done |
| `--days` / `-d` | `1` | Days to look back | Done |
| `--sources` / `-s` | all | Limit to specific sources (`gerrit`, `zuul`, `launchpad`, `irc`, `schedule`) | Done |
| `--max-turns` / `-t` | `15` | Max agent turns | Done |
| `--verbose` / `-v` | off | Show tool calls and thinking | Done |
| `--output` / `-o` | stdout | Write briefing to a markdown file | Done |

## Output Sections

The briefing is structured as:
1. **Reviews Needing Attention** — changes with no +2, sorted by age
2. **Ready to Merge** — changes with +2 / W+1
3. **CI Health** — failure patterns, recurring failures, gate failures
4. **Bug Tracker** — new bugs, critical/high bugs, counts by status
5. **IRC Activity** — key discussions, decisions, action items from #openstack-lbaas
6. **Release Schedule** — upcoming milestones, feature freeze countdown, at-risk patches
7. **Action Items** — concrete PTL to-dos derived from the data

## Files

| File | Purpose | Status |
|------|---------|--------|
| `ptl_agent/cli.py` | Main agent script | Done |
| `pyproject.toml` | Project config with `ptl` entry point | Done |
| `Containerfile` | Container build (Fedora 43) | Done |

## Completed Work

- [x] Project setup (`pyproject.toml`, dependencies, entry points)
- [x] PTL briefing agent (`ptl_agent/cli.py`) with 5 data sources
- [x] Source filtering (`--sources` flag)
- [x] Verbose mode (tool calls + thinking)
- [x] Cost and token usage reporting (per-model breakdown)
- [x] IRC/Matrix log source with file-based caching
- [x] Multi-project support (all 5 Octavia team repos in Gerrit/Zuul)
- [x] `--output` flag to save briefing to a markdown file
- [x] Rich terminal output (colored markdown, panels, formatted stats table)
- [x] Zuul pre-fetch (`fetch_zuul.py`) — fetches, filters, and summarizes CI data in Python before the agent runs, reducing token usage
- [x] Gerrit pre-fetch (`fetch_gerrit.py`) — extracts review state, labels, owner; sorts by needs-review first
- [x] Launchpad pre-fetch (`fetch_launchpad.py`) — extracts bug fields, groups by importance/status
- [x] Release schedule source (`fetch_schedule.py`) — scrapes current cycle milestones, flags upcoming deadlines, cross-references with feature freeze

## Next Steps

- [ ] Test full run with all sources and iterate on system prompt
- [ ] Add openstack-discuss mailing list source
- [ ] Core reviewer activity tracking (review counts per reviewer)
- [ ] Stable branch gate health (filter Zuul by stable/* branches)
