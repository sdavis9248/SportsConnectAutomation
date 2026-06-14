# Changelog

All notable changes to this project are recorded here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/). This project is not formally
versioned, so entries are grouped by date (newest first). Entries dated before
2026-06-13 are reconstructed from git commit history.

Per-module modification history: each module also carries a `Modification History`
block in its docstring for changes to that file specifically. This CHANGELOG is the
project-level summary; the module blocks are the file-level detail.

## 2026-06-14

### Added
- **Compliance matching — multi-season identity pool (`HistoryIndex`).** The
  identity resolver now takes an optional history pool built from
  `volunteer_credentials.json` (all distinct emails/phones/names/DOBs a person has
  had across seasons, via new `credential_history` aliases). When the single
  current-season Affinity export fails to match a PlayMetrics volunteer, the
  resolver falls back to this 1,455-person pool (`*_history` match methods),
  resolving to the person's AYSO id — and preferring the authoritative
  current-season record when one exists. On current data this lifted matches from
  **49 → 136 of 177 (28% → 77%)**: +80 by historical email, +2 by phone, +5 by
  name (flagged low-confidence for review). The 87 new matches resolve to
  *returning volunteers* with no current-season Affinity admin record — i.e. known
  AYSO people who need to renew/re-register, surfaced now instead of "unmatched."
  Auto-enabled in `build_compliance_payload` (history file auto-discovered next to
  the volunteers CSV); add `--history` in `compliance_test.py` to measure.
- **Credential history — teamAdminDetail enrichment + portal labeling.** Prior-roster
  people (in a past season's `teamAdminDetail` but not the current credentials export)
  now carry their last-known risk status (+ expiry) and a thin cert set (license level,
  concussion) as **`unverified` / `source='teamAdminDetail'`** windows — informative but
  never counted as currently valid. The portal labels history-pool matches as
  **"Prior record"** (amber) on the compliance + division views, and the Volunteer Lookup
  shows prior-season certs as "on file · prior season" plus the person's risk status.
- **Participant & certification architecture proposal** — `docs/certification-architecture.md`:
  a general-purpose temporal model (participant + typed roles, temporal requirements,
  credential verification provenance, identity resolution) extending
  `docs/ayso-architecture/schema.sql`, with a SQLite-system-of-record recommendation.
- **Certification system-of-record — runnable first cut** (`src/integrations/cert_model/`):
  `schema_sqlite.sql` + `seed_region58.sql` + `store.py`. A participant holds typed roles
  over time; **"volunteer" is a characteristic of a role** (`role_type.is_volunteer`) that
  pulls in requirements; **"youth referee" is a Referee who is a minor** (age-derived), via
  a conditional exemption (`applies_when {"is_minor": true}`). Compliance is derived as-of
  any date (`required/held/compliance_as_of`). Region 58 policy seeded from
  `etrainu_compliance_matcher`; `tests/unit/test_cert_model.py` (7 tests) covers role
  requirements, age-based exemption, requirement timing, gaps, and identity resolution.

### Fixed
- **Volunteer credential history — date handling.** Affinity exports mix ISO
  (`2022-08-24`) and US (`08/22/2011`) date formats. `credential_history` stored
  them raw, so `_current_window` compared a US-format expiry as a string against an
  ISO `today` and wrongly flagged still-valid certs as expired (e.g. a SafeSport
  good until `11/08/2026` read as not-current). Dates are now normalized to ISO at
  ingestion (`_iso_date`), which fixes both the validity logic and the inconsistent
  display. Regenerating the existing feed corrected validity on **1,141 certs**.

## 2026-06-13

### Added
- This `CHANGELOG.md` and the per-module `Modification History` docstring convention.
- Waitlist curation Phase 1 on PlayMetrics: `--waitlist-curate` produces a
  confirmed / declined / non-responder report and a manual to-remove candidate list.
- `data/knowledge/` curated knowledge base is now versioned (gitignore exception);
  it is hand-maintained, non-PII policy/FAQ content loaded into the email assistant.

### Changed
- **Renamed the project SportsConnectAutomation → AYSORegionAutomation** (the old
  name was anachronistic as Sports Connect is deprecated as the registration
  platform). Renamed the `.sln`/`.pyproj` and updated project-identity references
  in docs and module headers. The `SportsConnectAutomation` *Python class* (the
  Sports Connect browser automation) keeps its name — that integration still
  exists. Repo and local-folder renames are separate manual steps.
- Waitlist check-in (`--waitlist-notify`) now reads the latest PlayMetrics waitlist
  CSV and no longer logs into Sports Connect; keyed on PlayMetrics `player_id`.
- `--pm-download all` now also fetches waitlist, all-players, and player-contacts.
- Registrar email assistant: migrated from raw HTTP to the `anthropic` SDK, model
  `claude-opus-4-8`, stable cached system prompt, knowledge-base loading,
  PlayMetrics data sources (registration-responses, all-players, player-contacts,
  waitlist, payments), and added `--inbox-reset`.
- Refreshed stale docs for the PlayMetrics migration (README, `main.py` docstring,
  registrar assistant header).

### Fixed
- `_extract_body` in the email assistant now handles html-only messages and bodies
  stored as attachments (previously returned empty — "email body did not come through").
- Email assistant reads the PlayMetrics canonical filenames for all-players /
  player-contacts (was loading stale manual exports).
- Restored `registrar_email_assistant.py` after a rebase had corrupted it.
- Knowledge-base policy corrections: official DOB chart (2026/27), 05U session
  details, no multi-child discount, early-bird ended, financial-aid (reviewed —
  not honor system; apply during registration only), teammate/coach requests not
  accommodated in competitive divisions, role-based volunteer contact routing.

## 2026-06-12

### Added
- `CLAUDE.md` guidance file for the repository.

## 2026-06-10 – 2026-06-11

### Added
- ETrainU board-portal publishing, calendar of events, diagnostics, and manager
  enhancements (compliance → portal pipeline).
