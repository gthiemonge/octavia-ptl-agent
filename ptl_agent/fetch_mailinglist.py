# Copyright (c) 2026 Gregory Thiemonge
# SPDX-License-Identifier: MIT

"""Pre-fetch and filter openstack-discuss mailing list threads.

Downloads the mbox archive for the requested date range, parses it, and
extracts threads matching Octavia, PTL tags, or general community topics.
Writes a compact JSON summary to disk.
"""

import datetime
import email.utils
import gzip
import json
import mailbox
import re
import tempfile
import urllib.request
from pathlib import Path

LIST_ID = "openstack-discuss@lists.openstack.org"
EXPORT_URL = (
    "https://lists.openstack.org/archives/list/{list_id}"
    "/export/{list_id}-{start}-{end}.mbox.gz"
    "?start={start}&end={end}"
)

OCTAVIA_RE = re.compile(r"\[octavia\]", re.IGNORECASE)
PTL_RE = re.compile(r"\[ptl\]", re.IGNORECASE)
TAG_RE = re.compile(r"\[([^\]]+)\]")


def fetch_mbox(start: str, end: str) -> bytes | None:
    url = EXPORT_URL.format(list_id=LIST_ID, start=start, end=end)
    req = urllib.request.Request(url, headers={"User-Agent": "ptl-agent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except Exception as e:
        print(f"  [mailinglist] Failed to fetch mbox: {e}")
        return None


def parse_date(date_str: str | None) -> datetime.datetime | None:
    if not date_str:
        return None
    parsed = email.utils.parsedate_to_datetime(date_str)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def extract_tags(subject: str) -> list[str]:
    return [m.group(1) for m in TAG_RE.finditer(subject)]


def strip_re(subject: str) -> str:
    return re.sub(r"^(Re:\s*)+", "", subject, flags=re.IGNORECASE).strip()


def extract_message(msg: mailbox.mboxMessage) -> dict | None:
    subject = msg.get("Subject", "")
    if not subject:
        return None
    from_addr = msg.get("From", "")
    name, addr = email.utils.parseaddr(from_addr)
    date = parse_date(msg.get("Date"))
    message_id = msg.get("Message-ID", "")
    in_reply_to = msg.get("In-Reply-To", "")
    tags = extract_tags(subject)
    base_subject = strip_re(subject)

    return {
        "subject": subject,
        "base_subject": base_subject,
        "from_name": name or addr,
        "from_addr": addr,
        "date": date.isoformat() if date else None,
        "message_id": message_id.strip(),
        "in_reply_to": in_reply_to.strip(),
        "tags": tags,
    }


def classify_message(msg: dict) -> list[str]:
    categories = []
    subject = msg["subject"]
    if OCTAVIA_RE.search(subject):
        categories.append("octavia")
    if PTL_RE.search(subject):
        categories.append("ptl")
    if not categories:
        categories.append("general")
    return categories


def group_threads(messages: list[dict]) -> list[dict]:
    threads: dict[str, dict] = {}

    for msg in messages:
        base = msg["base_subject"]
        if base not in threads:
            threads[base] = {
                "subject": base,
                "tags": [],
                "categories": set(),
                "message_count": 0,
                "participants": set(),
                "first_date": msg["date"],
                "last_date": msg["date"],
                "url": None,
            }
        t = threads[base]
        t["message_count"] += 1
        t["participants"].add(msg["from_name"])
        for tag in msg["tags"]:
            if tag not in t["tags"]:
                t["tags"].append(tag)
        t["categories"].update(classify_message(msg))
        if msg["date"]:
            if t["first_date"] is None or msg["date"] < t["first_date"]:
                t["first_date"] = msg["date"]
            if t["last_date"] is None or msg["date"] > t["last_date"]:
                t["last_date"] = msg["date"]

    result = []
    for t in threads.values():
        t["participants"] = sorted(t["participants"])
        t["categories"] = sorted(t["categories"])
        result.append(t)

    result.sort(key=lambda t: t["last_date"] or "", reverse=True)
    return result


def summarize(threads: list[dict]) -> dict:
    octavia = [t for t in threads if "octavia" in t["categories"]]
    ptl = [t for t in threads if "ptl" in t["categories"]]
    general = [t for t in threads if "general" in t["categories"]]

    return {
        "total_threads": len(threads),
        "total_messages": sum(t["message_count"] for t in threads),
        "octavia_threads": len(octavia),
        "ptl_threads": len(ptl),
        "general_threads": len(general),
    }


def fetch_mailinglist_data(days: int, cache_dir: Path, verbose: bool = False) -> Path:
    cache_dir.mkdir(exist_ok=True)
    output_path = cache_dir / "mailinglist.json"

    today = datetime.date.today()
    start = today - datetime.timedelta(days=days)
    end = today + datetime.timedelta(days=1)

    if verbose:
        print(f"  [mailinglist] Fetching openstack-discuss archive {start} to {end}...")

    raw = fetch_mbox(start.isoformat(), end.isoformat())
    if not raw:
        result = {
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "days": days,
            "error": "Failed to fetch mbox archive",
            "summary": {"total_threads": 0, "total_messages": 0,
                        "octavia_threads": 0, "ptl_threads": 0, "general_threads": 0},
            "octavia_threads": [],
            "ptl_threads": [],
            "general_threads": [],
        }
        output_path.write_text(json.dumps(result, indent=2))
        return output_path

    decompressed = gzip.decompress(raw)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mbox") as tmp:
        tmp.write(decompressed)
        tmp_path = tmp.name

    mbox = mailbox.mbox(tmp_path)
    messages = []
    for msg in mbox:
        extracted = extract_message(msg)
        if extracted:
            messages.append(extracted)
    Path(tmp_path).unlink()

    threads = group_threads(messages)
    summary = summarize(threads)

    octavia_threads = [t for t in threads if "octavia" in t["categories"]]
    ptl_threads = [t for t in threads if "ptl" in t["categories"]]
    general_threads = [t for t in threads if "general" in t["categories"]]

    result = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "days": days,
        "summary": summary,
        "octavia_threads": octavia_threads,
        "ptl_threads": ptl_threads,
        "general_threads": general_threads,
    }

    output_path.write_text(json.dumps(result, indent=2))

    if verbose:
        print(
            f"  [mailinglist] {summary['total_messages']} message(s) in {summary['total_threads']} thread(s) "
            f"({summary['octavia_threads']} octavia, {summary['ptl_threads']} ptl, "
            f"{summary['general_threads']} general), saved to {output_path}"
        )

    return output_path
