# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Pre-fetch personal Gerrit activity for the PTL.

Fetches patches authored, reviews given, and comments posted by a specific
user across all Octavia projects, and writes a compact JSON summary to disk.
"""

import datetime
import json
from pathlib import Path

from ptl_agent.fetch_gerrit import (
    GERRIT_API,
    OCTAVIA_PROJECTS,
    extract_change,
    fetch_changes,
)


def fetch_user_changes(user: str, project: str, days: int, query_extra: str = "",
                       limit: int = 50) -> list[dict]:
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=days))
    after = cutoff.strftime("%Y-%m-%d")
    q = f"project:{project}+{query_extra}+after:{after}"
    url = (
        f"{GERRIT_API}?q={q}"
        f"&o=DETAILED_ACCOUNTS&o=CURRENT_REVISION&o=CURRENT_COMMIT&o=LABELS&n={limit}"
    )
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "ptl-agent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
        if raw.startswith(")]}'"):
            raw = raw[4:].lstrip("\n")
        return json.loads(raw)
    except Exception as e:
        print(f"  [activity] Failed to fetch {project} ({query_extra}): {e}")
        return []


def fetch_gerrit_activity_data(user: str, days: int, cache_dir: Path,
                               verbose: bool = False) -> Path:
    cache_dir.mkdir(exist_ok=True)
    output_path = cache_dir / "gerrit_activity.json"

    patches = []
    reviews = []
    comments = []
    seen_review_ids = set()

    for project in OCTAVIA_PROJECTS:
        if verbose:
            print(f"  [activity] Fetching activity for {user} on {project}...")

        for raw in fetch_user_changes(user, project, days, f"owner:{user}"):
            patches.append(extract_change(raw))

        for raw in fetch_user_changes(user, project, days, f"reviewer:{user}+-owner:{user}"):
            c = extract_change(raw)
            seen_review_ids.add(c["number"])
            reviews.append(c)

        for raw in fetch_user_changes(user, project, days, f"commentby:{user}+-owner:{user}"):
            c = extract_change(raw)
            if c["number"] not in seen_review_ids:
                comments.append(c)

    patches.sort(key=lambda c: c.get("updated", ""), reverse=True)
    reviews.sort(key=lambda c: c.get("updated", ""), reverse=True)
    comments.sort(key=lambda c: c.get("updated", ""), reverse=True)

    summary = {
        "patches_count": len(patches),
        "reviews_count": len(reviews),
        "comments_count": len(comments),
    }

    result = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "user": user,
        "days": days,
        "projects": OCTAVIA_PROJECTS,
        "summary": summary,
        "patches": patches,
        "reviews": reviews,
        "comments": comments,
    }

    output_path.write_text(json.dumps(result, indent=2))

    if verbose:
        print(
            f"  [activity] {summary['patches_count']} patch(es), "
            f"{summary['reviews_count']} review(s), "
            f"{summary['comments_count']} comment(s) "
            f"in the last {days} day(s), saved to {output_path}"
        )

    return output_path
