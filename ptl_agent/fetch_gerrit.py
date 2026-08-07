# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Pre-fetch and filter Gerrit review data for Octavia team projects.

Fetches open reviews from the Gerrit API, extracts only the fields relevant
to a PTL briefing, and writes a compact JSON summary to disk.
"""

import datetime
import json
import urllib.request
from pathlib import Path

GERRIT_API = "https://review.opendev.org/changes/"

OCTAVIA_PROJECTS = [
    "openstack/octavia",
    "openstack/octavia-tempest-plugin",
    "openstack/octavia-lib",
    "openstack/python-octaviaclient",
    "openstack/octavia-dashboard",
]


def fetch_changes(project: str, status: str = "open", limit: int = 30) -> list[dict]:
    url = (
        f"{GERRIT_API}?q=project:{project}+status:{status}"
        f"&o=DETAILED_ACCOUNTS&o=CURRENT_REVISION&o=CURRENT_COMMIT&o=LABELS&n={limit}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "ptl-agent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
        # Gerrit prefixes responses with )]}'
        if raw.startswith(")]}'"):
            raw = raw[4:].lstrip("\n")
        return json.loads(raw)
    except Exception as e:
        print(f"  [gerrit] Failed to fetch {project}: {e}")
        return []


def extract_labels(labels: dict) -> dict:
    """Extract vote summary for Code-Review and Workflow labels."""
    result = {}
    for label_name in ("Code-Review", "Workflow"):
        label = labels.get(label_name, {})
        votes = label.get("all", [])
        vote_values = [v.get("value", 0) for v in votes if v.get("value") is not None]
        result[label_name] = {
            "min": min(vote_values) if vote_values else 0,
            "max": max(vote_values) if vote_values else 0,
        }
    return result


def extract_change(change: dict) -> dict:
    owner = change.get("owner", {})
    labels = extract_labels(change.get("labels", {}))

    cr = labels.get("Code-Review", {})
    wf = labels.get("Workflow", {})

    if cr.get("min", 0) <= -1 or wf.get("min", 0) <= -1:
        review_state = "negative"
    elif cr.get("max", 0) >= 2 or wf.get("max", 0) >= 1:
        review_state = "approved"
    else:
        review_state = "needs-review"

    return {
        "number": change.get("_number"),
        "project": change.get("project"),
        "branch": change.get("branch"),
        "subject": change.get("subject"),
        "status": change.get("status"),
        "owner": owner.get("name") or owner.get("username", "unknown"),
        "created": change.get("created"),
        "updated": change.get("updated"),
        "insertions": change.get("insertions"),
        "deletions": change.get("deletions"),
        "code_review": cr,
        "workflow": wf,
        "review_state": review_state,
        "unresolved_comments": change.get("unresolved_comment_count", 0),
        "url": f"https://review.opendev.org/c/{change.get('project')}/+/{change.get('_number')}",
    }


def filter_by_days(changes: list[dict], days: int) -> list[dict]:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    recent = []
    for c in changes:
        updated = c.get("updated")
        if not updated:
            continue
        try:
            ts = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            if ts >= cutoff:
                recent.append(c)
        except ValueError:
            recent.append(c)
    return recent


def summarize(changes: list[dict]) -> dict:
    needs_review = [c for c in changes if c["review_state"] == "needs-review"]
    approved = [c for c in changes if c["review_state"] == "approved"]
    negative = [c for c in changes if c["review_state"] == "negative"]

    by_project: dict[str, int] = {}
    for c in changes:
        p = c.get("project", "unknown")
        by_project[p] = by_project.get(p, 0) + 1

    return {
        "total_open": len(changes),
        "needs_review": len(needs_review),
        "approved": len(approved),
        "negative": len(negative),
        "by_project": dict(sorted(by_project.items(), key=lambda x: -x[1])),
    }


def fetch_gerrit_data(days: int, cache_dir: Path, verbose: bool = False) -> Path:
    """Fetch, filter, and save Gerrit data. Returns path to the output file."""
    cache_dir.mkdir(exist_ok=True)
    output_path = cache_dir / "gerrit_reviews.json"

    all_changes = []
    for project in OCTAVIA_PROJECTS:
        if verbose:
            print(f"  [gerrit] Fetching open reviews for {project}...")
        raw = fetch_changes(project)
        extracted = [extract_change(c) for c in raw]
        all_changes.extend(extracted)

    recently_updated = filter_by_days(all_changes, days)

    # Sort: needs-review first (oldest updated first), then negative, then approved
    order = {"needs-review": 0, "negative": 1, "approved": 2}
    all_changes.sort(key=lambda c: (order.get(c["review_state"], 9), c.get("updated", "")))

    summary = summarize(all_changes)

    result = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "days": days,
        "projects": OCTAVIA_PROJECTS,
        "summary": summary,
        "recently_updated": recently_updated,
        "all_open": all_changes,
    }

    output_path.write_text(json.dumps(result, indent=2))

    if verbose:
        n = len(all_changes)
        r = len(recently_updated)
        print(f"  [gerrit] {n} open review(s), {r} updated in the last {days} day(s), saved to {output_path}")

    return output_path
