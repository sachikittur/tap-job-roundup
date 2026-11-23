"""Sanity check a downloaded company list before the weekly run uses it.

Exits 0 if the file looks like the Sheet's Companies tab, 1 otherwise, so a
wrong tab, an error page or an empty export never replaces the working list.

Usage: python scripts/check_companies_csv.py path/to/companies.csv
"""
from __future__ import annotations

import csv
import re
import sys

REQUIRED = ["company", "website", "eligibility", "ats", "status"]
MIN_ROWS = 20


def main(path: str) -> int:
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            header = {re.sub(r"[^a-z]", "", h.lower()) for h in (reader.fieldnames or [])}
            rows = [r for r in reader if any((v or "").strip() for v in r.values())]
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        print(f"Could not read {path}: {e}")
        return 1
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        print(f"Missing columns: {', '.join(missing)}")
        return 1
    if not any(h.startswith("careers") or "feed" in h for h in header):
        print("Missing the 'Careers / job feed link' column")
        return 1
    if len(rows) < MIN_ROWS:
        print(f"Only {len(rows)} rows; expected at least {MIN_ROWS}")
        return 1
    print(f"OK: {len(rows)} companies")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
