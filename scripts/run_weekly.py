"""The weekly run.

1. Read data/companies.csv and keep Eligible companies with a supported ATS.
2. Fetch each feed (one failure never stops the run), keep People and Culture
   roles in Canada, and assign a level category.
3. Compare with last week's site/jobs.json by posting URL: mark new roles,
   carry over the date first found, drop roles no longer in any feed.
4. Write site/jobs.json and the logs.

Usage:
    python scripts/run_weekly.py
    python scripts/run_weekly.py --only "Jane App,Trulioo"   # test run; writes logs/test_* only
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ats  # noqa: E402
import filters  # noqa: E402
from readers import READERS  # noqa: E402

try:
    import classify  # added in step 4
except ImportError:  # pragma: no cover
    classify = None

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = ROOT / "data" / "companies.csv"
JOBS_JSON = ROOT / "site" / "jobs.json"
LOGS = ROOT / "logs"
EASTERN = ZoneInfo("America/Toronto")


def col(row: dict, *names: str) -> str:
    norm = {re.sub(r"[^a-z]", "", k.lower()): k for k in row}
    for n in names:
        k = norm.get(re.sub(r"[^a-z]", "", n.lower()))
        if k:
            return (row[k] or "").strip()
    return ""


def load_companies(only: set[str] | None):
    with COMPANIES.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    targets, skipped = [], Counter()
    for r in rows:
        name = col(r, "Company")
        if only and name.lower() not in only:
            continue
        if col(r, "Eligibility").lower() != "eligible":
            skipped["not Eligible"] += 1
            continue
        ats_name = ats.normalise_ats(col(r, "ATS"))
        if ats_name not in ats.SUPPORTED:
            skipped["no supported ATS"] += 1
            continue
        token = ats.parse_token(ats_name, col(r, "Careers / job feed link", "Careers", "Feed"))
        if not token:
            skipped["no board token"] += 1
            continue
        targets.append((name, ats_name, token))
    return targets, skipped, len(rows)


def fetch_company(target):
    name, ats_name, token = target
    started = time.monotonic()
    try:
        postings = READERS[ats_name](token, name, filters.title_ok)
        return {"company": name, "ats": ats_name, "token": token, "ok": True,
                "postings": postings, "seconds": round(time.monotonic() - started, 1)}
    except Exception as e:  # log and move on
        return {"company": name, "ats": ats_name, "token": token, "ok": False, "postings": [],
                "error": f"{type(e).__name__}: {e}"[:300], "seconds": round(time.monotonic() - started, 1),
                "trace": traceback.format_exc(limit=2)}


def job_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def load_previous() -> dict[str, dict]:
    if not JOBS_JSON.exists():
        return {}
    try:
        return {j["url"]: j for j in json.loads(JOBS_JSON.read_text(encoding="utf-8")).get("jobs", [])}
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated company names, for testing")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    only = {s.strip().lower() for s in args.only.split(",")} if args.only else None

    now = datetime.now(EASTERN)
    today = now.strftime("%Y-%m-%d")
    targets, skipped, total_rows = load_companies(only)
    print(f"{total_rows} companies in CSV; fetching {len(targets)} "
          f"({', '.join(f'{v} {k}' for k, v in skipped.items()) or 'none skipped'})")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(fetch_company, targets))

    previous = load_previous()
    review_rows, jobs, seen = [], [], set()
    for res in results:
        status = f"{len(res['postings'])} postings" if res["ok"] else f"FAILED {res['error']}"
        print(f"  {res['company'][:38]:38} {res['ats']:15} {status}")
        for p in res["postings"]:
            pc_ok, pc_why = filters.people_culture(p.title)
            locs, provs, loc_why = filters.canada(p) if pc_ok else ([], [], "")
            keep = pc_ok and bool(locs) and p.url and p.url not in seen
            category, rule = ("", "")
            if keep and classify:
                category, rule = classify.classify(p)
            review_rows.append({
                "Company": p.company, "Title": p.title,
                "Locations (raw)": " | ".join(l.raw or l.country for l in p.locations),
                "People and Culture": "yes" if pc_ok else "no", "P&C reason": pc_why,
                "In Canada": ("yes" if locs else "no") if pc_ok else "", "Location reason": loc_why,
                "Kept": "yes" if keep else "no", "Category": category, "Rule": rule,
                "Employment type": p.employment_type, "URL": p.url,
            })
            if not keep:
                continue
            seen.add(p.url)
            prev = previous.get(p.url)
            jobs.append({
                "id": job_id(p.url),
                "title": p.title,
                "company": p.company,
                "location": " · ".join(locs),
                "locations": locs,
                "provinces": provs,
                "remote": "REMOTE" in provs,
                "employment_type": p.employment_type,
                "category": category,
                "category_rule": rule,
                "url": p.url,
                "date_posted": p.date_posted,
                "first_found": (prev or {}).get("first_found") or today,
                "is_new": prev is None,
                "ats": p.ats,
            })

    jobs.sort(key=lambda j: (j["first_found"], j["date_posted"] or ""), reverse=True)
    failed = [r for r in results if not r["ok"]]
    dropped = [u for u in previous if u not in seen]

    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "run_date": today,
        "count": len(jobs),
        "new_count": sum(j["is_new"] for j in jobs),
        "categories": dict(Counter(j["category"] for j in jobs if j["category"])),
        "jobs": jobs,
    }
    # A partial test run (--only) must never replace the live page data or logs
    prefix = "test_" if only else ""
    target = LOGS / "test_jobs.json" if only else JOBS_JSON
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if only:
        print(f"Test run: wrote logs/test_*; site/jobs.json and the weekly logs left unchanged")

    LOGS.mkdir(exist_ok=True)
    with (LOGS / f"{prefix}postings_review.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(review_rows[0]) if review_rows else ["Company"])
        w.writeheader()
        w.writerows(review_rows)
    with (LOGS / f"{prefix}classification.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["Category", "Rule", "Title", "Company", "Location",
                                           "Employment type", "URL"])
        w.writeheader()
        for j in jobs:
            w.writerow({"Category": j["category"], "Rule": j["category_rule"], "Title": j["title"],
                        "Company": j["company"], "Location": j["location"],
                        "Employment type": j["employment_type"], "URL": j["url"]})
    summary = {
        "run_date": today,
        "generated_at": out["generated_at"],
        "companies_in_csv": total_rows,
        "companies_fetched": len(targets),
        "companies_skipped": dict(skipped),
        "companies_failed": len(failed),
        "postings_seen": len(review_rows),
        "people_culture_postings": sum(r["People and Culture"] == "yes" for r in review_rows),
        "jobs_published": len(jobs),
        "new_jobs": out["new_count"],
        "dropped_since_last_run": len(dropped),
        "categories": out["categories"],
        "failures": [{k: r[k] for k in ("company", "ats", "token", "error")} for r in failed],
        "companies": [{"company": r["company"], "ats": r["ats"], "ok": r["ok"],
                       "postings": len(r["postings"]), "seconds": r["seconds"]} for r in results],
    }
    (LOGS / f"{prefix}run_log.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{len(review_rows)} postings seen, {summary['people_culture_postings']} People and Culture, "
          f"{len(jobs)} in Canada and published ({out['new_count']} new, {len(dropped)} dropped). "
          f"{len(failed)} feeds failed.")
    if failed:
        for f in failed:
            print(f"  failed: {f['company']} ({f['ats']}/{f['token']}): {f['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
