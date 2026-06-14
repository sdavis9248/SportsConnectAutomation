-- AYSO Temporal Data Architecture (PostgreSQL)
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- People & roles
CREATE TABLE person (
  person_id      UUID PRIMARY KEY,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  legal_name     TEXT NOT NULL,
  preferred_name TEXT,
  birthdate      DATE NOT NULL,
  email          TEXT,
  phone          TEXT,
  external_ref   JSONB
);

CREATE TABLE role_type (
  role_type_code TEXT PRIMARY KEY,
  description    TEXT NOT NULL
);

CREATE TABLE person_role (
  person_role_id UUID PRIMARY KEY,
  person_id      UUID NOT NULL REFERENCES person(person_id),
  role_type_code TEXT NOT NULL REFERENCES role_type(role_type_code),
  valid_during   TSTZRANGE NOT NULL,
  CHECK (lower(valid_during) < upper(valid_during))
);
CREATE INDEX person_role_ix ON person_role (person_id, role_type_code, valid_during);
ALTER TABLE person_role ADD CONSTRAINT person_role_no_overlap
  EXCLUDE USING gist (person_id WITH =, role_type_code WITH =, valid_during WITH &&);

-- Seasons & programs
CREATE TABLE season (
  season_id    UUID PRIMARY KEY,
  name         TEXT NOT NULL,
  valid_during DATERANGE NOT NULL
);

CREATE TABLE program (
  program_id   UUID PRIMARY KEY,
  season_id    UUID NOT NULL REFERENCES season(season_id),
  name         TEXT NOT NULL,
  valid_during DATERANGE NOT NULL
);

CREATE TABLE division (
  division_id  UUID PRIMARY KEY,
  program_id   UUID NOT NULL REFERENCES program(program_id),
  code         TEXT NOT NULL,
  valid_during DATERANGE NOT NULL
);

CREATE TABLE team (
  team_id      UUID PRIMARY KEY,
  program_id   UUID NOT NULL REFERENCES program(program_id),
  division_id  UUID REFERENCES division(division_id),
  name         TEXT NOT NULL,
  valid_during DATERANGE NOT NULL
);

CREATE TABLE age_group (
  age_group_id     UUID PRIMARY KEY,
  program_id       UUID NOT NULL REFERENCES program(program_id),
  name             TEXT NOT NULL,
  birthdate_during DATERANGE NOT NULL,
  valid_during     DATERANGE NOT NULL
);

-- Enrollment & placement
CREATE TABLE enrollment (
  enrollment_id  UUID PRIMARY KEY,
  person_role_id UUID NOT NULL REFERENCES person_role(person_role_id),
  program_id     UUID NOT NULL REFERENCES program(program_id),
  valid_during   DATERANGE NOT NULL,
  CHECK (lower(valid_during) < upper(valid_during)),
  UNIQUE (person_role_id, program_id)
);

CREATE TABLE enrollment_status_type (
  status_code TEXT PRIMARY KEY,
  description TEXT NOT NULL
);

CREATE TABLE enrollment_status (
  enrollment_status_id UUID PRIMARY KEY,
  enrollment_id        UUID NOT NULL REFERENCES enrollment(enrollment_id) ON DELETE CASCADE,
  status_code          TEXT NOT NULL REFERENCES enrollment_status_type(status_code),
  valid_during         DATERANGE NOT NULL,
  CHECK (lower(valid_during) < upper(valid_during))
);
CREATE INDEX enrollment_status_ix ON enrollment_status (enrollment_id, valid_during);
ALTER TABLE enrollment_status ADD CONSTRAINT enrollment_status_no_overlap
  EXCLUDE USING gist (enrollment_id WITH =, valid_during WITH &&);

CREATE TABLE team_placement (
  team_placement_id UUID PRIMARY KEY,
  enrollment_id     UUID NOT NULL REFERENCES enrollment(enrollment_id) ON DELETE CASCADE,
  team_id           UUID NOT NULL REFERENCES team(team_id),
  valid_during      DATERANGE NOT NULL,
  CHECK (lower(valid_during) < upper(valid_during))
);
CREATE INDEX team_placement_ix ON team_placement (team_id, valid_during);

-- Volunteers & certifications
CREATE TABLE volunteer_type (
  volunteer_type_code TEXT PRIMARY KEY,
  description         TEXT NOT NULL
);

CREATE TABLE volunteer_assignment (
  volunteer_assignment_id UUID PRIMARY KEY,
  person_role_id          UUID NOT NULL REFERENCES person_role(person_role_id),
  program_id              UUID NOT NULL REFERENCES program(program_id),
  volunteer_type_code     TEXT NOT NULL REFERENCES volunteer_type(volunteer_type_code),
  valid_during            DATERANGE NOT NULL,
  CHECK (lower(valid_during) < upper(valid_during))
);
CREATE INDEX volunteer_assignment_ix ON volunteer_assignment (program_id, volunteer_type_code, valid_during);

CREATE TABLE certification_type (
  certification_code TEXT PRIMARY KEY,
  description        TEXT NOT NULL
);

CREATE TABLE volunteer_requirement (
  volunteer_requirement_id UUID PRIMARY KEY,
  volunteer_type_code      TEXT NOT NULL REFERENCES volunteer_type(volunteer_type_code),
  certification_code       TEXT NOT NULL REFERENCES certification_type(certification_code),
  valid_during             DATERANGE NOT NULL,
  requirement_level        TEXT NOT NULL DEFAULT 'REQUIRED'
);

CREATE TABLE person_certification (
  person_certification_id UUID PRIMARY KEY,
  person_id               UUID NOT NULL REFERENCES person(person_id),
  certification_code      TEXT NOT NULL REFERENCES certification_type(certification_code),
  valid_during            DATERANGE NOT NULL,
  issuer                  TEXT,
  credential_ref          TEXT,
  metadata                JSONB
);
CREATE INDEX person_cert_ix ON person_certification (person_id, certification_code, valid_during);

CREATE TABLE certification_equivalency (
  satisfies_cert_code  TEXT NOT NULL REFERENCES certification_type(certification_code),
  by_cert_code         TEXT NOT NULL REFERENCES certification_type(certification_code),
  PRIMARY KEY (satisfies_cert_code, by_cert_code),
  CHECK (satisfies_cert_code <> by_cert_code)
);

-- Seed minimal lookups
INSERT INTO role_type VALUES
('PLAYER','Player'),
('VOLUNTEER','Volunteer'),
('COACH','Coach'),
('REFEREE','Referee');

INSERT INTO enrollment_status_type VALUES
('WAITLIST','Registered but not yet eligible'),
('ACTIVE','Eligible for placement'),
('PLACED','Placed on a team (derivable)'),
('WITHDRAWN','Withdrew from program'),
('CANCELLED','Cancelled before start');

INSERT INTO volunteer_type VALUES
('HEAD_COACH','Head Coach'),
('ASST_COACH','Assistant Coach'),
('REFEREE','Referee'),
('YOUTH_REF','Youth Referee'),
('TEAM_MANAGER','Team Manager');

INSERT INTO certification_type VALUES
('SAFE_HAVEN','AYSO Safe Haven'),
('SAFE_SPORT','SafeSport'),
('COACH_8U','AYSO 8U Coach'),
('REF_REG','AYSO Regional Referee'),
('REF_INT','AYSO Intermediate Referee');

INSERT INTO certification_equivalency VALUES ('REF_REG','REF_INT');
