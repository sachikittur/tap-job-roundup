"""BambooHR: {subdomain}.bamboohr.com/careers/list

The list has no description or posting date, so we fetch each posting's
detail, but only for titles that pass the People and Culture check (title_ok).
"""
from __future__ import annotations

import http_client
from readers.common import Location, Posting, clean_text, to_date

REMOTE_LOCATION_TYPE = "1"  # BambooHR: 0 on site, 1 remote, 2 hybrid


def _location(j: dict) -> Location:
    loc = j.get("location") or {}
    ats_loc = j.get("atsLocation") or {}
    city = loc.get("city") or ats_loc.get("city") or ""
    region = loc.get("state") or ats_loc.get("state") or ats_loc.get("province") or ""
    country = loc.get("addressCountry") or ats_loc.get("country") or ""
    remote = bool(j.get("isRemote")) or str(j.get("locationType")) == REMOTE_LOCATION_TYPE
    raw = ", ".join(x for x in (city, region, country) if x) or ("Remote" if remote else "")
    return Location(raw=raw, city=city, region=region, country=country, remote=remote)


def fetch(token: str, company: str, title_ok=None) -> list[Posting]:
    base = f"https://{token}.bamboohr.com/careers"
    r = http_client.get(f"{base}/list", headers={"Accept": "application/json"})
    r.raise_for_status()
    out = []
    for j in r.json().get("result", []):
        title = (j.get("jobOpeningName") or "").strip()
        location = _location(j)
        posting = Posting(
            title=title,
            company=company,
            url=f"{base}/{j.get('id')}",
            locations=[location],
            remote=location.remote,
            employment_type=j.get("employmentStatusLabel") or "",
            ats="BambooHR",
        )
        if title_ok is None or title_ok(title):
            try:
                d = http_client.get(f"{base}/{j.get('id')}/detail",
                                    headers={"Accept": "application/json"}).json()
                jo = (d.get("result") or {}).get("jobOpening") or {}
                posting.description = clean_text(jo.get("description"))
                posting.date_posted = to_date(jo.get("datePosted"))
                posting.url = jo.get("jobOpeningShareUrl") or posting.url
                if jo.get("location"):
                    detailed = _location({**j, "location": jo["location"]})
                    posting.locations = [detailed]
            except Exception:
                pass  # keep the posting without a description
        out.append(posting)
    return out
