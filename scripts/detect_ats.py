"""One-time ATS detection.

For every company in data/companies.csv with a blank ATS column, load its
website and careers page, look for links to a known ATS, verify the public
feed answers, and write the ATS name and board link back to the CSV.

Companies with no detectable feed are marked "Manual check". A report is
written to logs/detection_report.csv for pasting back into the Sheet.

Usage:
    python scripts/detect_ats.py              # all companies with a blank ATS
    python scripts/detect_ats.py --all        # re-detect every company
    python scripts/detect_ats.py --limit 10   # first 10 only (for testing)
    python scripts/detect_ats.py --dry-run    # report only, leave the CSV alone
    python scripts/detect_ats.py --status "To research"   # only newly added companies
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ats  # noqa: E402
import http_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "companies.csv"
REPORT_PATH = ROOT / "logs" / "detection_report.csv"

CAREERS_LINK = re.compile(
    r"""href=["']([^"'#]+)["'][^>]*>(?:(?!</a>).){0,200}?</a>""", re.I | re.S
)
CAREERS_WORDS = re.compile(r"career|jobs|join[- ]?(?:us|our|the)|work[- ]with[- ]us|hiring|opportunit|open[- ]roles|positions", re.I)
COMMON_PATHS = ("/careers", "/jobs", "/careers/", "/company/careers", "/about/careers", "/join-us")
CANADA = re.compile(
    r"\bCanada\b|\bToronto\b|\bVancouver\b|\bMontr[eé]al\b|\bCalgary\b|\bOttawa\b|\bWaterloo\b|\bEdmonton\b"
    r"|\bWinnipeg\b|\bHalifax\b|\bVictoria, BC\b|\bQu[eé]bec\b|\bOntario\b|\bBritish Columbia\b|\bAlberta\b",
    re.I,
)


# ---------------------------------------------------------------- CSV helpers

def find_col(fieldnames: list[str], *candidates: str) -> str | None:
    norm = {re.sub(r"[^a-z]", "", f.lower()): f for f in fieldnames}
    for c in candidates:
        key = re.sub(r"[^a-z]", "", c.lower())
        if key in norm:
            return norm[key]
    for c in candidates:  # loose: column name starts with the candidate
        key = re.sub(r"[^a-z]", "", c.lower())
        for k, f in norm.items():
            if k.startswith(key):
                return f
    return None


def load_csv():
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    cols = {
        "company": find_col(fields, "Company"),
        "website": find_col(fields, "Website"),
        "eligibility": find_col(fields, "Eligibility"),
        "ats": find_col(fields, "ATS"),
        "feed": find_col(fields, "Careers / job feed link", "Careers", "Job feed link", "Feed"),
        "status": find_col(fields, "Status"),
        "source": find_col(fields, "Source"),
    }
    missing = [k for k in ("company", "website", "ats", "feed", "status") if not cols[k]]
    if missing:
        sys.exit(f"companies.csv is missing columns: {', '.join(missing)}. Found: {fields}")
    return rows, fields, cols


# ---------------------------------------------------------------- detection

def fetch_text(url: str) -> tuple[str, str]:
    """Return (final_url, html). Empty html on failure."""
    try:
        r = http_client.get(url, allow_redirects=True)
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            return url, ""
        return r.url, r.text[:2_000_000]
    except Exception:
        return url, ""


def verify(ats_name: str, token: str):
    """Return (job_count, raw_text) if the public feed answers, else (None, '')."""
    try:
        r = http_client.get(ats.feed_url(ats_name, token), headers={"Accept": "application/json"})
        if r.status_code != 200:
            return None, ""
        return ats.count_jobs(ats_name, r.json()), r.text
    except Exception:
        return None, ""


def careers_links(base: str, html: str) -> list[str]:
    links = []
    for m in CAREERS_LINK.finditer(html):
        href, whole = m.group(1), m.group(0)
        if CAREERS_WORDS.search(href) or CAREERS_WORDS.search(re.sub(r"<[^>]+>", " ", whole)):
            url = urljoin(base, href)
            if url.startswith("http") and url not in links:
                links.append(url)
    return links[:6]


def slug_guesses(name: str, website: str) -> list[str]:
    base = re.sub(r"\b(inc|ltd|corp|corporation|technologies|technology|labs|software|co|canada)\b\.?", "", name, flags=re.I)
    words = re.findall(r"[a-z0-9]+", base.lower())
    guesses = ["".join(words), "-".join(words)]
    host = (urlparse(website).hostname or "").lower().removeprefix("www.")
    if host:
        guesses.append(host.split(".")[0])
    return [g for i, g in enumerate(guesses) if g and len(g) > 2 and g not in guesses[:i]]


def detect(name: str, website: str) -> dict:
    result = {"ats": "", "token": "", "jobs": "", "method": "", "careers_page": "", "note": ""}
    if not website:
        result["note"] = "No website in Sheet"
        return result
    if not website.startswith("http"):
        website = "https://" + website.strip().lstrip("/")

    pages_seen: list[str] = []
    unsupported: Counter = Counter()

    def scan(url: str, html: str) -> bool:
        pages_seen.append(url)
        # The final URL itself may be an ATS board (careers link redirected there)
        for ats_name, token in ats.find_tokens(url + "\n" + html):
            jobs, _ = verify(ats_name, token)
            if jobs is not None:
                result.update(ats=ats_name, token=token, jobs=jobs, careers_page=url,
                              method="link on careers page" if url != pages_seen[0] else "link on website")
                return True
        unsupported.update(ats.find_unsupported(url + "\n" + html))
        return False

    home_url, home = fetch_text(website)
    if not home:
        result["note"] = "Website did not load"
    elif scan(home_url, home):
        return result

    candidates = careers_links(home_url, home) if home else []
    origin = f"{urlparse(home_url).scheme}://{urlparse(home_url).netloc}"
    candidates += [origin + p for p in COMMON_PATHS if origin + p not in candidates]
    for url in candidates[:8]:
        final, html = fetch_text(url)
        if not html or final in pages_seen:
            continue
        if not result["careers_page"]:
            result["careers_page"] = final
        if scan(final, html):
            return result
        # one level deeper: careers pages often link to "View open roles"
        for deeper in careers_links(final, html)[:3]:
            if deeper in pages_seen:
                continue
            f2, h2 = fetch_text(deeper)
            if h2 and scan(f2, h2):
                return result

    if unsupported:
        top = unsupported.most_common(1)[0][0]
        result.update(ats=top, method="unsupported ATS",
                      note=f"Uses {top}, which has no public feed reader yet")
        return result

    # Last resort: many careers pages load jobs with JavaScript, so the HTML has no
    # ATS link. Try the company's name as a board token, and accept only boards
    # with at least one Canadian location so we don't pick up a namesake.
    for slug in slug_guesses(name, website):
        for ats_name in ("Greenhouse", "Lever", "Ashby", "BambooHR", "Workable"):
            jobs, raw = verify(ats_name, slug)
            if jobs and CANADA.search(raw):
                result.update(ats=ats_name, token=slug, jobs=jobs, method="name guess (please confirm)")
                return result

    if not result["note"]:
        result["note"] = "No ATS link found on website or careers page"
    return result


# ---------------------------------------------------------------- main

def main() -> None:
    global CSV_PATH, REPORT_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="re-detect companies that already have an ATS")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--status", help='only rows with this Status, e.g. "To research"')
    ap.add_argument("--csv", type=Path, default=CSV_PATH, help="input CSV (default data/companies.csv)")
    ap.add_argument("--report", type=Path, default=REPORT_PATH)
    args = ap.parse_args()
    CSV_PATH, REPORT_PATH = args.csv, args.report

    rows, fields, c = load_csv()
    todo = [r for r in rows
            if (args.all or not (r[c["ats"]] or "").strip())
            and (r[c["status"]] or "").strip().lower() != "excluded"
            and (not args.status or (r[c["status"]] or "").strip().lower() == args.status.lower())]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(rows)} companies in CSV, {len(todo)} to detect")

    def work(row):
        res = detect(row[c["company"]].strip(), (row[c["website"]] or "").strip())
        print(f"  {row[c['company']][:40]:40} {res['ats'] or '-':16} {res['token'] or ''} {res['note']}", flush=True)
        return row, res

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(work, todo))

    report = []
    for row, res in results:
        if res["ats"] in ats.SUPPORTED:
            status = "Feed found"
            link = ats.board_url(res["ats"], res["token"])
        else:
            status = "Manual check"
            link = res["careers_page"]
        if not args.dry_run:
            row[c["ats"]] = res["ats"]
            row[c["feed"]] = link
            row[c["status"]] = status
        report.append({
            "Company": row[c["company"]],
            "Website": row[c["website"]],
            "Eligibility": row[c["eligibility"]] if c["eligibility"] else "",
            "ATS": res["ats"],
            "Careers / job feed link": link,
            "Status": status,
            "Jobs in feed": res["jobs"],
            "How found": res["method"],
            "Note": res["note"],
        })

    if not args.dry_run:
        with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    REPORT_PATH.parent.mkdir(exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(report[0].keys()) if report else ["Company"])
        w.writeheader()
        w.writerows(report)

    # Summary across the whole CSV (not just this run)
    final_rows = rows if not args.dry_run else rows
    by_ats = Counter((r[c["ats"]] or "").strip() or "(none)" for r in final_rows)
    by_status = Counter((r[c["status"]] or "").strip() or "(blank)" for r in final_rows)
    guesses = sum(1 for r in report if r["How found"].startswith("name guess"))
    print("\nATS across all companies:")
    for k, v in by_ats.most_common():
        print(f"  {k:18} {v}")
    print("\nStatus across all companies:")
    for k, v in by_status.most_common():
        print(f"  {k:18} {v}")
    if guesses:
        print(f"\n{guesses} feeds were found by guessing from the company name; please confirm them in the report.")
    print(f"\nReport: {REPORT_PATH}")


if __name__ == "__main__":
    main()
