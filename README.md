# TAP Job Roundup

A weekly board of People and Culture roles at Canadian tech companies, shared with TAP Network members.

Every Monday at 9:00 am Eastern a GitHub Action reads public job feeds from each company's applicant tracking system (ATS), keeps People and Culture roles located in Canada, sorts each into one of six level categories, publishes the result to a static page on GitHub Pages and posts a summary to Slack.

No database, no server, no paid services. LinkedIn, Indeed and other job boards are never fetched.

## Layout

```
data/companies.csv        Export of the Companies tab from the Company List Sheet (the only input)
config/filters.yaml       Keyword lists for "is this People and Culture" and "is this in Canada"
config/levels.yaml        The six level categories and their rules, checked in order
scripts/detect_ats.py     One-time: finds each company's ATS and board token, writes them to the CSV
scripts/readers/          One small reader per ATS (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, BambooHR)
scripts/run_weekly.py     Fetch, filter, classify, diff against last week, write site/jobs.json
scripts/notify_slack.py   Weekly Slack post, or a staff alert if the run failed or found nothing
site/                     The static landing page (index.html, jobs.json, assets/). Self-contained.
logs/                     Run log and classification log from the latest run
.github/workflows/        The weekly schedule and the Pages deploy
```

## Run locally

Needs Python 3.11 or newer.

```powershell
python -m pip install -r requirements.txt
```

Refresh the company list: in the Sheet, open the Companies tab, choose File > Download > Comma separated values, and save it over `data/companies.csv`.

Detect ATS for companies with a blank ATS column (one time, or after adding companies):

```powershell
python scripts/detect_ats.py
```

This updates `data/companies.csv` in place and writes `logs/detection_report.csv`, which the team can paste back into the Sheet.

Run the weekly job locally (no Slack post):

```powershell
python scripts/run_weekly.py
```

Preview the page:

```powershell
python -m http.server 8000 -d site
```

Then open http://localhost:8000.

## Two streams

Every company belongs to one stream, set in the company list's **Stream** column:

| Stream value | Where its roles appear |
|---|---|
| `TAP member` (or blank) | The **TAP member companies** tab, and the lead of the Slack post |
| `Canadian tech` | The **More Canadian tech** tab, and its own line in the Slack post |

A Canadian tech company counts only once someone confirms it meets the rules (headquartered in Canada, tech as the core business, about 50 or more employees) and sets **Eligibility** to `Eligible`. New candidates start as `To confirm`, and the **HQ** column notes where they are based. If a company is listed in both streams, its roles go in the member stream. The page shows the tabs only once the Canadian tech stream has roles.

Preview what the Canadian tech tab would show before anyone confirms (writes `logs/test_*` only):

```powershell
python scripts/run_weekly.py --include-unconfirmed
```

Find feeds for newly added companies only:

```powershell
python scripts/detect_ats.py --status "To research"
```

### Keeping the list in the Sheet

The Company List Sheet is the source of truth. To have each Monday run use the Sheet as it is that morning, with no exports: in the Sheet choose File > Share > Publish to web, pick the **Companies** tab and **Comma separated values**, copy the link, and add it as a repository secret named `COMPANIES_CSV_URL`. The run checks the download looks like the Companies tab before using it, and keeps `data/companies.csv` in step. Without the secret, the run uses `data/companies.csv` as committed.

## Tuning

- A role is missing or shouldn't be there: edit the lists in `config/filters.yaml`.
- A role is in the wrong category: check `logs/classification.csv` for the rule that matched, then edit `config/levels.yaml`.

No code changes are needed for either.

Test a few companies without touching the live page data or logs (writes `logs/test_*`):

```powershell
python scripts/run_weekly.py --only "Trulioo,Jane App"
```

See the Slack message without sending it:

```powershell
python scripts/notify_slack.py --dry-run
```

## Set up on GitHub (one time)

1. **Push this repo to GitHub.**
2. **Turn on Pages:** Settings > Pages > Build and deployment > Source: **GitHub Actions**.
3. **Create two Slack incoming webhooks** (Slack app settings > Incoming Webhooks): one for the members channel, one for a private TAP staff channel.
4. **Add them as secrets:** Settings > Secrets and variables > Actions > New repository secret:
   - `SLACK_WEBHOOK_URL`: the members channel
   - `SLACK_ALERT_WEBHOOK_URL`: the private staff channel
5. **Add the page address as a variable** (same screen, Variables tab): `PAGE_URL`, for example `https://jobs.tapnetwork.ca/`. The Slack post links here.
6. **Do a test run:** Actions > Weekly job roundup > Run workflow, with "Test run" ticked. It fetches, publishes the page and posts the members message to the **staff** channel only.
7. When the test post looks right, the Monday schedule takes over. A manual run with "Test run" unticked posts to members.

### Using a TAP subdomain

To serve the page at, say, `jobs.tapnetwork.ca`: add a DNS CNAME record for `jobs` pointing to `<github-account>.github.io`, then enter the domain under Settings > Pages > Custom domain and tick Enforce HTTPS. Set `PAGE_URL` to match. The address then stays the same if the page later moves behind a member login.

## What runs when

| When | What |
|---|---|
| Mondays 9:00 am Eastern | `weekly.yml`: fetch all feeds, write `site/jobs.json` and `logs/`, commit them, deploy the page, post to Slack |
| Run failed, or found zero roles | No members post. A short alert goes to the staff channel with a link to the run |
| Some feeds failed | The members post still goes out; the staff channel gets a list of the skipped companies |
| Someone edits `site/` | `pages.yml` redeploys the page |

GitHub schedules in UTC, so the workflow is scheduled at both 13:00 and 14:00 UTC and runs only at the one that is 9 am in Toronto. Scheduled runs can start a few minutes late when GitHub is busy.

## Secrets

Slack webhooks live only in GitHub repository secrets (`SLACK_WEBHOOK_URL`, `SLACK_ALERT_WEBHOOK_URL`). Never commit a webhook URL. The scripts read them from environment variables and send nothing if they are missing.

## Later: members only

The page is fully static and self-contained in `site/` (its fonts, logo and data are all local). To restrict it later, put the same address behind a login layer such as Cloudflare Access, or embed the page on a members-only SilkStart page. No code changes are needed.
