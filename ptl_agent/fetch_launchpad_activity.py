# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Pre-fetch personal Launchpad bug activity for the PTL.

Fetches bugs reported by and assigned to a specific user in the Octavia
project, and writes a compact JSON summary to disk.
"""

import datetime
import json
import urllib.request
from pathlib import Path

from ptl_agent.fetch_launchpad import LAUNCHPAD_API, extract_bug, filter_new_bugs

LP_PERSON_URL = "https://api.launchpad.net/devel/~{user}"


def fetch_user_bugs(user: str, role: str, size: int = 50) -> list[dict]:
    person_url = LP_PERSON_URL.format(user=user)
    url = f"{LAUNCHPAD_API}?ws.op=searchTasks&{role}={person_url}&ws.size={size}"
    req = urllib.request.Request(url, headers={"User-Agent": "ptl-agent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("entries", [])
    except Exception as e:
        print(f"  [lp-activity] Failed to fetch {role} bugs for {user}: {e}")
        return []


def fetch_launchpad_activity_data(user: str, days: int, cache_dir: Path,
                                  verbose: bool = False) -> Path:
    cache_dir.mkdir(exist_ok=True)
    output_path = cache_dir / "launchpad_activity.json"

    if verbose:
        print(f"  [lp-activity] Fetching bug activity for {user}...")

    reported_raw = fetch_user_bugs(user, "bug_reporter")
    reported = [extract_bug(e) for e in reported_raw]
    recently_reported = filter_new_bugs(reported, days)

    assigned_raw = fetch_user_bugs(user, "assignee")
    assigned = [extract_bug(e) for e in assigned_raw]
    recently_assigned = filter_new_bugs(assigned, days)

    summary = {
        "reported_count": len(reported),
        "reported_recent": len(recently_reported),
        "assigned_count": len(assigned),
        "assigned_recent": len(recently_assigned),
    }

    result = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "user": user,
        "days": days,
        "summary": summary,
        "reported": reported,
        "recently_reported": recently_reported,
        "assigned": assigned,
        "recently_assigned": recently_assigned,
    }

    output_path.write_text(json.dumps(result, indent=2))

    if verbose:
        print(
            f"  [lp-activity] {summary['reported_count']} reported "
            f"({summary['reported_recent']} recent), "
            f"{summary['assigned_count']} assigned "
            f"({summary['assigned_recent']} recent), "
            f"saved to {output_path}"
        )

    return output_path
