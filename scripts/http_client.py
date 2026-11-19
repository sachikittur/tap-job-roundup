"""Shared HTTP session with polite per-host throttling.

ATS API hosts are limited to one request per second (the brief's rule).
Company websites get a lighter limit. Safe to use from several threads.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests

USER_AGENT = "TAPJobRoundup/1.0 (weekly People and Culture job digest; public ATS feeds only)"
TIMEOUT = 15

# Hosts (or host suffixes) of public ATS feeds: max 1 request per second each.
ATS_HOST_SUFFIXES = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "workable.com",
    "smartrecruiters.com",
    "bamboohr.com",
)

# Never fetch from job boards whose terms prohibit scraping.
BLOCKED_HOST_SUFFIXES = ("linkedin.com", "indeed.com", "indeed.ca", "glassdoor.com", "glassdoor.ca")

_locks: dict[str, threading.Lock] = {}
_last: dict[str, float] = {}
_registry_lock = threading.Lock()
_local = threading.local()


def _throttle_key(host: str) -> tuple[str, float]:
    for suffix in ATS_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return suffix, 1.0  # one bucket per ATS, not per subdomain
    return host, 0.5


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-CA,en;q=0.8"})
        _local.session = s
    return s


class BlockedHostError(Exception):
    pass


def get(url: str, **kwargs) -> requests.Response:
    """GET with throttling and one retry on a timeout or dropped connection."""
    try:
        return _get_once(url, **dict(kwargs))
    except (requests.Timeout, requests.ConnectionError):
        time.sleep(3)
        return _get_once(url, **kwargs)


def _get_once(url: str, **kwargs) -> requests.Response:
    host = (urlparse(url).hostname or "").lower()
    if any(host == b or host.endswith("." + b) for b in BLOCKED_HOST_SUFFIXES):
        raise BlockedHostError(f"Refusing to fetch from job board host {host}")
    key, interval = _throttle_key(host)
    with _registry_lock:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        wait = _last.get(key, 0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return _session().get(url, timeout=kwargs.pop("timeout", TIMEOUT), **kwargs)
        finally:
            _last[key] = time.monotonic()
