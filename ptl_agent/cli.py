# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Octavia PTL Daily Briefing Agent.

Uses the Claude Agent SDK to fetch and summarize OpenStack Octavia
community activity from Gerrit, Zuul CI, Launchpad, and IRC logs.
"""

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from ptl_agent.fetch_gerrit import fetch_gerrit_data
from ptl_agent.fetch_gerrit_activity import fetch_gerrit_activity_data
from ptl_agent.fetch_launchpad import fetch_launchpad_data
from ptl_agent.fetch_launchpad_activity import fetch_launchpad_activity_data
from ptl_agent.fetch_schedule import fetch_schedule_data
from ptl_agent.fetch_mailinglist import fetch_mailinglist_data
from ptl_agent.fetch_zuul import fetch_zuul_data

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

CACHE_DIR = Path(".ptl_cache")
IRC_CHANNEL = "openstack-lbaas"
IRC_BASE_URL = "https://meetings.opendev.org/irclogs/%23{channel}/{filename}"

OCTAVIA_PROJECTS = [
    "openstack/octavia",
    "openstack/octavia-tempest-plugin",
    "openstack/octavia-lib",
    "openstack/python-octaviaclient",
    "openstack/octavia-dashboard",
]

SYSTEM_PROMPT_HEADER = """\
You are the daily briefing assistant for the OpenStack Octavia PTL (Project Team Lead).
Your job: analyze pre-fetched community data and produce a concise morning summary
covering the last {days} day(s). Today is {today}.

Most data has been pre-fetched into local JSON files — use the Read tool to load them.
Use WebFetch only when explicitly told to (e.g. today's IRC log).
Prefer reading and analyzing the pre-fetched data over making new API calls.
"""

SOURCE_GERRIT = """\
═══ GERRIT OPEN REVIEWS ═══
Gerrit review data has been pre-fetched and filtered for all Octavia team projects.
Read the file at: {gerrit_data_path}

The JSON file contains:
- "summary": total open, counts by review_state (needs-review, approved, negative), by project
- "recently_updated": changes updated in the last {days} day(s)
- "all_open": all open changes, sorted by review_state then updated date
Each change has: number, project, branch, subject, owner, created, updated,
insertions, deletions, code_review, workflow, review_state, unresolved_comments, url.

Report reviews grouped by state: needs-review first (oldest updated at top),
then negative reviews, then approved/ready-to-merge.
Do NOT re-fetch this data with WebFetch — it is already on disk.
"""

SOURCE_ZUUL = """\
═══ ZUUL CI FAILURES ═══
Zuul CI failure data has been pre-fetched and filtered for all Octavia team projects.
Read the file at: {zuul_data_path}

The JSON file contains:
- "summary": failure counts by job and by project, plus gate failures list
- "builds": array of filtered builds with fields: job, result, pipeline, voting,
  project, branch, change, patchset, start_time, duration_s, log_url, review_url

Analyze the data and report:
- Are the same jobs failing repeatedly? (check summary.failures_by_job)
- Are failures concentrated on specific projects? (check summary.failures_by_project)
- Any gate failures? (summary.gate_failures — HIGH PRIORITY)
- Link to log_url for investigation, review_url for the associated change
Do NOT re-fetch this data with WebFetch — it is already on disk.
"""

SOURCE_LAUNCHPAD = """\
═══ LAUNCHPAD BUGS ═══
Launchpad bug data has been pre-fetched and filtered for the Octavia project.
Read the file at: {launchpad_data_path}

The JSON file contains:
- "summary": total open, counts by status and importance, critical_high_count, new_in_period
- "new_bugs": bugs filed in the last {days} day(s)
- "critical_high": all open Critical/High importance bugs
- "all_open": all open bugs with fields: title, status, importance, assignee, date_created, web_link
Do NOT re-fetch this data with WebFetch — it is already on disk.
"""

# {irc_instructions} is filled dynamically with cached file paths and today's live URL
SOURCE_IRC = """\
═══ IRC / MATRIX LOGS (#{channel}) ═══
The Octavia team uses the #{channel} channel. Logs are at:
https://meetings.opendev.org/irclogs/%23{channel}/

{irc_instructions}

When analyzing IRC logs:
- Identify key discussions, decisions, and action items
- Note who participated
- Flag any issues raised or help requests
- Summarize topics discussed, not every line
"""

OUTPUT_GERRIT = """\
## Reviews Needing Attention
- List changes needing review (no +2), sorted by age (oldest first)
- For each: subject, owner, days since last update, URL

## Ready to Merge
- Changes with +2 / W+1 that can be approved or are awaiting gate
"""

OUTPUT_ZUUL = """\
## CI Health
- Summary of failure patterns
- Any recurring job failures (list job name + count)
- Any gate failures (HIGH PRIORITY)
"""

OUTPUT_LAUNCHPAD = """\
## Bug Tracker
- New bugs filed in the last {days} day(s)
- Critical/High bugs currently open
- Total open bug count by status
"""

OUTPUT_IRC = """\
## IRC Activity
- Key discussions and decisions from #{channel}
- Action items mentioned
- Help requests or issues raised
- If no activity, say so
"""

SOURCE_SCHEDULE = """\
═══ RELEASE SCHEDULE ═══
Release schedule data has been pre-fetched for the current development cycle.
Read the file at: {schedule_data_path}

The JSON file contains:
- "release_name": the current release codename
- "schedule_url": link to the full schedule page
- "reminders.upcoming": events happening in the next 30 days (with days_from_today)
- "reminders.past": recent past events
- "reminders.future": events more than 30 days away

Focus on upcoming events. For each, note how many days away it is.
If feature freeze is approaching, cross-reference with the Gerrit reviews:
highlight patches that implement new features and need to merge before the freeze.
Do NOT re-fetch this data with WebFetch — it is already on disk.
"""

OUTPUT_SCHEDULE = """\
## Release Schedule ({release_name})
- Next upcoming milestones and deadlines (with countdown in days)
- If feature freeze is within 30 days: list feature patches at risk of missing it
- Link to the full schedule
"""

SOURCE_MAILINGLIST = """\
═══ OPENSTACK-DISCUSS MAILING LIST ═══
Mailing list data has been pre-fetched from the openstack-discuss archives.
Read the file at: {mailinglist_data_path}

The JSON file contains:
- "summary": total threads/messages, counts by category (octavia, ptl, general)
- "octavia_threads": threads with [octavia] tag — direct project relevance
- "ptl_threads": threads with [ptl] tag — PTL-specific discussions
- "general_threads": all other threads — community-wide topics

Each thread has: subject, tags, categories, message_count, participants, first_date, last_date.

Focus on octavia and ptl threads first. For general threads, highlight
security advisories (OSSA/OSSN), release announcements, governance topics,
and anything that may affect Octavia or require PTL action.
Do NOT re-fetch this data with WebFetch — it is already on disk.
"""

OUTPUT_MAILINGLIST = """\
## Mailing List (openstack-discuss)
- Octavia-specific threads and key points
- PTL-tagged discussions requiring attention
- Notable community-wide threads (security, releases, governance)
"""

SOURCE_ACTIVITY = """\
═══ YOUR GERRIT ACTIVITY ═══
Personal Gerrit activity data has been pre-fetched for user "{user}".
Read the file at: {activity_data_path}

The JSON file contains:
- "summary": patches_count, reviews_count, comments_count
- "patches": changes authored by {user} in the last {days} day(s)
- "reviews": changes reviewed by {user} (excluding self-owned)
- "comments": changes commented on by {user} (excluding self-owned and already in reviews)

Each change has the same fields as in the Gerrit reviews data.
Do NOT re-fetch this data with WebFetch — it is already on disk.
"""

OUTPUT_ACTIVITY = """\
## Your Activity ({user})
- Patches submitted (with current review state)
- Reviews given on others' changes
- Comments posted
"""

SOURCE_LP_ACTIVITY = """\
═══ YOUR LAUNCHPAD BUG ACTIVITY ═══
Personal Launchpad bug activity has been pre-fetched for user "{lp_user}".
Read the file at: {lp_activity_data_path}

The JSON file contains:
- "summary": reported_count, reported_recent, assigned_count, assigned_recent
- "reported": all open bugs reported by {lp_user}
- "recently_reported": bugs reported in the last {days} day(s)
- "assigned": all open bugs assigned to {lp_user}
- "recently_assigned": bugs assigned in the last {days} day(s)

Each bug has: title, status, importance, assignee, date_created, web_link.
Do NOT re-fetch this data with WebFetch — it is already on disk.
"""

OUTPUT_LP_ACTIVITY = """\
## Your Bug Activity ({lp_user})
- Bugs you reported (with status)
- Bugs assigned to you (with importance and status)
"""

OUTPUT_FOOTER = """\
## Action Items
- Bullet list of concrete things the PTL should do today, derived from the data above

Keep the tone professional but concise. Use markdown formatting.
If a fetch fails, note the failure and continue with the other sources.
Do NOT fabricate data. If a source returns empty results, say so.
"""

ALL_SOURCES = {
    "gerrit": (SOURCE_GERRIT, OUTPUT_GERRIT),
    "zuul": (SOURCE_ZUUL, OUTPUT_ZUUL),
    "launchpad": (SOURCE_LAUNCHPAD, OUTPUT_LAUNCHPAD),
    "irc": (SOURCE_IRC, OUTPUT_IRC),
    "schedule": (SOURCE_SCHEDULE, OUTPUT_SCHEDULE),
    "mailinglist": (SOURCE_MAILINGLIST, OUTPUT_MAILINGLIST),
    "activity": (SOURCE_ACTIVITY, OUTPUT_ACTIVITY),
    "lp-activity": (SOURCE_LP_ACTIVITY, OUTPUT_LP_ACTIVITY),
}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def cache_get(url: str) -> str | None:
    path = CACHE_DIR / f"{cache_key(url)}.txt"
    if path.exists():
        return path.read_text()
    return None


def cache_put(url: str, content: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{cache_key(url)}.txt"
    path.write_text(content)
    return path


def fetch_and_cache(url: str) -> tuple[str | None, Path | None]:
    """Fetch a URL. Returns (content, cache_path) or (None, None) on failure."""
    cached = cache_get(url)
    if cached is not None:
        path = CACHE_DIR / f"{cache_key(url)}.txt"
        return cached, path

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ptl-agent/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        path = cache_put(url, content)
        return content, path
    except Exception as e:
        print(f"  [cache] Failed to fetch {url}: {e}")
        return None, None


def irc_log_url(date: datetime.date) -> str:
    filename = f"%23{IRC_CHANNEL}.{date.isoformat()}.log.html"
    return IRC_BASE_URL.format(channel=IRC_CHANNEL, filename=filename)


def prefetch_irc_logs(days: int, verbose: bool = False) -> str:
    """Pre-fetch IRC logs for past days (immutable). Returns instructions for
    the system prompt telling the agent where to find cached files and how to
    fetch today's live log."""
    today = datetime.date.today()
    instructions = []

    for i in range(days, 0, -1):
        date = today - datetime.timedelta(days=i)
        url = irc_log_url(date)

        if verbose:
            print(f"  [cache] Fetching IRC log for {date}...")

        content, path = fetch_and_cache(url)
        if content and path:
            instructions.append(
                f"- {date}: CACHED — Read the file at {path.resolve()} "
                f"(do NOT fetch this URL, the file is already on disk)"
            )
        else:
            instructions.append(
                f"- {date}: Fetch failed during pre-cache. "
                f"Try WebFetch: {url}"
            )

    today_url = irc_log_url(today)
    instructions.append(
        f"- {today} (today): LIVE — use WebFetch to get {today_url} "
        f"(today's log is still being written, do not cache)"
    )

    return "\n".join(instructions)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def build_system_prompt(days: int, sources: list[str],
                        gerrit_user: str | None = None,
                        lp_user: str | None = None,
                        verbose: bool = False) -> str:
    today = datetime.date.today().isoformat()
    fmt = dict(days=days, today=today, user=gerrit_user or "", lp_user=lp_user or "")

    parts = [SYSTEM_PROMPT_HEADER.format(**fmt)]
    output_parts = [f"\n═══ OUTPUT FORMAT ═══\n\n# Octavia PTL Daily Briefing — {today}\n"]

    release_name = ""

    for name in sources:
        src_template, out = ALL_SOURCES[name]

        if name == "irc":
            irc_instructions = prefetch_irc_logs(days, verbose=verbose)
            src = src_template.format(
                channel=IRC_CHANNEL, irc_instructions=irc_instructions, **fmt
            )
        elif name == "gerrit":
            gerrit_path = fetch_gerrit_data(days, CACHE_DIR, verbose=verbose)
            src = src_template.format(gerrit_data_path=gerrit_path.resolve(), **fmt)
        elif name == "zuul":
            zuul_path = fetch_zuul_data(days, CACHE_DIR, verbose=verbose)
            src = src_template.format(zuul_data_path=zuul_path.resolve(), **fmt)
        elif name == "launchpad":
            lp_path = fetch_launchpad_data(days, CACHE_DIR, verbose=verbose)
            src = src_template.format(launchpad_data_path=lp_path.resolve(), **fmt)
        elif name == "schedule":
            sched_path = fetch_schedule_data(CACHE_DIR, verbose=verbose)
            sched_data = json.loads(sched_path.read_text())
            release_name = sched_data.get("release_name", "unknown")
            src = src_template.format(schedule_data_path=sched_path.resolve(), **fmt)
        elif name == "mailinglist":
            ml_path = fetch_mailinglist_data(days, CACHE_DIR, verbose=verbose)
            src = src_template.format(mailinglist_data_path=ml_path.resolve(), **fmt)
        elif name == "activity":
            if not gerrit_user:
                if verbose:
                    print("  [activity] Skipped — no --gerrit-user provided")
                continue
            act_path = fetch_gerrit_activity_data(gerrit_user, days, CACHE_DIR, verbose=verbose)
            src = src_template.format(activity_data_path=act_path.resolve(), **fmt)
        elif name == "lp-activity":
            if not lp_user:
                if verbose:
                    print("  [lp-activity] Skipped — no --lp-user provided")
                continue
            lp_act_path = fetch_launchpad_activity_data(lp_user, days, CACHE_DIR, verbose=verbose)
            src = src_template.format(lp_activity_data_path=lp_act_path.resolve(), **fmt)
        else:
            src = src_template.format(**fmt)

        parts.append(src)
        output_parts.append(out.format(
            channel=IRC_CHANNEL, release_name=release_name, **fmt
        ))

    output_parts.append(OUTPUT_FOOTER)
    return "\n".join(parts) + "\n".join(output_parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Octavia PTL daily briefing agent."
    )
    parser.add_argument(
        "prompt", nargs="*", default=None,
        help="Optional follow-up question to append to the briefing request",
    )
    parser.add_argument("--model", "-m", default="claude-sonnet-4-6", help="Model ID (default: claude-sonnet-4-6)")
    parser.add_argument(
        "--days", "-d", type=int, default=1,
        help="How many days back to look (default: 1)",
    )
    parser.add_argument(
        "--max-turns", "-t", type=int, default=15,
        help="Max agentic turns (default: 15)",
    )
    parser.add_argument(
        "--sources", "-s", nargs="+",
        choices=list(ALL_SOURCES.keys()), default=list(ALL_SOURCES.keys()),
        help="Sources to include (default: all). Choices: gerrit, zuul, launchpad, irc",
    )
    parser.add_argument(
        "--gerrit-user", default=None,
        help="Gerrit username for personal activity tracking (patches, reviews, comments)",
    )
    parser.add_argument(
        "--lp-user", default=None,
        help="Launchpad username for personal bug activity (reported, assigned)",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Write briefing to a file (markdown)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show tool calls and thinking",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

def print_stats(console: Console, message: ResultMessage, elapsed: float, verbose: bool):
    cost = getattr(message, "total_cost_usd", None)
    usage = getattr(message, "usage", {})
    model_usage = getattr(message, "model_usage", {})

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()

    table.add_row("Status", message.subtype)
    table.add_row("Wall time", f"{elapsed:.1f}s")

    if cost is not None:
        table.add_row("Total cost", f"${cost:.4f}")

    if usage:
        input_t = usage.get("input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_create = usage.get("cache_creation_input_tokens", 0)
        output_t = usage.get("output_tokens", 0)
        total_in = input_t + cache_read + cache_create
        table.add_row(
            "Tokens",
            f"{total_in:,} in ({cache_read:,} cache read, {cache_create:,} cache write) / {output_t:,} out",
        )

    if model_usage:
        for model_name, mu in model_usage.items():
            m_in = mu.get("inputTokens", 0)
            m_out = mu.get("outputTokens", 0)
            m_cache_read = mu.get("cacheReadInputTokens", 0)
            m_cost = mu.get("costUSD", None)
            cost_str = f" (${m_cost:.4f})" if m_cost is not None else ""
            table.add_row(
                f"  {model_name}",
                f"{m_in:,} in ({m_cache_read:,} cache read) / {m_out:,} out{cost_str}",
            )

    console.print(Panel(table, title="Agent Stats", border_style="blue"))


SDK_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_USE_VERTEX",
    "CLOUD_ML_REGION",
    "ANTHROPIC_VERTEX_PROJECT_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_MAX_MODEL",
]


def print_env_check(console: Console):
    table = Table(title="SDK Environment", show_header=True, border_style="dim")
    table.add_column("Variable", style="bold")
    table.add_column("Value")
    for var in SDK_ENV_VARS:
        val = os.environ.get(var)
        if val is None:
            table.add_row(var, "[dim]not set[/dim]")
        elif "KEY" in var or "CREDENTIALS" in var:
            table.add_row(var, f"[green]{val[:8]}...({len(val)} chars)[/green]")
        else:
            table.add_row(var, f"[green]{val}[/green]")
    console.print(table)
    console.print()


async def run_briefing(args):
    console = Console()

    if args.verbose:
        print_env_check(console)

    system_prompt = build_system_prompt(args.days, args.sources,
                                           gerrit_user=args.gerrit_user,
                                           lp_user=args.lp_user,
                                           verbose=args.verbose)

    user_prompt = "Generate my Octavia PTL daily briefing."
    if args.prompt:
        user_prompt += f" Also: {' '.join(args.prompt)}"

    options = ClaudeAgentOptions(
        model=args.model,
        system_prompt=system_prompt,
        allowed_tools=["WebFetch", "WebSearch", "Bash", "Read"],
        max_turns=args.max_turns,
    )

    start = time.monotonic()
    briefing_parts: list[str] = []

    async for message in query(prompt=user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    briefing_parts.append(block.text)
                    console.print(Markdown(block.text))
                elif isinstance(block, ThinkingBlock) and args.verbose:
                    console.print(
                        Panel(block.thinking, title="Thinking", border_style="yellow", expand=False)
                    )
                elif isinstance(block, ToolUseBlock) and args.verbose:
                    console.print(f"  [dim]> {block.name}({block.input})[/dim]")

        elif isinstance(message, ResultMessage):
            elapsed = time.monotonic() - start
            print_stats(console, message, elapsed, args.verbose)

    briefing_text = "\n".join(briefing_parts)

    if args.output:
        Path(args.output).write_text(briefing_text)
        console.print(f"\nBriefing saved to [bold]{args.output}[/bold]")


def main_cli():
    asyncio.run(run_briefing(parse_args()))


if __name__ == "__main__":
    main_cli()
