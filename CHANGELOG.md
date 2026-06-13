# Changelog

All notable changes to this project are recorded here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/). This project is not formally
versioned, so entries are grouped by date (newest first). Entries dated before
2026-06-13 are reconstructed from git commit history.

Per-module modification history: each module also carries a `Modification History`
block in its docstring for changes to that file specifically. This CHANGELOG is the
project-level summary; the module blocks are the file-level detail.

## 2026-06-13

### Added
- This `CHANGELOG.md` and the per-module `Modification History` docstring convention.
- Waitlist curation Phase 1 on PlayMetrics: `--waitlist-curate` produces a
  confirmed / declined / non-responder report and a manual to-remove candidate list.
- `data/knowledge/` curated knowledge base is now versioned (gitignore exception);
  it is hand-maintained, non-PII policy/FAQ content loaded into the email assistant.

### Changed
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
