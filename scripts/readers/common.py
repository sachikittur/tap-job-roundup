"""Shared shape and helpers for the ATS readers.

Every reader returns a list of Posting objects with the same fields, so the
rest of the pipeline never needs to know which ATS a job came from.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Location:
    raw: str = ""          # as the ATS wrote it, e.g. "Vancouver, BC" or "Remote - Canada"
    city: str = ""
    region: str = ""       # province or state, any spelling
    country: str = ""      # any spelling: "CA", "Canada", "ca"
    remote: bool = False


@dataclass
class Posting:
    title: str
    company: str
    url: str
    locations: list[Location] = field(default_factory=list)
    remote: bool = False
    employment_type: str = ""
    date_posted: str = ""   # YYYY-MM-DD
    description: str = ""   # plain text
    ats: str = ""


def clean_text(raw: str | None) -> str:
    """HTML (possibly entity-escaped, as Greenhouse sends it) to plain text."""
    if not raw:
        return ""
    text = html.unescape(raw)
    if "&lt;" in raw or "&gt;" in raw:  # double-escaped
        text = html.unescape(text)
    text = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def to_date(value) -> str:
    """ISO string, YYYY-MM-DD, or epoch milliseconds to YYYY-MM-DD."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return str(value)[:10]


def says_remote(*texts: str) -> bool:
    return any(t and re.search(r"\bremote\b", t, re.I) for t in texts)
