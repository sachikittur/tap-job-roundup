"""The two checks a posting must pass: it's a People and Culture role, and it's
in Canada. Keyword lists come from config/filters.yaml."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from readers.common import Location, Posting

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "filters.yaml"


# ---------------------------------------------------------------- term matching

def term_regex(term: str) -> re.Pattern:
    """Whole-word, case-insensitive; a trailing * allows longer words."""
    prefix = term.endswith("*")
    body = re.escape(term.rstrip("*").strip())
    body = body.replace(r"\ ", r"[\s\-]+")  # "People Operations" also matches "People-Operations"
    return re.compile(r"(?<![A-Za-z0-9])" + body + (r"[A-Za-z]*" if prefix else r"(?![A-Za-z0-9])"), re.I)


def compile_terms(terms) -> list[tuple[str, re.Pattern]]:
    return [(t, term_regex(t)) for t in (terms or [])]


def first_match(text: str, compiled) -> str | None:
    for term, rx in compiled:
        if rx.search(text):
            return term
    return None


@lru_cache(maxsize=1)
def _config():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    pc = cfg["people_culture"]
    return {
        "include": compile_terms(pc.get("include")),
        "exclude": compile_terms(pc.get("exclude")),
        "keep": compile_terms(pc.get("always_keep")),
        "false": compile_terms(pc.get("false_positives")),
        "keep_plain_remote": bool((cfg.get("location") or {}).get("keep_plain_remote")),
    }


# ---------------------------------------------------------------- People and Culture

def people_culture(title: str) -> tuple[bool, str]:
    """Return (keep, reason)."""
    c = _config()
    cleaned = title
    for _, rx in c["false"]:
        cleaned = rx.sub(" ", cleaned)
    inc = first_match(cleaned, c["include"])
    if not inc:
        return False, "no People and Culture term"
    exc = first_match(cleaned, c["exclude"])
    if exc:
        keep = first_match(cleaned, c["keep"])
        if keep:
            return True, f"'{inc}' kept despite '{exc}' (always keep '{keep}')"
        return False, f"'{inc}' but excluded by '{exc}'"
    return True, f"'{inc}'"


def title_ok(title: str) -> bool:
    return people_culture(title)[0]


# ---------------------------------------------------------------- Canada

PROVINCES = {
    "AB": ["Alberta"], "BC": ["British Columbia", "B.C."], "MB": ["Manitoba"],
    "NB": ["New Brunswick"], "NL": ["Newfoundland and Labrador", "Newfoundland"],
    "NS": ["Nova Scotia"], "NT": ["Northwest Territories"], "NU": ["Nunavut"],
    "ON": ["Ontario"], "PE": ["Prince Edward Island", "PEI"], "QC": ["Quebec", "Québec"],
    "SK": ["Saskatchewan"], "YT": ["Yukon"],
}
PROVINCE_NAMES = {n.lower(): code for code, names in PROVINCES.items() for n in names}

# Canadian cities likely to appear without a province. Ambiguous names
# (London, Victoria, Kingston, Richmond, Waterloo) are matched only with a
# province or "Canada" nearby, except where listed here as clearly Canadian.
CITIES = {
    "Toronto": "ON", "Ottawa": "ON", "Mississauga": "ON", "Markham": "ON", "Kitchener": "ON",
    "Waterloo": "ON", "Hamilton": "ON", "Burlington": "ON", "Oakville": "ON", "Guelph": "ON",
    "Vaughan": "ON", "Brampton": "ON", "Kanata": "ON", "Cambridge": "ON", "Barrie": "ON",
    "Vancouver": "BC", "Burnaby": "BC", "Surrey": "BC", "Richmond": "BC", "Victoria": "BC",
    "Kelowna": "BC", "Coquitlam": "BC", "North Vancouver": "BC", "New Westminster": "BC",
    "Nanaimo": "BC", "Squamish": "BC", "Langley": "BC", "Abbotsford": "BC", "Delta": "BC",
    "Calgary": "AB", "Edmonton": "AB", "Lethbridge": "AB", "Red Deer": "AB", "Canmore": "AB",
    "Montreal": "QC", "Montréal": "QC", "Quebec City": "QC", "Québec City": "QC", "Laval": "QC",
    "Gatineau": "QC", "Sherbrooke": "QC",
    "Winnipeg": "MB", "Regina": "SK", "Saskatoon": "SK", "Halifax": "NS", "Dartmouth": "NS",
    "Fredericton": "NB", "Moncton": "NB", "Saint John": "NB", "St. John's": "NL",
    "Charlottetown": "PE", "Whitehorse": "YT", "Yellowknife": "NT",
}
# Cities that are also big US/UK cities: only trusted with a Canadian signal.
AMBIGUOUS = {"Richmond", "Victoria", "Waterloo", "Cambridge", "Hamilton", "Delta", "Surrey",
             "Burlington", "Langley", "London", "Kingston", "Saint John"}

CANADA_RX = re.compile(r"(?<![A-Za-z])(Canada|Canadian)(?![A-Za-z])", re.I)
US_RX = re.compile(r"(?<![A-Za-z])(United States|USA|U\.S\.A?\.?|US)(?![A-Za-z])")
US_STATE_RX = re.compile(
    r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY"
    r"|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC|California|Washington|New York|Texas"
    r"|Massachusetts|Illinois|Colorado|Florida|Georgia|Oregon)(?![A-Za-z])")
NOT_A_CITY = re.compile(r"^\s*(remote|hybrid|on[- ]?site|canada|anywhere|multiple locations?)\b", re.I)
CODE_RX = re.compile(r"(?:,|\s|\()\s*(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)(?![A-Za-z])")

# Countries we recognise as definitely not Canada when a country field is set.
CANADA_COUNTRY = {"ca", "can", "canada"}


def _province_from_text(text: str) -> str | None:
    m = CODE_RX.search(text)
    if m:
        return m.group(1).upper()
    low = text.lower()
    for name, code in PROVINCE_NAMES.items():
        if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", low):
            return code
    return None


def _city_from_text(text: str, canada_signal: bool) -> tuple[str, str] | None:
    for city, code in sorted(CITIES.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"(?<![A-Za-z])" + re.escape(city) + r"(?![A-Za-z])", text, re.I):
            if city in AMBIGUOUS and not canada_signal:
                continue
            return city.replace("Montréal", "Montreal").replace("Québec City", "Quebec City"), code
    return None


def classify_location(loc: Location, keep_plain_remote: bool) -> tuple[str | None, str | None, str]:
    """Return (clean_location, province_code_or_REMOTE, reason). clean_location is None if not Canada."""
    country = (loc.country or "").strip().lower()
    text = " ".join(x for x in (loc.raw, loc.city, loc.region, loc.country) if x)
    if country and country not in CANADA_COUNTRY and not CANADA_RX.search(loc.raw or ""):
        return None, None, f"country is {loc.country}"

    region_code = _province_from_text(loc.region) if loc.region else None
    province = region_code or _province_from_text(text)
    canada_signal = country in CANADA_COUNTRY or bool(CANADA_RX.search(text)) or bool(province)

    if not province and not CANADA_RX.search(loc.raw or "") and country not in CANADA_COUNTRY:
        if US_RX.search(loc.raw or ""):
            return None, None, "US location"
        if US_STATE_RX.search(loc.raw or ""):
            return None, None, "US state"

    city_hit = _city_from_text(loc.city or loc.raw or "", canada_signal)
    city = (loc.city or "").strip() or (city_hit[0] if city_hit else "")
    if not city and province and "," in (loc.raw or ""):
        # "London, ON" or "Kingston, Ontario": the part before the first comma is the city
        first = loc.raw.split(",")[0].strip()
        if first and len(first) <= 30 and not NOT_A_CITY.match(first) \
                and _province_from_text(" " + first) is None:
            city = first
    if not province and city_hit:
        province = city_hit[1]
        canada_signal = True

    if loc.remote and canada_signal and not city:
        return "Remote (Canada)", "REMOTE", "remote in Canada"
    if loc.remote and re.fullmatch(r"\s*remote\s*", loc.raw or "", re.I) and not country:
        if keep_plain_remote:
            return "Remote (Canada)", "REMOTE", "plain remote (kept by config)"
        return None, None, "plain remote, no country"
    if not canada_signal:
        return None, None, "no Canadian place found"
    if city and province:
        return f"{city.title() if city.isupper() else city}, {province}", province, "Canadian city"
    if province:
        return PROVINCES[province][0], province, "Canadian province"
    if loc.remote:
        return "Remote (Canada)", "REMOTE", "remote in Canada"
    return "Canada", "CA", "says Canada"


def canada(posting: Posting) -> tuple[list[str], list[str], str]:
    """Return (clean_locations, province_codes, reason). Empty lists mean not in Canada."""
    keep_plain_remote = _config()["keep_plain_remote"]
    # Split "Vancouver, BC; Toronto, ON" style strings into separate locations
    locs: list[Location] = []
    for loc in posting.locations or [Location(remote=posting.remote)]:
        parts = [p.strip() for p in re.split(r"\s*(?:;|\||/| or )\s*", loc.raw or "") if p.strip()]
        if len(parts) > 1:
            locs += [Location(raw=p, country=loc.country, remote=loc.remote or bool(re.search(r"\bremote\b", p, re.I)))
                     for p in parts]
        else:
            locs.append(loc)

    cleans, provs, reasons = [], [], []
    for loc in locs:
        clean, prov, why = classify_location(loc, keep_plain_remote)
        reasons.append(f"{loc.raw or loc.country or '(blank)'}: {why}")
        if clean and clean not in cleans:
            cleans.append(clean)
            if prov and prov not in provs:
                provs.append(prov)
    # Drop a bare province ("Ontario") when a city in that province is listed
    province_names = {names[0]: code for code, names in PROVINCES.items()}
    cleans = [c for c in cleans
              if not (c in province_names and any(o.endswith(", " + province_names[c]) for o in cleans))]
    # A posting that is remote overall and in Canada also counts as Remote (Canada)
    if cleans and posting.remote and "REMOTE" not in provs and len(posting.locations) <= 1 \
            and any("remote" in (l.raw or "").lower() for l in posting.locations):
        provs.append("REMOTE")
    return cleans, provs, "; ".join(reasons)
