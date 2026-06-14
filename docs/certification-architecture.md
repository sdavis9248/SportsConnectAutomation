# Participant & Certification Architecture (recommendation)

**Status:** proposal · **Date:** 2026-06-14 · **Builds on:** `docs/ayso-architecture/schema.sql`

## 1. Goal

A general-purpose, **temporal** model for managing who must hold which credentials,
when, and whether they do — driven by data we ingest from outside systems with full
provenance. General enough that the *same* machinery serves:

- **Volunteers** — coach/referee certifications (Safe Haven, SafeSport, licenses, …).
- **Players** — documents (birth certificate, medical release, photo consent).
- Any future participant type, credential, or requirement.

Three temporal axes, all modeled the same way (half-open ranges `[begin, end)`, where
`end = NULL` means "still in effect"):

1. **People hold roles** over time — `active_from / active_to`.
2. **Roles require credentials** over time — `required_from / required_to` (when a rule
   was introduced and when it was retired).
3. **People hold credentials** over time — `valid_from / valid_to` (issued → expires).

The core query is then: **given a person and a date, what is required vs. what is held →
what's missing**, with the evidence and source for everything held.

## 2. What we already have

`docs/ayso-architecture/schema.sql` is ~80% of this and is a solid foundation. It already
gives us, temporally:

| Concept in your vision | Existing table | Already temporal? |
|---|---|---|
| Person (canonical identity) | `person` | n/a (has `external_ref` JSONB) |
| Person holds typed roles over time | `person_role` (`role_type` = PLAYER/VOLUNTEER/…) | ✅ `valid_during`, no-overlap |
| Role ↔ required credential, with dates | `volunteer_requirement` | ✅ `valid_during` = required_from/to |
| Person holds a credential over time | `person_certification` | ✅ `valid_during` + `issuer`/`credential_ref`/`metadata` |
| One cert satisfies another | `certification_equivalency` | ✅ |
| Assignments per program/season | `volunteer_assignment` | ✅ |

So this is **refinement, not a rewrite.** The deltas below generalize "volunteer" →
"participant," add a real **verification/provenance** layer, and add an **identity
resolution** layer (which is exactly the matcher work we just built).

## 3. Recommended generalizations (the deltas)

### 3.1 Participant = one identity + typed roles; "volunteer" is a role *characteristic*

One canonical **`participant`** row is the identity for everyone — player, volunteer,
guardian. What a person *is* at a given time is expressed as **roles held over time**
(`participant_role`): Head Coach, Assistant Coach, Referee, Player, Guardian, Team
Manager. Crucially:

- **"Volunteer" is not a role you hold — it's a *characteristic of* a role**
  (`role_type.is_volunteer`). Head Coach / Assistant Coach / Referee / Team Manager are
  volunteer roles; Player / Guardian are not. Being a volunteer role is what pulls in
  certification **requirements** (§3.2). `role_type.tracked` flags the four
  compliance-tracked roles.
- **"Youth Referee" is not a separate role** — it's a **Referee who is a minor** at the
  date in question, derived from `participant.birthdate` vs. the age of majority. Minor
  status is what fires the SafeSport/fingerprinting exemption (§3.2). This removes a whole
  class of "which youth-type do I assign?" data-entry error: assign `REFEREE`, and age
  decides the rest.
- Seed `GUARDIAN`; add a **guardian ↔ dependent** link (a player's birth cert is furnished
  by a guardian):

```sql
CREATE TABLE person_relationship (
  person_relationship_id UUID PRIMARY KEY,
  from_person_id UUID NOT NULL REFERENCES person(person_id),  -- guardian
  to_person_id   UUID NOT NULL REFERENCES person(person_id),  -- dependent/player
  relationship_code TEXT NOT NULL,         -- GUARDIAN_OF, EMERGENCY_CONTACT, …
  valid_during   DATERANGE NOT NULL
);
```

> Naming: you can rename `person`→`participant` cosmetically, but I'd keep `person` — it's
> the *identity*; "participant" is just a person who currently holds any role. Don't fork
> the identity table by type; that's the mistake the role model exists to avoid.

### 3.2 Generalize requirements beyond volunteers → `requirement`

`volunteer_requirement` only keys on `volunteer_type`. Replace it with a requirement that
can attach a credential to **any qualifying context**, still temporal:

```sql
CREATE TABLE requirement (
  requirement_id     UUID PRIMARY KEY,
  credential_code    TEXT NOT NULL REFERENCES credential_type(credential_code),
  -- the context this applies to (any subset; NULLs = "any"):
  role_type_code     TEXT REFERENCES role_type(role_type_code),       -- e.g. PLAYER
  volunteer_type_code TEXT REFERENCES volunteer_type(volunteer_type_code), -- e.g. HEAD_COACH
  scope              JSONB,        -- optional: {"age_group":"10U"}, {"play_level":"Core"}…
  requirement_level  TEXT NOT NULL DEFAULT 'REQUIRED',  -- REQUIRED | RECOMMENDED
  valid_during       DATERANGE NOT NULL                 -- required_from / required_to
);
```

This lets **PLAYER → BIRTH_CERTIFICATE** and **HEAD_COACH → SAFE_HAVEN** live in one table,
and lets a rule turn on/off by date (your "introduced as required / later retired").

**Exemptions** are first-class and **conditional**. Region 58 policy — "Youth Referees are
exempt from SafeSport + Fingerprinting" — is modeled as an exemption on the **Referee**
role that only applies when the holder is a minor (`applies_when {"is_minor": true}`,
evaluated from birthdate vs. `as_of`). No separate youth role, no duplicated requirement
sets:

```sql
CREATE TABLE requirement_exemption (
  requirement_exemption_id UUID PRIMARY KEY,
  credential_code TEXT NOT NULL REFERENCES credential_type(credential_code),
  role_type_code  TEXT NOT NULL REFERENCES role_type(role_type_code),
  applies_when    JSONB,          -- e.g. {"is_minor": true}; NULL = always
  reason          TEXT,
  valid_during    DATERANGE NOT NULL
);
```

**Age-adequacy** (a 10U coach needs a license that covers ≥10U) is a `sufficiency` rule —
generalize `certification_equivalency` to carry an optional predicate:

```sql
CREATE TABLE credential_sufficiency (
  satisfies_code TEXT NOT NULL REFERENCES credential_type(credential_code), -- the requirement
  by_code        TEXT NOT NULL REFERENCES credential_type(credential_code), -- what the person holds
  predicate      JSONB,   -- e.g. {"min_age_covered": "$scope.age_group"}; NULL = always
  PRIMARY KEY (satisfies_code, by_code)
);
```

### 3.3 Split "holds a credential" from "who verified it" (provenance)

This is the part you specifically called out — *"pull in from outside the verifications,
who the source was."* Today `person_certification` mixes the fact and the evidence. Split:

```sql
-- domain-neutral rename of certification_type
CREATE TABLE credential_type (
  credential_code TEXT PRIMARY KEY,
  description     TEXT NOT NULL,
  domain          TEXT NOT NULL DEFAULT 'ANY',  -- VOLUNTEER | PLAYER | ANY
  renews          BOOLEAN NOT NULL DEFAULT TRUE  -- birth cert = false (never expires)
);

-- the FACT that a person holds a credential for a window (domain-neutral rename)
CREATE TABLE participant_credential (
  participant_credential_id UUID PRIMARY KEY,
  person_id        UUID NOT NULL REFERENCES person(person_id),
  credential_code  TEXT NOT NULL REFERENCES credential_type(credential_code),
  valid_during     DATERANGE NOT NULL,            -- valid_from / valid_to (expiry)
  detail           TEXT,                           -- license level, referee grade, …
  status           TEXT NOT NULL DEFAULT 'ACTIVE'  -- ACTIVE | REVOKED | SUPERSEDED
);

-- one or more VERIFICATIONS of that credential, each with its source (provenance trail)
CREATE TABLE credential_verification (
  credential_verification_id UUID PRIMARY KEY,
  participant_credential_id  UUID NOT NULL REFERENCES participant_credential(participant_credential_id),
  source_system    TEXT NOT NULL,    -- 'sports_affinity', 'playmetrics', 'manual', 'jdp'…
  source_ref       TEXT,             -- native id / export row / file
  method           TEXT,             -- 'export', 'api', 'document_review', 'self_attested'
  verified_by      TEXT,             -- person/automation that recorded it
  observed_at      TIMESTAMPTZ NOT NULL,  -- when WE saw this (the export/pull time)
  evidence_uri     TEXT,             -- scan/screenshot/file
  confidence       TEXT,             -- high | medium | low
  raw              JSONB
);
```

Why the split matters here specifically:

- **It captures history we currently can't.** Affinity report 143 is a *current-state*
  snapshot — re-pulling it each period and writing a `credential_verification` row with
  `observed_at` is how true credential history finally accrues (our standing limitation).
- **Multiple sources can corroborate** one credential (Affinity says valid; a JDP
  background check says valid) without duplicating the credential.
- **Birth certificate** fits unchanged: `credential_type('BIRTH_CERTIFICATE', domain=PLAYER,
  renews=false)`, one `participant_credential` with `valid_to = NULL`, verified once by
  `method='document_review', verified_by='<registrar>'`.

### 3.4 Identity resolution as a first-class layer (this is the matcher we just built)

External systems don't share a key. Promote `person.external_ref` to a table — this is
exactly the alias pool / `IdentityResolver` from `compliance_provider.py`, persisted:

```sql
CREATE TABLE external_identity (
  external_identity_id UUID PRIMARY KEY,
  person_id     UUID NOT NULL REFERENCES person(person_id),
  source_system TEXT NOT NULL,     -- 'sports_affinity' | 'playmetrics'
  source_key    TEXT NOT NULL,     -- AYSO id | PlayMetrics member id | email | phone
  key_kind      TEXT NOT NULL,     -- 'native_id' | 'email' | 'phone' | 'name_dob'
  match_method  TEXT,              -- email | source_id | phone | name_dob | *_history | manual
  confidence    TEXT,
  valid_during  DATERANGE NOT NULL,
  UNIQUE (source_system, key_kind, source_key, valid_during)
);
```

Ingestion becomes: resolve each source row to a `person_id` via `external_identity`
(creating the person + alias on first sight), then write credentials / assignments /
verifications against that canonical id. The match-method/confidence we already compute
become columns — the work is done, it just needs a home.

## 4. The core resolution (the whole point)

`required(person, as_of)` − `held(person, as_of)` = **gaps**. In SQL against the model:

```sql
-- what a person must hold on a date, given the roles/assignments active that date
WITH active_contexts AS (
  SELECT pr.role_type_code, va.volunteer_type_code, va.scope
  FROM person_role pr
  LEFT JOIN volunteer_assignment va
    ON va.person_role_id = pr.person_role_id AND va.valid_during @> :as_of::date
  WHERE pr.person_id = :pid AND pr.valid_during @> :as_of::date
),
required AS (
  SELECT DISTINCT r.credential_code
  FROM requirement r JOIN active_contexts c
    ON (r.role_type_code IS NULL OR r.role_type_code = c.role_type_code)
   AND (r.volunteer_type_code IS NULL OR r.volunteer_type_code = c.volunteer_type_code)
  WHERE r.valid_during @> :as_of::date AND r.requirement_level = 'REQUIRED'
    AND NOT EXISTS (  -- minus exemptions active that date
      SELECT 1 FROM requirement_exemption e
      WHERE e.valid_during @> :as_of::date
        AND (e.volunteer_type_code = c.volunteer_type_code OR e.role_type_code = c.role_type_code))
),
held AS (  -- held creds + anything that sufficiently satisfies them
  SELECT s.satisfies_code AS credential_code
  FROM participant_credential pc
  JOIN credential_sufficiency s ON s.by_code = pc.credential_code
  WHERE pc.person_id = :pid AND pc.valid_during @> :as_of::date AND pc.status='ACTIVE'
  UNION
  SELECT pc.credential_code FROM participant_credential pc
  WHERE pc.person_id = :pid AND pc.valid_during @> :as_of::date AND pc.status='ACTIVE'
)
SELECT r.credential_code AS gap
FROM required r LEFT JOIN held h USING (credential_code)
WHERE h.credential_code IS NULL;
```

`asOf` is already the convention in `endpoints.md` (`GET …/compliance?asOf=YYYY-MM-DD`).
This query *is* `build_portal_payload`'s compliance derivation — moved from ad-hoc Python
onto a queryable model, so "what did we require / what did they hold on date X" is answerable
retroactively, not just for today.

## 5. Where to store it — recommendation

Today's stack is producer (Selenium/Python on Windows) → JSON files → GCS bucket → Flask
portal. No database, single writer, read-mostly. Options:

| | Effort | Fit | Notes |
|---|---|---|---|
| **A. Cloud SQL (Postgres)** | High | Med | `schema.sql` runs ~as-is (range types, GiST `EXCLUDE`). Proper integrity, but new managed infra to run/connect from Cloud Run **and** the Windows producer; overkill for ~1.5k people. |
| **B. SQLite system-of-record** ✅ | Low | High | One `region58.db` the producer builds/queries; export as-of JSON snapshots to the bucket (consumer seam unchanged). Real relational + temporal queries, **zero new infra**, Windows-friendly. |
| **C. Pure-Python over JSON** | Lowest | Low | Reimplements joins/temporal logic in Python; no ad-hoc querying; gets messy. Stepping stone only. |

**Recommendation: B — SQLite as the canonical "certification system of record."** The
producer owns it; the portal keeps consuming exported JSON (Lookup + compliance unchanged
in shape, richer in content). SQLite lacks range types + `EXCLUDE`, so adapt the DDL:
store `*_from DATE` / `*_to DATE` (NULL = open), enforce no-overlap in the ingestion layer,
and index `(person_id, code, from, to)`. The SQL stays ~portable, so **Postgres is a clean
upgrade path** if a second region joins or you need concurrent writers. Don't start on
Postgres infra for a single-region, single-writer dataset.

## 6. How current work maps in (nothing is wasted)

| Current asset | Becomes |
|---|---|
| `IdentityResolver` + `HistoryIndex` (alias pool) | the `external_identity` resolution layer; match-method/confidence → columns |
| `credential_history.py` cert **windows** | `participant_credential.valid_during` directly |
| Affinity report 143 pull | `credential_verification` rows (`source='sports_affinity'`, `observed_at`=pull) → accrues real history |
| `teamAdminDetail` per season | `volunteer_assignment` (temporal) |
| PlayMetrics volunteers/enrollment | `person_role` / `enrollment` |
| `compliance_provider` CERT_TYPES + Region 58 policy (4 roles, Youth-Ref exemptions, age-adequate licenses) | seeds for `credential_type`, `requirement`, `requirement_exemption`, `credential_sufficiency` |
| `AffinityComplianceAdapter` (source-agnostic adapter contract) | the ingestion adapter pattern — unchanged philosophy, now writing to the DB |

## 7. Suggested rollout (incremental, each phase shippable)

1. **Schema + seeds.** Adapt `schema.sql` to SQLite; seed role/volunteer/credential types,
   the real AYSO `requirement` rows *with their introduced dates*, exemptions, sufficiency.
2. **Ingestion + identity.** Build `external_identity` from the alias pool; load persons,
   credentials (+ verification provenance), assignments, enrollments.
3. **Resolution.** Implement `required/held/gaps as_of`; have `compliance_provider` derive
   from the DB (keep the adapter/`CompliancePackage` contract so the portal is untouched).
4. **Export + portal.** Emit as-of JSON snapshots to the bucket; Lookup/compliance render
   richer data (full verification trail, "required since" dates).
5. **Players.** Add `BIRTH_CERTIFICATE`, `MEDICAL_RELEASE`, `PHOTO_CONSENT` (domain=PLAYER)
   + PLAYER requirements — same engine, no new code.

## 8. First cut — implemented

A runnable SQLite implementation of this model lives in **`src/integrations/cert_model/`**:

- `schema_sqlite.sql` — the model above as SQLite (temporal `(from_date, to_date)` pairs,
  `role_type.is_volunteer`/`tracked`, conditional `requirement_exemption.applies_when`).
- `seed_region58.sql` — roles, credential types, and the **real Region 58 requirement
  set** ported from `etrainu_compliance_matcher.DEFAULT_REQUIRED_BY_ROLE`, with the
  youth-referee exemption as an age-conditional rule. (Requirement *introduced dates* are
  best-effort placeholders flagged `-- verify`.)
- `store.py` — the engine: `build()`, ingestion helpers (`add_participant`, `add_role`,
  `add_credential` + verification, `resolve_or_create_identity`), and the as-of resolution
  (`required_as_of` / `held_as_of` / `compliance_as_of`). `python -m integrations.cert_model.store`
  runs a worked demo; `tests/unit/test_cert_model.py` covers it.

Demo output (shows the three core behaviors): a Head Coach's only gap is SafeSport; a
**minor** Referee needs 5 certs while an **adult** Referee needs 7 (difference = age alone);
and the same coach required 6 certs in 2017 vs. 7 today (SafeSport introduced 2018).

**Portal follow-on:** because the entity is now a participant, the admin **"Lookup"** tab
becomes **"Participant Lookup"** — same UI, but it will resolve players and guardians too
once those are populated (today the feed is volunteer-only).

## 9. Open decisions for you

- **Storage:** confirm SQLite-system-of-record (B) vs. going straight to Cloud SQL (A).
- **Scope next:** wire ingestion (Affinity/PlayMetrics → this DB) for volunteers first,
  or model players/birth-certs in the same pass?
- **History depth:** start snapshotting Affinity each period now (to accrue real
  `credential_verification` history) even before the DB is the system of record?
- **Requirement dates:** confirm the real AYSO introduced dates for SafeSport, cardiac,
  concussion, fingerprinting (the seed marks these `-- verify`).
