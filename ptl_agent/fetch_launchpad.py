# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Pre-fetch and filter Launchpad bug data for the Octavia project.

Fetches open bug tasks from the Launchpad API, extracts only the fields
relevant to a PTL briefing, and writes a compact JSON summary to disk.
"""

import datetime
import json
import urllib.parse
import urllib.request
from pathlib import Path

LAUNCHPAD_API = "https://api.launchpad.net/devel/octavia"


def fetch_bug_tasks(statuses: list[str] | None = None, size: int = 50) -> list[dict]:
    if statuses is None:
        statuses = ["New", "Confirmed", "Triaged", "In Progress"]
    params = "&".join(f"status={urllib.parse.quote(s)}" for s in statuses)
    url = f"{LAUNCHPAD_API}?ws.op=searchTasks&{params}&ws.size={size}"
    req = urllib.request.Request(url, headers={"User-Agent": "ptl-agent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("entries", [])
    except Exception as e:
        print(f"  [launchpad] Failed to fetch bugs: {e}")
        return []


def extract_assignee(assignee_link: str | None) -> str:
    if not assignee_link:
        return "unassigned"
    # Link format: https://api.launchpad.net/devel/~username
    return assignee_link.rsplit("~", 1)[-1] if "~" in assignee_link else "unassigned"


def extract_bug(entry: dict) -> dict:
    return {
        "title": entry.get("title"),
        "status": entry.get("status"),
        "importance": entry.get("importance"),
        "assignee": extract_assignee(entry.get("assignee_link")),
        "date_created": entry.get("date_created"),
        "date_triaged": entry.get("date_triaged"),
        "web_link": entry.get("web_link"),
    }


def filter_new_bugs(bugs: list[dict], days: int) -> list[dict]:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    new = []
    for b in bugs:
        created = b.get("date_created")
        if not created:
            continue
        try:
            ts = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            if ts >= cutoff:
                new.append(b)
        except ValueError:
            pass
    return new


def summarize(bugs: list[dict], days: int) -> dict:
    by_status: dict[str, int] = {}
    by_importance: dict[str, int] = {}
    critical_high = []

    for b in bugs:
        status = b.get("status", "Unknown")
        importance = b.get("importance", "Unknown")
        by_status[status] = by_status.get(status, 0) + 1
        by_importance[importance] = by_importance.get(importance, 0) + 1
        if importance in ("Critical", "High"):
            critical_high.append(b)

    new_bugs = filter_new_bugs(bugs, days)

    return {
        "total_open": len(bugs),
        "by_status": dict(sorted(by_status.items(), key=lambda x: -x[1])),
        "by_importance": dict(sorted(by_importance.items(), key=lambda x: -x[1])),
        "critical_high_count": len(critical_high),
        "new_in_period": len(new_bugs),
    }


def fetch_launchpad_data(days: int, cache_dir: Path, verbose: bool = False) -> Path:
    """Fetch, filter, and save Launchpad data. Returns path to the output file."""
    cache_dir.mkdir(exist_ok=True)
    output_path = cache_dir / "launchpad_bugs.json"

    if verbose:
        print("  [launchpad] Fetching open bugs for octavia...")

    raw_entries = fetch_bug_tasks()
    bugs = [extract_bug(e) for e in raw_entries]
    new_bugs = filter_new_bugs(bugs, days)
    critical_high = [b for b in bugs if b.get("importance") in ("Critical", "High")]
    summary = summarize(bugs, days)

    result = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "days": days,
        "summary": summary,
        "new_bugs": new_bugs,
        "critical_high": critical_high,
        "all_open": bugs,
    }

    output_path.write_text(json.dumps(result, indent=2))

    if verbose:
        n = len(bugs)
        print(f"  [launchpad] {n} open bug(s), {len(new_bugs)} new in the last {days} day(s), saved to {output_path}")

    return output_path
