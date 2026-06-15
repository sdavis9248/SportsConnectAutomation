-- Participant & certification model — SQLite system-of-record (first cut).
-- See docs/certification-architecture.md. Postgres (range types + GiST EXCLUDE) is
-- the later port; here temporal validity is a (from_date, to_date) DATE pair of ISO
-- 'YYYY-MM-DD' strings, to_date NULL = open ("still in effect"). A row is in effect
-- at :as_of when  from_date <= :as_of AND (to_date IS NULL OR :as_of < to_date)
-- (half-open [from, to)). SQLite has no EXCLUDE; no-overlap is enforced app-side.
--
-- Model shape (per the refined concept):
--   * PARTICIPANT is the one identity (player, volunteer, guardian — all the same row).
--   * A participant holds typed ROLES over time (Head Coach, Referee, Player, ...).
--   * "Volunteer" is a CHARACTERISTIC of a role (role_type.is_volunteer), not a role
--     itself — and that's what pulls in certification REQUIREMENTS.
--   * "Youth Referee" is NOT a separate role: it's a REFEREE who is a minor at the
--     time in question (derived from birthdate vs. age of majority). Minor status is
--     what triggers the SafeSport/fingerprinting exemption.

PRAGMA foreign_keys = ON;

-- ── Participants & roles ──────────────────────────────────────────────────
CREATE TABLE participant (
  participant_id TEXT PRIMARY KEY,
  legal_name     TEXT NOT NULL,
  preferred_name TEXT,
  birthdate      TEXT,                        -- drives minor / age-group derivation
  email          TEXT,
  phone          TEXT,
  risk_status    TEXT,                        -- denormalized convenience (also a credential)
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  external_ref   TEXT                         -- JSON
);

CREATE TABLE role_type (
  role_type_code TEXT PRIMARY KEY,
  description    TEXT NOT NULL,
  is_volunteer   INTEGER NOT NULL DEFAULT 0,  -- characteristic: a volunteer role (carries cert reqs)
  tracked        INTEGER NOT NULL DEFAULT 0   -- compliance-tracked (Region 58: the 4 coach/ref roles)
);

CREATE TABLE participant_role (         -- a participant holds a role over a window
  participant_role_id TEXT PRIMARY KEY,
  participant_id      TEXT NOT NULL REFERENCES participant(participant_id),
  role_type_code      TEXT NOT NULL REFERENCES role_type(role_type_code),
  scope               TEXT,                  -- JSON e.g. {"age_group":"10U","team":"...","season":"MY2026"}
  from_date           TEXT NOT NULL,
  to_date             TEXT
);
CREATE INDEX ix_participant_role ON participant_role(participant_id, role_type_code, from_date);

CREATE TABLE participant_relationship ( -- guardian -> dependent, etc.
  participant_relationship_id TEXT PRIMARY KEY,
  from_participant_id TEXT NOT NULL REFERENCES participant(participant_id),
  to_participant_id   TEXT NOT NULL REFERENCES participant(participant_id),
  relationship_code   TEXT NOT NULL,         -- GUARDIAN_OF | EMERGENCY_CONTACT | ...
  from_date           TEXT NOT NULL,
  to_date             TEXT
);

-- ── Credentials (works for volunteer certs AND player documents) ───────────
CREATE TABLE credential_type (
  credential_code TEXT PRIMARY KEY,
  description     TEXT NOT NULL,
  domain          TEXT NOT NULL DEFAULT 'ANY',   -- VOLUNTEER | PLAYER | ANY
  renews          INTEGER NOT NULL DEFAULT 1,     -- 0 = never expires (e.g. birth cert)
  sensitive_evidence INTEGER NOT NULL DEFAULT 0   -- 1 = verify-and-DISCARD: the artifact
                                                  -- (birth cert / passport image) is NEVER
                                                  -- persisted; only provenance is kept.
);

CREATE TABLE participant_credential (   -- the FACT that a participant holds a credential
  participant_credential_id TEXT PRIMARY KEY,
  participant_id   TEXT NOT NULL REFERENCES participant(participant_id),
  credential_code  TEXT NOT NULL REFERENCES credential_type(credential_code),
  from_date        TEXT,                       -- valid_from (issue); NULL = unknown
  to_date          TEXT,                       -- valid_to (expiry); NULL = open
  detail           TEXT,                       -- license level, referee grade, ...
  status           TEXT NOT NULL DEFAULT 'ACTIVE',   -- ACTIVE | UNVERIFIED | REVOKED | SUPERSEDED
  source           TEXT
);
CREATE INDEX ix_participant_credential ON participant_credential(participant_id, credential_code, from_date);

CREATE TABLE credential_verification (  -- one+ verifications, each with its source (provenance)
  credential_verification_id TEXT PRIMARY KEY,
  participant_credential_id  TEXT NOT NULL REFERENCES participant_credential(participant_credential_id),
  source_system  TEXT NOT NULL,              -- sports_affinity | playmetrics | manual | jdp ...
  source_ref     TEXT,
  method         TEXT,                       -- export | api | document_review | self_attested
  verified_by    TEXT,
  observed_at    TEXT NOT NULL,              -- when WE saw it (export/pull time) — accrues history
  evidence_kind  TEXT,                       -- what was shown: birth_certificate | passport | electronic_record ...
  evidence_ref   TEXT,                       -- NON-sensitive token only: issuing authority, hash, last-4 — NEVER the doc
  evidence_uri   TEXT,                       -- link to NON-sensitive electronic evidence; forced NULL for sensitive types
  confidence     TEXT,                       -- high | medium | low
  raw            TEXT                        -- JSON; forced NULL for sensitive types
);

-- ── Requirements (temporal) + exemptions + sufficiency ─────────────────────
CREATE TABLE requirement (              -- a role requires a credential over a window
  requirement_id      TEXT PRIMARY KEY,
  credential_code     TEXT NOT NULL REFERENCES credential_type(credential_code),
  role_type_code      TEXT NOT NULL REFERENCES role_type(role_type_code),
  scope               TEXT,                  -- optional JSON {"age_group":"10U"} ...
  requirement_level   TEXT NOT NULL DEFAULT 'REQUIRED',   -- REQUIRED | RECOMMENDED
  from_date           TEXT NOT NULL,         -- required_from (introduced)
  to_date             TEXT                   -- required_to (retired); NULL = still required
);

CREATE TABLE requirement_exemption (    -- a role is exempt from a credential, optionally only when a condition holds
  requirement_exemption_id TEXT PRIMARY KEY,
  credential_code  TEXT NOT NULL REFERENCES credential_type(credential_code),
  role_type_code   TEXT NOT NULL REFERENCES role_type(role_type_code),
  applies_when     TEXT,                     -- JSON predicate, e.g. {"is_minor":true}; NULL = always
  reason           TEXT,
  from_date        TEXT NOT NULL,
  to_date          TEXT
);

CREATE TABLE credential_sufficiency (   -- holding by_code satisfies satisfies_code (optionally if predicate holds)
  satisfies_code TEXT NOT NULL REFERENCES credential_type(credential_code),
  by_code        TEXT NOT NULL REFERENCES credential_type(credential_code),
  predicate      TEXT,                       -- JSON; NULL = always satisfies (app evaluates predicates)
  PRIMARY KEY (satisfies_code, by_code)
);

-- ── Identity resolution (the matcher / alias pool, persisted) ──────────────
CREATE TABLE external_identity (
  external_identity_id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL REFERENCES participant(participant_id),
  source_system  TEXT NOT NULL,              -- sports_affinity | playmetrics
  source_key     TEXT NOT NULL,              -- AYSO id | member id | email | phone
  key_kind       TEXT NOT NULL,              -- native_id | email | phone | name_dob
  match_method   TEXT,
  confidence     TEXT,
  from_date      TEXT,
  to_date        TEXT
);
CREATE INDEX ix_external_identity ON external_identity(source_system, key_kind, source_key);
