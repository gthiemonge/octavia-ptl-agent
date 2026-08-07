# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Pre-fetch and filter Zuul CI build data for Octavia team projects.

Fetches failure data from the Zuul API, extracts only the fields relevant
to a PTL briefing, and writes a compact JSON summary to disk.
"""

import datetime
import json
import urllib.request
from pathlib import Path

ZUUL_API = "https://zuul.opendev.org/api/tenant/openstack/builds"

OCTAVIA_PROJECTS = [
    "openstack/octavia",
    "openstack/octavia-tempest-plugin",
    "openstack/octavia-lib",
    "openstack/python-octaviaclient",
    "openstack/octavia-dashboard",
]


def fetch_builds(project: str, result: str = "FAILURE", limit: int = 20) -> list[dict]:
    url = f"{ZUUL_API}?project={project}&result={result}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "ptl-agent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [zuul] Failed to fetch {project}: {e}")
        return []


def extract_build(build: dict) -> dict:
    ref = build.get("ref", {})
    return {
        "job": build.get("job_name"),
        "result": build.get("result"),
        "pipeline": build.get("pipeline"),
        "voting": build.get("voting"),
        "project": ref.get("project"),
        "branch": ref.get("branch"),
        "change": ref.get("change"),
        "patchset": ref.get("patchset"),
        "start_time": build.get("start_time"),
        "duration_s": build.get("duration"),
        "log_url": build.get("log_url"),
        "review_url": ref.get("ref_url"),
    }


def filter_by_days(builds: list[dict], days: int) -> list[dict]:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    filtered = []
    for b in builds:
        start = b.get("start_time")
        if not start:
            continue
        try:
            ts = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            if ts >= cutoff:
                filtered.append(b)
        except ValueError:
            filtered.append(b)
    return filtered


def summarize(builds: list[dict]) -> dict:
    """Produce a summary with failure counts by job and by project."""
    by_job: dict[str, int] = {}
    by_project: dict[str, int] = {}
    gate_failures = []

    for b in builds:
        job = b.get("job", "unknown")
        project = b.get("project", "unknown")
        by_job[job] = by_job.get(job, 0) + 1
        by_project[project] = by_project.get(project, 0) + 1
        if b.get("pipeline") == "gate":
            gate_failures.append(b)

    return {
        "total_failures": len(builds),
        "failures_by_job": dict(sorted(by_job.items(), key=lambda x: -x[1])),
        "failures_by_project": dict(sorted(by_project.items(), key=lambda x: -x[1])),
        "gate_failures": gate_failures,
    }


def fetch_zuul_data(days: int, cache_dir: Path, verbose: bool = False) -> Path:
    """Fetch, filter, and save Zuul data. Returns path to the output file."""
    cache_dir.mkdir(exist_ok=True)
    output_path = cache_dir / "zuul_failures.json"

    all_builds = []
    for project in OCTAVIA_PROJECTS:
        if verbose:
            print(f"  [zuul] Fetching failures for {project}...")
        raw = fetch_builds(project)
        extracted = [extract_build(b) for b in raw]
        all_builds.extend(extracted)

    filtered = filter_by_days(all_builds, days)
    summary = summarize(filtered)

    result = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "days": days,
        "projects": OCTAVIA_PROJECTS,
        "summary": summary,
        "builds": filtered,
    }

    output_path.write_text(json.dumps(result, indent=2))

    if verbose:
        n = len(filtered)
        print(f"  [zuul] {n} failure(s) in the last {days} day(s), saved to {output_path}")

    return output_path
