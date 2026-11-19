"""Workable: apply.workable.com/api/v1/widget/accounts/{subdomain}"""
from __future__ import annotations

import http_client
from readers.common import Location, Posting, clean_text, says_remote, to_date


def fetch(token: str, company: str, title_ok=None) -> list[Posting]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
    r = http_client.get(url, headers={"Accept": "application/json"})
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        remote = bool(j.get("telecommuting"))
        locs = [l for l in (j.get("locations") or []) if not l.get("hidden")]
        if not locs:
            locs = [{"city": j.get("city"), "region": j.get("state"), "country": j.get("country")}]
        locations = []
        for l in locs:
            raw = ", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x)
            locations.append(Location(
                raw=raw, city=l.get("city") or "", region=l.get("region") or "",
                country=l.get("countryCode") or l.get("country") or "",
                remote=remote or says_remote(raw),
            ))
        out.append(Posting(
            title=(j.get("title") or "").strip(),
            company=company,
            url=j.get("url") or j.get("shortlink") or "",
            locations=locations,
            remote=remote,
            employment_type=j.get("employment_type") or "",
            date_posted=to_date(j.get("published_on") or j.get("created_at")),
            description=clean_text(j.get("description")),
            ats="Workable",
        ))
    return out
