"""Assign each posting exactly one of the six level categories.

Rules live in config/levels.yaml and are checked in order; the first match
wins. classify() returns the category and a short note of the rule and the
words that matched, which run_weekly.py logs to logs/classification.csv.

Run this file directly to print the review table from the latest run:
    python scripts/classify.py
"""
from __future__ import annotations

import csv
import re
import sys
from functools import lru_cache
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from filters import compile_terms, first_match  # noqa: E402
from readers.common import Posting  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "levels.yaml"
LOG = ROOT / "logs" / "classification.csv"

CATEGORY_ORDER = ["Senior & executive", "Leadership", "Fractional", "Specialist", "Early career", "Mid career"]
FALLBACK = "Mid career"

_DASH = r"\s*(?:-|–|—|to)\s*"
YEARS_PATTERNS = [
    re.compile(r"(\d{1,2})" + _DASH + r"(\d{1,2})\+?\s*(?:years|yrs)", re.I),          # 1-3 years -> 3
    re.compile(r"up to\s*(\d{1,2})\s*(?:years|yrs)", re.I),                            # up to 5 years -> 5
    re.compile(r"(?:minimum|at least|min\.?)\s*(?:of\s*)?(\d{1,2})\s*(?:years|yrs)", re.I),  # at least 4 years
    re.compile(r"(\d{1,2})\s*\+\s*(?:years|yrs)", re.I),                               # 3+ years -> 3
    re.compile(r"(\d{1,2})\s*(?:or more\s*)?(?:years|yrs)['’]?\s*(?:of\s*)?(?:\w+\s*){0,4}experience", re.I),
]


@lru_cache(maxsize=1)
def _rules():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    scan = int(cfg.get("description_scan_chars", 1500))
    compiled = []
    for cat in cfg["categories"]:
        for rule in cat.get("rules", []):
            compiled.append({
                "category": cat["name"],
                "id": rule.get("id", cat["name"]),
                "title_any": compile_terms(rule.get("title_any")),
                "title_none": compile_terms(rule.get("title_none")),
                "employment_type_any": compile_terms(rule.get("employment_type_any")),
                "description_any": compile_terms(rule.get("description_any")),
                "experience_max_years": rule.get("experience_max_years"),
                "fallback": bool(rule.get("fallback")),
                "has_title_any": "title_any" in rule,
                "has_emp": "employment_type_any" in rule,
                "has_desc": "description_any" in rule,
            })
    unknown = {r["category"] for r in compiled} - set(CATEGORY_ORDER)
    if unknown:
        raise ValueError(f"levels.yaml has categories the page doesn't know: {unknown}")
    return compiled, scan


def required_years(description: str) -> int | None:
    """The highest experience requirement mentioned, or None if none is."""
    found = []
    for i, rx in enumerate(YEARS_PATTERNS):
        for m in rx.finditer(description or ""):
            n = int(m.group(2) if i == 0 else m.group(1))
            if 0 < n <= 30:
                found.append(n)
    return max(found) if found else None


def classify(p: Posting) -> tuple[str, str]:
    rules, scan = _rules()
    desc_head = (p.description or "")[:scan]
    years = None
    for r in rules:
        evidence = []
        if r["fallback"]:
            return r["category"], f"{r['id']} (no other rule matched)"
        if r["has_title_any"]:
            hit = first_match(p.title, r["title_any"])
            if not hit:
                continue
            evidence.append(f"title '{hit}'")
        if r["has_emp"]:
            hit = first_match(p.employment_type or "", r["employment_type_any"])
            if not hit:
                continue
            evidence.append(f"employment type '{hit}'")
        if r["has_desc"]:
            hit = first_match(desc_head, r["description_any"])
            if not hit:
                continue
            evidence.append(f"description '{hit}'")
        if r["experience_max_years"] is not None:
            if years is None:
                years = required_years(p.description) or 0
            if not years or years > int(r["experience_max_years"]):
                continue
            evidence.append(f"asks for {years} years")
        if r["title_none"]:
            blocked = first_match(p.title, r["title_none"])
            if blocked:
                continue
        return r["category"], f"{r['id']} ({', '.join(evidence)})"
    return FALLBACK, "no rule matched"


def print_review(path: Path = LOG) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    rows.sort(key=lambda r: (CATEGORY_ORDER.index(r["Category"]), r["Company"].lower()))
    w = max([len(r["Title"]) for r in rows] + [10])
    w = min(w, 55)
    for cat in CATEGORY_ORDER:
        group = [r for r in rows if r["Category"] == cat]
        print(f"\n{cat} ({len(group)})")
        for r in group:
            print(f"  {r['Title'][:w]:{w}}  {r['Company'][:22]:22}  {r['Rule']}")


if __name__ == "__main__":
    print_review()
