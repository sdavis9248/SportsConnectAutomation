# Compliance features — scope & hand-off

Scope for two related volunteer-compliance deliverables. Both ride on the existing
producer→bucket→portal architecture and the `CompliancePackage` already built by
the compliance pipeline.

- **Producer:** `AYSORegionAutomation` (this repo) — Python/Selenium, runs locally,
  pulls PlayMetrics + Sports Affinity, publishes feeds to the GCS bucket
  `region58-portal-data`.
- **Consumer:** `region58-portal` (`github.com/sdavis9248/region58-portal`) — Flask
  on Cloud Run, reads the bucket, Google OAuth login restricted to `ayso58.org`,
  roles admin/director/viewer.

> This is real volunteer PII. Never commit `data/`. Never email real volunteers
> without `test_mode` + an explicit confirmation.

## Read before coding
- `Compliance_Provider_Architecture.md`
- `src/integrations/compliance_provider.py` — `CompliancePackage` (normalized,
  source-agnostic). `AffinityComplianceAdapter.build_package()` reads the Affinity
  "Admin Credentials" + `teamAdminDetail` exports and builds one `ComplianceRecord`
  per volunteer with `source_id` (AYSO ID) + `certifications`: `safesport`,
  `fingerprinting`, `background_check`, `coach_license` (level),
  `referee_certification` (grade), with dates/expiry. `IdentityResolver.resolve()`
  **splits** that full package into PM-matched (resolved) vs unmatched — i.e. the
  full credential set already exists; the portal currently only surfaces the matched
  subset.
- `src/integrations/etrainu_compliance_matcher.py` — `build_remediation()` returns
  per-volunteer `gaps`, each tagged `channel ∈ {etrainu, portal, admin}`.
  `write_portal_next_steps()` emits `compliance_next_steps.json` =
  `{generated_at, volunteers:[{email, division, position, matched, next_step,
  next_steps}]}`. Policy already enforced here: only **4 tracked roles** (Head
  Coach, Assistant Coach, Referee, Youth Referee); **Youth Referees exempt from
  SafeSport + Fingerprinting**; coach licenses checked for **age-adequacy**.
- `src/automation/sports_affinity_manager.py` — how the Affinity exports are pulled.
- `src/automation/waitlist_notifier.py` — **use as the email template**: Gmail OAuth2
  send, `test_mode` (redirect all mail to `email_config.test_email`), `max_emails`
  throttle, rate limiting, per-recipient HTML. `src/automation/waitlist_persistence.py`
  for the send-history/cadence pattern.
- `region58-portal/app.py` — `login_required` decorator, role checks,
  `render_template`, `CloudStorageSource` + `GCS_FILES`, `gcs.Client()` bucket
  read/write; `deploy.ps1`.

## Step 0 (gates Deliverable B's value — do first)
Verify the **Sports Affinity export scope**. "Look up anyone, current or **past**"
only works if the Admin Credentials / `teamAdminDetail` export contains the **full
membership**, not just current-season / assigned admins. Check how
`sports_affinity_manager.py` runs the export; if it's season-scoped, adjust it to
pull full membership. Report findings before building B.

## Deliverable A — Per-volunteer compliance reminder emails
A new `--compliance-reminders` flag + `src/automation/compliance_reminder_notifier.py`
that emails each volunteer the **specific** items they're missing and the next step
for each.

- **Source:** the latest `compliance_next_steps.json` (produced by
  `--etrainu-compliance`) — reflects the last compliance run, so reminders contain
  only real gaps.
- **Content:** **templated** (deterministic, built from `next_steps` — no
  LLM-invented steps), worded by channel: `etrainu` → the qualifying course/session;
  `portal` → the static AYSO cert link (e.g. SafeSport).
- **Admin-channel gaps:** **do not email the volunteer** (they can't self-fix); roll
  these into a **registrar digest** instead.
- Skip volunteers with no volunteer-actionable gaps.
- **Sending:** reuse `waitlist_notifier`'s Gmail OAuth2 path + `test_mode`/`test_email`
  + `max_emails` throttle + a confirmation prompt before any production send.
- **Cadence:** track sends (`waitlist_persistence`-style) with a configurable
  cooldown (~7–10 days) so nobody is re-reminded every run.
- **Config:** `email_config` / a new `compliance_reminder_config` in `config.json`
  (gitignored — document new keys in `config/config.example.json`).
- This improves outreach only; compliance status and eligibility decisions stay the
  registrar's call.

## Deliverable B — Full-credentials "Volunteer Lookup" portal tab
Search **any** volunteer (current or past) and see their certifications,
independent of whether they've registered in PlayMetrics this season.

- **Producer:** publish the **whole `CompliancePackage`** (all records — reuse
  `build_package`, not just resolved) to the bucket as a new feed
  (e.g. `volunteer_credentials.json`); add to `UPLOAD_FILES`.
- **Consumer:** add the feed to `GCS_FILES` + a new **admin-only** tab
  (`login_required` + admin/refadmin role — credential PII incl. background-check
  status, never public). Search by name / AYSO ID / email → show the 5 cert types,
  level/grade, obtained/expire dates, and a "registered in PlayMetrics this season?
  yes/no" flag (cross-ref the PM volunteers feed).
- Independent of Deliverable A (doesn't touch reminder logic) — can ship first.

## Design note (2026-06-14): temporal-window credential model
Per the checked-in `docs/ayso-architecture/` (a temporal-first AYSO model: a
canonical **person** holds each certification over validity **windows**
`[begin, end)`, and compliance is **derived as-of a date**, not stored), the
credential feed is **not** flat per-season snapshots.

`volunteer_credentials.json` (built by
`integrations/credential_history.build_credential_history`) is keyed by AYSO ID;
each cert is a set of merged validity **windows** across seasons (same obtain
date = one window observed in multiple seasons; a new obtain date = a renewal =
a new window), plus a derived `current` (valid as of build) and
`observed_seasons` (the activity timeline). Possession on any date is derivable
from the windows. **The Volunteer Lookup tab should render each cert's timeline +
a "valid as of <date>" check, not a per-season grid.**

Producer is wired: `--affinity-credential-history` pulls the configured
`sports_affinity_config.credential_seasons` (report 143, by seasonguid value)
and writes the feed; `playmetrics_portal_upload.py` publishes it. Per-season
volunteer_type/division ("assignments") is a follow-up needing the
`teamAdminDetail` roster export.

## Process
1. Do **Step 0** and report.
2. Produce a short **plan** (files changed, email-content design, lookup-tab UI,
   bucket feed name, config keys, any IAM) and wait for approval.
3. Implement with `test_mode` + a **dry-run/preview** that writes drafted emails to
   `reports/` for review, and show a sample rendered email + a sample lookup view
   (synthetic data, no real PII) before any real send or deploy.

## Locked decisions (defaults)
| Item | Default |
|---|---|
| Reminder email copy | Templated (no LLM) |
| Admin-channel gaps | Registrar digest; not emailed to the volunteer |
| Reminder cadence | Tracked sends + ~7–10 day cooldown |
| Reminder source/trigger | `compliance_next_steps.json` via `--compliance-reminders` |
| First send | `test_mode` + small `max_emails` + confirm prompt |
| Lookup tab access | Admin-only (admin/refadmin), behind `login_required` |
| Lookup searchable by | name, AYSO ID, email |
| Lookup source | full `CompliancePackage` (all records) |
| Past volunteers | requires full-membership Affinity export (Step 0) |
