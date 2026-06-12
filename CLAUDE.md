# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Selenium-based automation for an AYSO region (Region 58) that drives several external systems — Sports Connect/Blue Sombrero (registration reports), Sports Affinity (volunteer credentials), ETrainU (training certifications, reached via Sports Connect SSO), and PlayMetrics — and publishes results to Google Drive/Sheets, Mailchimp, an Access database, and a board portal (GCS bucket `region58-portal-data`).

## Commands

```powershell
venv\Scripts\activate                 # virtual env (created by setup.bat / python -m venv venv)
pip install -r requirements.txt

python src\main.py                    # run all enabled reports (run.bat does the same)
python src\main.py --help             # the full CLI — dozens of flags, see below
python src\main.py TEAM_DETAIL --headless   # one report, headless

pytest tests/                         # all tests
pytest tests/unit/test_config.py      # one file
pytest tests/unit/test_config.py::TestConfigManager::test_name   # one test
pytest -m "not slow"                  # markers: slow, integration, unit, e2e

black src/                            # format
flake8 src/                           # lint
pylint src/
```

Note: the intended pytest config lives in `tests/pytest.txt`, which pytest does **not** auto-discover (use `pytest -c tests/pytest.txt` to apply it). `tests/conftest.py` adds `src/` to `sys.path`, so tests import modules as `core.config`, `automation.sports_connect`, etc.

## Architecture

### Everything dispatches through `src/main.py`

`main.py` (~3,300 lines) is a single argparse CLI that is the entry point for every feature: report downloads, waitlist management, medical forms, payment reminders, PlayMetrics exports, Mailchimp sync, ETrainU scraping, and compliance publishing. Each feature is a flag (`--waitlist-removal`, `--medical-forms`, `--pm-download`, `--etrainu`, `--pm-compliance`, …) that calls a `handle_*` function or manager class from `src/automation/` or `src/integrations/`. The `--help` epilog in `main.py` is the best catalog of what the tool can do. New features follow the same pattern: a module under `automation/` or `integrations/` plus a flag + dispatch branch in `main.py`.

### Layers

- **`src/core/`** — framework: `ConfigManager` (reads `config/config.json`; report definitions, season, org id, timeouts), `WebDriverManager` (Chrome via webdriver-manager with manual-chromedriver fallback; downloads land in `data/downloads/`), `ElementInteractor` (resilient Selenium interactions), custom exceptions.
- **`src/automation/`** — feature managers. `sports_connect.py` (`SportsConnectAutomation`) owns the logged-in browser session; other managers (`ETrainUManager`, `SportsAffinityManager`) reuse that session/SSO rather than logging in separately. `report_handlers.py` defines `ReportType` and per-report download logic.
- **`src/integrations/`** — external services: Google Drive/Sheets, Gmail OAuth, Access DB (`access_db.py`, runs macros like `UpdateEnrollmentSummary`), and the compliance pipeline.
- **`src/utilities/`** — logging, credentials (CSV files under `config/`), archiver, validator.

Because `main.py` does `sys.path.insert(src)`, all intra-project imports are rooted at `src/` (`from core.config import ConfigManager`), never `from src.core...`.

### Compliance pipeline (adapter pattern)

Documented in `Compliance_Provider_Architecture.md` — read it before touching compliance code. The contract is source-agnostic:

```
source exports -> ComplianceSourceAdapter.build_package() -> CompliancePackage
              -> IdentityResolver.attach(pm_volunteers)   -> resolved + unmatched
              -> build_portal_payload() -> compliance.json -> GCS bucket / Drive folder
```

The portal and `IdentityResolver` depend only on `CompliancePackage` (`src/integrations/compliance_provider.py`), never on a specific source. Identity matching priority: manual override → email → phone → AYSO id → name(+DOB) → name, with a confidence level surfaced for human review. Supporting a new governing system means writing one new adapter subclass; nothing downstream changes. `compliance_publisher.py` writes the portal payload; `etrainu_compliance_matcher.py` feeds ETrainU certifications into the same flow.

**Unmatched volunteers are usually a real-world gap** (they registered in PlayMetrics but aren't in the AYSO governing system yet), not a bug. Manual fixes go in `data\playmetrics\overrides.json` as `{"email":"AYSO-ID"}`.

### eTrainu compliance → board portal (the publish flow)

This repo *produces* data; a companion repo, **region58-portal** (`C:\Users\sdavis\region58-portal`, a Flask app on Cloud Run — service `region58-portal`, region `us-west2`, deploy via `deploy.ps1`), *consumes* it from the **`region58-portal-data` GCS bucket**. The bucket is the hand-off.

**Filename-sync rule:** a file only reaches the portal if it's listed in *both* `playmetrics_portal_upload.py` `UPLOAD_FILES` (the pusher) and the portal's `cloud_storage_source.py` `GCS_FILES` (the fetcher, an allowlist). Add to one without the other and the file sits in the bucket unused.

Two compliance entry points:

```powershell
# 1. Resolve PlayMetrics volunteers against the Sports Affinity governing data
python src\compliance_test.py `
  --credentials "...AdminCredentialsStatusDynamic.xlsx" `
  --details     "...teamAdminDetail.xlsx" `
  --volunteers  "data\playmetrics\volunteers_*.csv" `
  --out data\playmetrics
#   writes compliance_package/resolved/unmatched.json
#   flags: --diagnose (column/capture check) | --explain-unmatched (near-miss vs
#          absent cross-check) | --overrides <json> | --synthetic

# 2. Match non-compliant volunteers to available eTrainu training + stage portal feeds
python src\main.py --etrainu-compliance [--etrainu-live]
#   writes worklist xlsx/csv + compliance_next_steps.json + etrainu_events.json
#   to reports\ AND stages the two portal feeds into data\playmetrics\
#   --etrainu-live scrapes fresh; offline uses the saved events JSON

# 3. Push data\playmetrics\* to the bucket
python src\automation\playmetrics_portal_upload.py
```

### Compliance specifics (the non-obvious parts)

- **Matcher** (`src/integrations/etrainu_compliance_matcher.py`): `build_remediation` routes each gap to a channel — **etrainu** (coach/referee courses → next qualifying scheduled session), **portal** (online certs → static AYSO links), **admin** (risk_status / unresolved identity). Policy is a faithful port of the Region 58 Google Apps Script: only **4 tracked roles** (Head Coach, Assistant Coach, Referee, Youth Referee); **Youth Referees are exempt from SafeSport + Fingerprinting**; coach licenses are checked for age-adequacy (a 10U coach holding an 8U license is "insufficient").
- `write_portal_next_steps` emits a **dict** `{generated_at, volunteers:[...]}`, not a bare list — the portal joins on `volunteers`.
- **Affinity export gotcha:** the `teamAdminDetail` export carries a title-banner row ("Administrator Information Report") that shifts the real headers down one. `AffinityComplianceAdapter._read_excel_skip_banner` detects and skips it — never assume row 0 is the header for these exports.

### eTrainu scraper traps (`src/automation/etrainu_manager.py`)

Reached via Sports Connect SSO (`etrainu_config.volunteer_id`). Live scrape walks N months (`scrape_months`) within a radius (`#geoRadiusSelect`, `location_radius_km`); month nav is `#next-month` / `#prev-month`. Two parsing traps that have bitten before:

- `#noResultsMessage` is **always** in the DOM and carries a `hidden` class when results exist — only treat "no results" when it's present **and not** hidden.
- The location column embeds a `.special-instructions` div; strip it off before reading the address or it gets glued onto the location string.

### Configuration and credentials

- `config/config.json` (copy from `config.example.json`) — org id, season, report definitions with saved-report IDs and wait times, Access DB path, Drive folder id.
- Credentials are CSVs in `config/` (`sports_connect_creds.csv`, `playmetrics_creds.csv`) managed by `utilities/credentials.py`; Google service-account JSONs also live at repo root / `config/`. None of these are committed patterns to replicate — keep secrets out of new code paths.
- State/data: `data/downloads/` (report exports, JSON result files), `data/pm_chrome_profile/` (persistent Chrome profile for PlayMetrics), `logs/`.

### Data, PII & secrets

- **`data/` holds PII** (volunteer rosters, compliance, downloads) and is gitignored — never commit it or paste its contents anywhere shared.
- The portal's `user_roles.json` is config **baked into the portal image at deploy** (not the bucket); access changes need a portal redeploy, not a refresh.
- Keep credentials in the gitignored `config/` CSVs; prefer Secret Manager over cleartext env vars for the portal's OAuth/Flask keys.

### Gotchas

- `src/automation/game_card_processor - Copy*.py` are stale manual backups — only `game_card_processor.py` is live; don't import or edit the copies.
- Selenium flows are timing-sensitive; per-report `wait_time` values in `config.json` exist because the reporting site is slow. Prefer `ElementInteractor`/explicit waits over raw `time.sleep` when adding steps.
- This is a Windows-first project (Visual Studio `.sln`/`.pyproj`, `run.bat`, Access DB via COM); shell examples should use Windows paths.
