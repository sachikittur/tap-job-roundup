"""Greenhouse: boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"""
from __future__ import annotations

import http_client
from readers.common import Location, Posting, clean_text, says_remote, to_date


def fetch(token: str, company: str, title_ok=None) -> list[Posting]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    r = http_client.get(url, headers={"Accept": "application/json"})
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        loc_name = (j.get("location") or {}).get("name", "").strip()
        locations = [Location(raw=loc_name, remote=says_remote(loc_name))] if loc_name else []
        for office in j.get("offices") or []:
            raw = (office.get("location") or office.get("name") or "").strip()
            if raw and raw != loc_name:
                locations.append(Location(raw=raw, remote=says_remote(raw)))
        employment = ""
        for m in j.get("metadata") or []:
            if "employment" in (m.get("name") or "").lower() and isinstance(m.get("value"), str):
                employment = m["value"]
        out.append(Posting(
            title=j.get("title", "").strip(),
            company=company,
            url=j.get("absolute_url", ""),
            locations=locations,
            remote=any(l.remote for l in locations),
            employment_type=employment,
            date_posted=to_date(j.get("first_published") or j.get("updated_at")),
            description=clean_text(j.get("content")),
            ats="Greenhouse",
        ))
    return out
