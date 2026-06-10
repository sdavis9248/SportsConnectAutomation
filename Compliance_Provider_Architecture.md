# Volunteer Compliance Provider — Architecture

Goal: surface coach / assistant-coach / referee certifications (currently from
Sports Affinity) in the board portal **now**, built so that when the new governing
system arrives we write one adapter and change nothing else.

## Layers

1. **CompliancePackage** (`compliance_provider.py`) — the source-agnostic contract.
   Normalized certs keyed by stable names (`id_verified`, `safe_haven`,
   `concussion`, `safesport`, `cardiac`, `fingerprinting`, `background_check`,
   `coach_license`, `referee_certification`), a normalized `risk_status`, identity
   fields, and a `raw` blob for audit. Serializes to JSON for the portal. The portal
   and resolver depend only on this — never on Affinity.

2. **ComplianceSourceAdapter** (ABC) — `build_package() -> CompliancePackage`.
   - `AffinityComplianceAdapter` maps the existing **Admin Credentials** (cert flags,
     keyed by `Admin ID`) and **Admin Details (All Fields)** (name/email/DOB/AYSO ID)
     exports onto the package. Reuses the column names already in
     `VolunteerComplianceHandler`.
   - A future system = a new subclass. Nothing downstream changes.

3. **IdentityResolver** — bridges the gap that PlayMetrics has no AYSO ID. Matches a
   PM volunteer to a governing-system record in priority order: manual **override** →
   **email** → **AYSO id** (if present) → **name (+DOB)** → **name**. Returns a match
   confidence (high/medium/low/none) so the portal can flag low-confidence and
   unmatched volunteers for human review. An override map (volunteer email → AYSO ID)
   lets the registrar pin ambiguous ones once, persistently.

## Data flow (temporary Affinity bridge)

```
SportsAffinityManager.export_all_reports()         # already exists
   -> Admin Credentials.xlsx + Admin Details.xlsx
AffinityComplianceAdapter(cred, details).build_package()
   -> CompliancePackage  (JSON-able, source-agnostic)
IdentityResolver(package).attach(pm_volunteers)    # pm_volunteers from volunteers.csv
   -> resolved (volunteer + certs + confidence) + unmatched lists
publish -> board portal (GCS json the portal reads)
```

## Switching governing systems later

Implement `NewSystemAdapter(ComplianceSourceAdapter)` returning a `CompliancePackage`.
Swap which adapter is constructed. Resolver, package schema, portal, and the
override map are unchanged. If the new system exposes email or the PM volunteer id
directly, identity resolution gets stronger automatically (more high-confidence
matches, fewer name fallbacks).

## Open items
- Confirm the Admin Details "All Fields" export includes Email (drives the
  high-confidence match). If yes, most volunteers resolve by email; the rest fall to
  name and surface for review.
- Portal ingestion format/location (e.g. a JSON object in `gs://region58-portal-data/`)
  so the publisher writes what the portal expects.
- Optional: a small override map file for the handful of name-only / ambiguous cases.
