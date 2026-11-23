"""Post the weekly Slack message, or a staff alert if the run went wrong.

Webhooks come only from environment variables (GitHub secrets), never code:
    SLACK_WEBHOOK_URL         members channel
    SLACK_ALERT_WEBHOOK_URL   private TAP staff channel
    PAGE_URL                  the public page address

Usage:
    python scripts/notify_slack.py                # normal weekly post
    python scripts/notify_slack.py --failed       # the run crashed: alert staff only
    python scripts/notify_slack.py --test         # send the members post to the staff channel instead
    python scripts/notify_slack.py --dry-run      # print what would be sent, send nothing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
JOBS_JSON = ROOT / "site" / "jobs.json"
RUN_LOG = ROOT / "logs" / "run_log.json"

# Order categories appear in the message: most senior first
ORDER = ["Senior & executive", "Leadership", "Mid career", "Specialist", "Early career", "Fractional"]
HIGHLIGHTS = 5


def esc(text: str) -> str:
    """Slack mrkdwn escaping."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def join_and(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def stream_of(job: dict) -> str:
    return "canadian_tech" if job.get("stream") == "canadian_tech" else "member"


def members_message(jobs_data: dict, page_url: str) -> dict:
    """Member roles lead; other Canadian tech roles get their own line, never mixed in."""
    all_jobs = jobs_data.get("jobs", [])
    jobs = [j for j in all_jobs if stream_of(j) == "member"]
    others = [j for j in all_jobs if stream_of(j) == "canadian_tech"]
    new = [j for j in jobs if j.get("is_new")]
    link = f"<{page_url}|See them all>" if page_url else "See them all on the TAP Job Roundup page"

    if new:
        counts = Counter(j["category"] for j in new)
        breakdown = esc(join_and([f"{counts[c]} {c}" for c in ORDER if counts.get(c)]))
        headline = (f"{plural(len(new), 'new People and Culture role', 'new People and Culture roles')} "
                    f"at TAP member companies this week: {breakdown}.")
        picks = sorted(new, key=lambda j: (ORDER.index(j["category"]) if j["category"] in ORDER else 99,
                                           j.get("company", "").lower()))[:HIGHLIGHTS]
        lines = [f"• <{j['url']}|{esc(j['title'])}>, {esc(j['company'])} ({esc(j['location'])})" for j in picks]
        more = len(new) - len(picks)
        tail = f"{link}: {plural(len(jobs), 'member role', 'member roles')} open in total" + (
            f", including {more} more new this week." if more > 0 else ".")
    else:
        headline = (f"No new People and Culture roles at TAP member companies this week. "
                    f"{plural(len(jobs), 'role is', 'roles are')} still open.")
        lines, tail = [], f"{link}."

    if others:
        new_others = sum(1 for j in others if j.get("is_new"))
        other_link = (f"<{page_url.rstrip('/')}/?stream=canadian-tech|See the Canadian tech roles>"
                      if page_url else "See them on the page")
        if new_others:
            tail += (f"\n\nAlso new this week at other Canadian tech companies: "
                     f"{plural(new_others, 'role', 'roles')}. {other_link}.")
        else:
            tail += (f"\n\nOther Canadian tech companies have "
                     f"{plural(len(others), 'role', 'roles')} open. {other_link}.")

    text = headline + "\n\n" + ("\n".join(lines) + "\n\n" if lines else "") + tail
    return {
        "text": headline,  # notification preview
        # Job fields are escaped above; the rest is our own text
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
        "unfurl_links": False,
    }


def alert_message(reason: str, run_log: dict | None, repo_run_url: str) -> dict:
    parts = [f"TAP Job Roundup: {reason} The members post was skipped."]
    if run_log:
        parts.append(
            f"Fetched {plural(run_log.get('companies_fetched', 0), 'company', 'companies')}, "
            f"{run_log.get('companies_failed', 0)} failed; "
            f"{plural(run_log.get('postings_seen', 0), 'posting', 'postings')} seen, "
            f"{run_log.get('jobs_published', 0)} published.")
    if repo_run_url:
        parts.append(f"<{repo_run_url}|Open the run log>")
    text = "\n".join(parts)
    return {"text": text, "unfurl_links": False}


def failures_note(run_log: dict, repo_run_url: str) -> dict | None:
    fails = run_log.get("failures") or []
    if not fails:
        return None
    names = ", ".join(esc(f["company"]) for f in fails[:10]) + (" and others" if len(fails) > 10 else "")
    text = (f"TAP Job Roundup: the weekly post went out, but {plural(len(fails), 'feed', 'feeds')} failed "
            f"and were skipped this week: {names}.")
    if repo_run_url:
        text += f" <{repo_run_url}|Run log>"
    return {"text": text, "unfurl_links": False}


def send(webhook: str | None, payload: dict, label: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"--- would send to {label} ---\n{json.dumps(payload, indent=1, ensure_ascii=False)}\n")
        return True
    if not webhook:
        print(f"No webhook set for {label}; nothing sent.", file=sys.stderr)
        return False
    r = requests.post(webhook, json=payload, timeout=15)
    if r.status_code != 200:
        print(f"Slack {label} returned {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return False
    print(f"Sent to {label}.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--failed", action="store_true", help="the weekly run crashed")
    ap.add_argument("--test", action="store_true", help="send the members post to the staff channel")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    members_hook = os.environ.get("SLACK_WEBHOOK_URL")
    alert_hook = os.environ.get("SLACK_ALERT_WEBHOOK_URL")
    page_url = os.environ.get("PAGE_URL", "").strip()
    run_url = os.environ.get("RUN_URL", "").strip()

    run_log = json.loads(RUN_LOG.read_text(encoding="utf-8")) if RUN_LOG.exists() else None
    jobs_data = json.loads(JOBS_JSON.read_text(encoding="utf-8")) if JOBS_JSON.exists() else {}

    if args.failed or run_log is None:
        ok = send(alert_hook, alert_message("the weekly run failed.", run_log, run_url), "staff alert channel",
                  args.dry_run)
        return 0 if ok else 1
    if not jobs_data.get("jobs"):
        ok = send(alert_hook, alert_message("the weekly run found zero roles.", run_log, run_url),
                  "staff alert channel", args.dry_run)
        return 0 if ok else 1

    post = members_message(jobs_data, page_url)
    if args.test:
        post["text"] = "[Test] " + post["text"]
        post["blocks"][0]["text"]["text"] = "*Test run: this is what members will see.*\n\n" + \
            post["blocks"][0]["text"]["text"]
        ok = send(alert_hook, post, "staff alert channel (test)", args.dry_run)
    else:
        ok = send(members_hook, post, "members channel", args.dry_run)

    note = failures_note(run_log, run_url)
    if note:
        send(alert_hook, note, "staff alert channel", args.dry_run)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
