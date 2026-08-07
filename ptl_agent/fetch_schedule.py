# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Pre-fetch and filter OpenStack release schedule data.

Scrapes the current development release schedule page and extracts
milestones and deadlines relevant to an Octavia PTL.
"""

import datetime
import json
import re
import urllib.request
from pathlib import Path

RELEASES_INDEX = "https://releases.openstack.org/"

PTL_RELEVANT_KEYWORDS = [
    "milestone",
    "feature freeze",
    "spec freeze",
    "rc1",
    "final rc",
    "release",
    "library",
    "client",
    "string freeze",
    "requirements freeze",
    "election",
    "extra-ac",
    "membership freeze",
    "project team gathering",
    "cycle highlights",
]


def find_current_release(verbose: bool = False) -> tuple[str, str]:
    """Find the current development release name and schedule URL."""
    req = urllib.request.Request(RELEASES_INDEX, headers={"User-Agent": "ptl-agent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode()
    except Exception as e:
        if verbose:
            print(f"  [schedule] Failed to fetch releases index: {e}")
        return "", ""

    # Look for the development release link pattern
    # e.g., <a href="hibiscus/schedule.html">
    match = re.search(
        r'(?:Development|development).*?href=["\'](\w+)/schedule\.html["\']',
        html, re.DOTALL | re.IGNORECASE,
    )
    if not match:
        # Try reverse: link then "Development"
        match = re.search(
            r'href=["\'](\w+)/schedule\.html["\'].*?Development',
            html, re.DOTALL | re.IGNORECASE,
        )
    if match:
        name = match.group(1)
        url = f"{RELEASES_INDEX}{name}/schedule.html"
        return name, url

    if verbose:
        print("  [schedule] Could not find current development release")
    return "", ""


def parse_date(text: str) -> datetime.date | None:
    """Try to parse various date formats from the schedule page."""
    text = text.strip().rstrip(",").strip()
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Try "Week of Mon DD-DD, YYYY" — take the first date
    m = re.match(r"Week of \w+ (\d+)[-–](\d+),?\s*(\d{4})", text)
    if m:
        day = int(m.group(1))
        year = int(m.group(3))
        # Need month — search in original text
        month_match = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*", text)
        if month_match:
            month_str = month_match.group(0)[:3]
            try:
                month = datetime.datetime.strptime(month_str, "%b").month
                return datetime.date(year, month, day)
            except ValueError:
                pass
    return None


def fetch_schedule_page(url: str, verbose: bool = False) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ptl-agent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode()
    except Exception as e:
        if verbose:
            print(f"  [schedule] Failed to fetch schedule page: {e}")
        return ""


def extract_events_from_html(html: str) -> list[dict]:
    """Extract date-event pairs from the schedule HTML table.

    The table has rows like:
      <tr><td>Aug 24 - Aug 28</td><td>R-5</td><td><ul><li>Event 1</li>...</ul></td></tr>
    We parse the week date from the first cell and event names from <li> tags
    in any subsequent cell.
    """
    events = []

    # Split into table rows
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if not cells:
            continue

        # First cell has the week date range, e.g. "Aug 24 - Aug 28"
        date_text = re.sub(r"<[^>]+>", "", cells[0]).strip()
        date = parse_week_range(date_text)
        if not date:
            continue

        # Events are in <li> tags across remaining cells
        row_html = " ".join(cells[1:])
        items = re.findall(r"<li[^>]*>(.*?)</li>", row_html, re.DOTALL)
        for item in items:
            event_text = re.sub(r"<[^>]+>", "", item).strip()
            if event_text:
                events.append({
                    "date": date.isoformat(),
                    "week": date_text,
                    "event": event_text,
                })

    return events


def parse_week_range(text: str) -> datetime.date | None:
    """Parse 'Mon DD - Mon DD' week range, returning the Monday date.

    Infers year from context (current or next year). Examples:
      'Aug 24 - Aug 28' -> 2026-08-24
      'Mar 30 - Apr 03' -> 2027-03-30
    """
    m = re.match(r"(\w{3})\s+(\d{1,2})\s*-\s*\w{3}\s+\d{1,2}", text)
    if not m:
        return None
    month_str = m.group(1)
    day = int(m.group(2))
    try:
        month = datetime.datetime.strptime(month_str, "%b").month
    except ValueError:
        return None

    today = datetime.date.today()
    # Try current year first, then next year
    for year in (today.year, today.year + 1):
        try:
            return datetime.date(year, month, day)
        except ValueError:
            continue
    return None


def filter_relevant(events: list[dict]) -> list[dict]:
    """Keep only PTL-relevant events."""
    relevant = []
    for e in events:
        event_lower = e["event"].lower()
        if any(kw in event_lower for kw in PTL_RELEVANT_KEYWORDS):
            relevant.append(e)
    return relevant


def compute_reminders(events: list[dict], days_ahead: int = 30) -> dict:
    """Split events into past, upcoming, and far-future relative to today."""
    today = datetime.date.today()
    cutoff = today + datetime.timedelta(days=days_ahead)

    past = []
    upcoming = []
    future = []

    for e in events:
        try:
            d = datetime.date.fromisoformat(e["date"])
        except ValueError:
            continue

        entry = {**e, "days_from_today": (d - today).days}

        if d < today:
            past.append(entry)
        elif d <= cutoff:
            upcoming.append(entry)
        else:
            future.append(entry)

    return {
        "today": today.isoformat(),
        "past": past,
        "upcoming": upcoming,
        "future": future,
    }


def fetch_schedule_data(cache_dir: Path, verbose: bool = False) -> Path:
    """Fetch and process release schedule. Returns path to the output file."""
    cache_dir.mkdir(exist_ok=True)
    output_path = cache_dir / "release_schedule.json"

    release_name, schedule_url = find_current_release(verbose=verbose)
    if not schedule_url:
        # Write empty result
        output_path.write_text(json.dumps({"error": "Could not find current release schedule"}))
        return output_path

    if verbose:
        print(f"  [schedule] Current release: {release_name} ({schedule_url})")

    html = fetch_schedule_page(schedule_url, verbose=verbose)
    if not html:
        output_path.write_text(json.dumps({"error": "Could not fetch schedule page"}))
        return output_path

    all_events = extract_events_from_html(html)
    relevant = filter_relevant(all_events)
    reminders = compute_reminders(relevant)

    result = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "release_name": release_name,
        "schedule_url": schedule_url,
        "reminders": reminders,
        "all_relevant_events": relevant,
    }

    output_path.write_text(json.dumps(result, indent=2))

    if verbose:
        n_up = len(reminders["upcoming"])
        print(f"  [schedule] {len(relevant)} relevant events, {n_up} upcoming in next 30 days")

    return output_path
