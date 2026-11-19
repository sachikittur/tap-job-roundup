"""Known applicant tracking systems: how to spot them in HTML, parse a board
token from a URL, and build the public feed URL."""
from __future__ import annotations

import re

# ATS we have a feed reader for. Key = value used in the CSV's ATS column.
SUPPORTED = ("Greenhouse", "Lever", "Ashby", "Workable", "SmartRecruiters", "BambooHR")

# Path segments that look like tokens but are not.
_NOT_TOKENS = {
    "embed", "api", "v0", "v1", "j", "jobs", "job", "careers", "apply", "www", "static",
    "assets", "js", "css", "app", "widget", "posting-api", "job-board", "search", "login",
    "leverdemo", "demo", "example", "test",
}

TOKEN_PATTERNS: dict[str, list[re.Pattern]] = {
    "Greenhouse": [
        re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)", re.I),
        re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I),
        re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)", re.I),
    ],
    "Lever": [
        re.compile(r"jobs\.lever\.co/([A-Za-z0-9_.-]+)", re.I),
        re.compile(r"api\.lever\.co/v0/postings/([A-Za-z0-9_.-]+)", re.I),
    ],
    "Ashby": [
        re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)", re.I),
        re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.%-]+)", re.I),
    ],
    "Workable": [
        re.compile(r"apply\.workable\.com/api/v1/widget/accounts/([a-z0-9-]+)", re.I),
        re.compile(r"apply\.workable\.com/([a-z0-9-]+)", re.I),
        re.compile(r"//([a-z0-9-]+)\.workable\.com", re.I),
    ],
    "SmartRecruiters": [
        re.compile(r"api\.smartrecruiters\.com/v1/companies/([A-Za-z0-9_-]+)", re.I),
        re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I),
    ],
    "BambooHR": [
        re.compile(r"//([a-z0-9-]+)\.bamboohr\.com", re.I),
    ],
}

# ATS we can recognise but have no reader for: these become "Manual check".
UNSUPPORTED_PATTERNS: dict[str, re.Pattern] = {
    "Workday": re.compile(r"myworkdayjobs\.com|myworkdaysite\.com", re.I),
    "iCIMS": re.compile(r"\.icims\.com", re.I),
    "Jobvite": re.compile(r"jobs\.jobvite\.com|jobvite\.com/", re.I),
    "Recruitee": re.compile(r"\.recruitee\.com", re.I),
    "Breezy": re.compile(r"\.breezy\.hr", re.I),
    "Pinpoint": re.compile(r"\.pinpointhq\.com", re.I),
    "Rippling": re.compile(r"ats\.rippling\.com", re.I),
    "JazzHR": re.compile(r"\.applytojob\.com", re.I),
    "Teamtailor": re.compile(r"\.teamtailor\.com", re.I),
    "Dayforce": re.compile(r"dayforcehcm\.com", re.I),
    "ADP": re.compile(r"workforcenow\.adp\.com|recruiting\.adp\.com", re.I),
    "UKG": re.compile(r"ultipro\.com|ukg\.net", re.I),
    "SuccessFactors": re.compile(r"successfactors\.(?:com|eu)|jobs\.sap\.com", re.I),
    "Taleo": re.compile(r"taleo\.net", re.I),
    "Personio": re.compile(r"\.jobs\.personio\.", re.I),
    "Comeet": re.compile(r"comeet\.(?:com|co)/jobs", re.I),
    "Freshteam": re.compile(r"\.freshteam\.com", re.I),
    "Gem": re.compile(r"jobs\.gem\.com", re.I),
    "Dover": re.compile(r"app\.dover\.(?:io|com)/apply", re.I),
    "Collage": re.compile(r"collage\.co/jobs|secure\.collage\.co", re.I),
    "Humi": re.compile(r"humi\.ca/.*jobs|jobs\.humi\.ca", re.I),
}


def find_tokens(text: str) -> list[tuple[str, str]]:
    """Return (ats, token) pairs found in text, supported ATS only, in order found."""
    found: list[tuple[str, str]] = []
    for ats, patterns in TOKEN_PATTERNS.items():
        for pat in patterns:
            for m in pat.finditer(text):
                token = m.group(1).strip(".-_")
                if token and token.lower() not in _NOT_TOKENS and (ats, token) not in found:
                    found.append((ats, token))
    return found


def find_unsupported(text: str) -> list[str]:
    return [name for name, pat in UNSUPPORTED_PATTERNS.items() if pat.search(text)]


def normalise_ats(value: str) -> str:
    v = (value or "").strip().lower().replace(" ", "")
    for name in SUPPORTED:
        if v == name.lower():
            return name
    return (value or "").strip()


def parse_token(ats: str, value: str) -> str | None:
    """The CSV's feed column may hold a bare token or any URL containing one."""
    value = (value or "").strip()
    if not value:
        return None
    if "/" not in value and "." not in value:
        return value
    hits = [t for a, t in find_tokens(value) if a == ats]
    return hits[0] if hits else None


def feed_url(ats: str, token: str) -> str:
    return {
        "Greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
        "Lever": f"https://api.lever.co/v0/postings/{token}?mode=json",
        "Ashby": f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false",
        "Workable": f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true",
        "SmartRecruiters": f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100",
        "BambooHR": f"https://{token}.bamboohr.com/careers/list",
    }[ats]


def board_url(ats: str, token: str) -> str:
    """Human-friendly public board address, written to the CSV."""
    return {
        "Greenhouse": f"https://job-boards.greenhouse.io/{token}",
        "Lever": f"https://jobs.lever.co/{token}",
        "Ashby": f"https://jobs.ashbyhq.com/{token}",
        "Workable": f"https://apply.workable.com/{token}",
        "SmartRecruiters": f"https://careers.smartrecruiters.com/{token}",
        "BambooHR": f"https://{token}.bamboohr.com/careers",
    }[ats]


def count_jobs(ats: str, data) -> int | None:
    """Number of postings in a parsed feed response, or None if the shape is wrong."""
    try:
        if ats == "Greenhouse":
            return len(data["jobs"])
        if ats == "Lever":
            return len(data) if isinstance(data, list) else None
        if ats == "Ashby":
            return len(data["jobs"])
        if ats == "Workable":
            return len(data["jobs"])
        if ats == "SmartRecruiters":
            return int(data["totalFound"])
        if ats == "BambooHR":
            return len(data["result"])
    except (KeyError, TypeError, ValueError):
        return None
    return None
