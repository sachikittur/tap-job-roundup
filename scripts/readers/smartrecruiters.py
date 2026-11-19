"""SmartRecruiters: api.smartrecruiters.com/v1/companies/{id}/postings

The list has no description or public URL, so we fetch each posting's detail,
but only for titles that pass the People and Culture check (title_ok), to keep
the request count low.
"""
from __future__ import annotations

import http_client
from readers.common import Location, Posting, clean_text, to_date


def fetch(token: str, company: str, title_ok=None) -> list[Posting]:
    out, offset = [], 0
    while True:
        url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100&offset={offset}"
        r = http_client.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
        items = data.get("content", [])
        for j in items:
            title = (j.get("name") or "").strip()
            loc = j.get("location") or {}
            remote = bool(loc.get("remote"))
            posting = Posting(
                title=title,
                company=company,
                url=f"https://jobs.smartrecruiters.com/{token}/{j.get('id')}",
                locations=[Location(raw=loc.get("fullLocation") or "", city=loc.get("city") or "",
                                    region=loc.get("region") or "", country=loc.get("country") or "",
                                    remote=remote)],
                remote=remote,
                employment_type=(j.get("typeOfEmployment") or {}).get("label") or "",
                date_posted=to_date(j.get("releasedDate")),
                ats="SmartRecruiters",
            )
            if title_ok is None or title_ok(title):
                try:
                    d = http_client.get(j["ref"], headers={"Accept": "application/json"}).json()
                    posting.url = d.get("postingUrl") or posting.url
                    sections = (d.get("jobAd") or {}).get("sections") or {}
                    posting.description = clean_text("\n".join(
                        (sections.get(k) or {}).get("text") or ""
                        for k in ("jobDescription", "qualifications", "additionalInformation")))
                except Exception:
                    pass  # keep the posting without a description
            out.append(posting)
        offset += len(items)
        if not items or offset >= int(data.get("totalFound", 0)):
            return out
