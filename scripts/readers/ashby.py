"""Ashby: api.ashbyhq.com/posting-api/job-board/{org}"""
from __future__ import annotations

import http_client
from readers.common import Location, Posting, says_remote, to_date

EMPLOYMENT = {"FullTime": "Full-time", "PartTime": "Part-time", "Intern": "Intern",
              "Contract": "Contract", "Temporary": "Temporary"}


def _loc(raw: str, address: dict | None, remote: bool) -> Location:
    pa = (address or {}).get("postalAddress") or {}
    return Location(
        raw=raw or "",
        city=pa.get("addressLocality") or "",
        region=pa.get("addressRegion") or "",
        country=pa.get("addressCountry") or "",
        remote=remote or says_remote(raw),
    )


def fetch(token: str, company: str, title_ok=None) -> list[Posting]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"
    r = http_client.get(url, headers={"Accept": "application/json"})
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        fully_remote = (j.get("workplaceType") or "").lower() == "remote"
        locations = [_loc(j.get("location"), j.get("address"), fully_remote)]
        for s in j.get("secondaryLocations") or []:
            locations.append(_loc(s.get("location"), s.get("address"), fully_remote))
        out.append(Posting(
            title=(j.get("title") or "").strip(),
            company=company,
            url=j.get("jobUrl", ""),
            locations=locations,
            remote=fully_remote or any(l.remote for l in locations),
            employment_type=EMPLOYMENT.get(j.get("employmentType"), j.get("employmentType") or ""),
            date_posted=to_date(j.get("publishedAt")),
            description=j.get("descriptionPlain") or "",
            ats="Ashby",
        ))
    return out
