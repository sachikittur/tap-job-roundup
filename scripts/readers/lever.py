"""Lever: api.lever.co/v0/postings/{company}?mode=json"""
from __future__ import annotations

import http_client
from readers.common import Location, Posting, says_remote, to_date


def fetch(token: str, company: str, title_ok=None) -> list[Posting]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    r = http_client.get(url, headers={"Accept": "application/json"})
    r.raise_for_status()
    out = []
    for j in r.json():
        cats = j.get("categories") or {}
        remote = (j.get("workplaceType") or "").lower() == "remote"
        country = j.get("country") or ""  # Lever's country applies to the primary location
        raws = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
        locations = []
        for i, raw in enumerate(raws):
            locations.append(Location(
                raw=raw,
                country=country if i == 0 or len(raws) == 1 else "",
                remote=remote or says_remote(raw),
            ))
        if not locations and country:
            locations.append(Location(country=country, remote=remote))
        desc = "\n".join(filter(None, [
            j.get("openingPlain"), j.get("descriptionBodyPlain") or j.get("descriptionPlain"),
            *[(l.get("text") or "") for l in j.get("lists") or []],
            j.get("additionalPlain"),
        ]))
        out.append(Posting(
            title=(j.get("text") or "").strip(),
            company=company,
            url=j.get("hostedUrl", ""),
            locations=locations,
            remote=remote or any(l.remote for l in locations),
            employment_type=cats.get("commitment") or "",
            date_posted=to_date(j.get("createdAt")),
            description=desc,
            ats="Lever",
        ))
    return out
