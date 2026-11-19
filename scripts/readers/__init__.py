"""One small reader per ATS. Each exposes fetch(token, company, title_ok) -> list[Posting].

title_ok is an optional callable; readers that need an extra request per
posting (BambooHR, SmartRecruiters) only make it for titles that pass.
"""
from readers import ashby, bamboohr, greenhouse, lever, smartrecruiters, workable

READERS = {
    "Greenhouse": greenhouse.fetch,
    "Lever": lever.fetch,
    "Ashby": ashby.fetch,
    "Workable": workable.fetch,
    "SmartRecruiters": smartrecruiters.fetch,
    "BambooHR": bamboohr.fetch,
}
