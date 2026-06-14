-- Region 58 seed: roles, credential types, and the actual compliance policy ported
-- from integrations/etrainu_compliance_matcher.DEFAULT_REQUIRED_BY_ROLE.
--
-- requirement.from_date = when the requirement was INTRODUCED. Best-research dates
-- with their statutory/program source (registrar to give final confirmation — these
-- are editable data, not logic; the engine won't enforce a requirement before its date):
--   safe_haven      1999-01-01  AYSO Safe Haven program launched (~1999)
--   risk_status     2005-01-01  AYSO national background-check / risk-status program (approx)
--   fingerprinting  2010-01-01  AYSO CA LiveScan; reinforced statewide by CA AB 506 (eff. 2022-01-01)
--   concussion      2012-01-01  CA AB 25 youth-sports concussion protocol (eff. 2012-01-01)
--   cardiac         2017-01-01  CA AB 1639 Eric Paredes Sudden Cardiac Arrest Prevention (eff. 2017)
--   safesport       2018-09-01  US Center for SafeSport (2017 Act); AYSO adult-volunteer adoption ~2018
--   coach_license / referee_certification / player docs: foundational (pre-dates our data)

-- Roles. "Volunteer" is a CHARACTERISTIC (is_volunteer) — Head Coach / Assistant
-- Coach / Referee / Team Manager are volunteer roles; Player and Guardian are not.
-- The 4 coach/referee roles are compliance-tracked. There is NO "Youth Referee" role:
-- a youth referee is a Referee who is a minor (handled by an age-conditional exemption).
INSERT INTO role_type(role_type_code, description, is_volunteer, tracked) VALUES
 ('PLAYER','Player',0,0),
 ('GUARDIAN','Parent/Guardian',0,0),
 ('HEAD_COACH','Head Coach',1,1),
 ('ASST_COACH','Assistant Coach',1,1),
 ('REFEREE','Referee',1,1),
 ('TEAM_MANAGER','Team Manager',1,0);

INSERT INTO credential_type(credential_code, description, domain, renews) VALUES
 ('id_verified','AYSO ID Verified','VOLUNTEER',0),
 ('safe_haven','AYSO Safe Haven','VOLUNTEER',1),
 ('safesport','SafeSport Trained','VOLUNTEER',1),
 ('concussion','Concussion Awareness','VOLUNTEER',1),
 ('cardiac','Sudden Cardiac Arrest Awareness','VOLUNTEER',1),
 ('fingerprinting','CA Mandated Fingerprinting (LiveScan)','VOLUNTEER',0),
 ('risk_status','AYSO Risk Status (background check)','VOLUNTEER',1),
 ('coach_license','AYSO Coaching License','VOLUNTEER',1),
 ('referee_certification','AYSO Referee Grade','VOLUNTEER',1),
 ('birth_certificate','Proof of Age (birth certificate)','PLAYER',0),
 ('medical_release','Medical Release / Consent','PLAYER',1),
 ('photo_consent','Photo Consent','PLAYER',1);

-- Requirements attached per role. Head Coach and Assistant Coach share the coach set;
-- Referee carries the referee set (the minor carve-outs are exemptions, below).
INSERT INTO requirement(requirement_id, credential_code, role_type_code, requirement_level, from_date, to_date) VALUES
 -- Head Coach: _CORE + fingerprinting, safesport, coach_license
 ('r_hc_sh','safe_haven','HEAD_COACH','REQUIRED','2000-01-01',NULL),
 ('r_hc_co','concussion','HEAD_COACH','REQUIRED','2012-01-01',NULL),      -- verify
 ('r_hc_ca','cardiac','HEAD_COACH','REQUIRED','2017-01-01',NULL),         -- verify (CA AB 1639)
 ('r_hc_ri','risk_status','HEAD_COACH','REQUIRED','2005-01-01',NULL),     -- verify
 ('r_hc_fp','fingerprinting','HEAD_COACH','REQUIRED','2010-01-01',NULL),  -- verify (CA LiveScan)
 ('r_hc_ss','safesport','HEAD_COACH','REQUIRED','2018-09-01',NULL),       -- verify (US SafeSport adoption)
 ('r_hc_cl','coach_license','HEAD_COACH','REQUIRED','2000-01-01',NULL),
 -- Assistant Coach: same set as Head Coach
 ('r_ac_sh','safe_haven','ASST_COACH','REQUIRED','2000-01-01',NULL),
 ('r_ac_co','concussion','ASST_COACH','REQUIRED','2012-01-01',NULL),
 ('r_ac_ca','cardiac','ASST_COACH','REQUIRED','2017-01-01',NULL),
 ('r_ac_ri','risk_status','ASST_COACH','REQUIRED','2005-01-01',NULL),
 ('r_ac_fp','fingerprinting','ASST_COACH','REQUIRED','2010-01-01',NULL),
 ('r_ac_ss','safesport','ASST_COACH','REQUIRED','2018-09-01',NULL),
 ('r_ac_cl','coach_license','ASST_COACH','REQUIRED','2000-01-01',NULL),
 -- Referee: _CORE + fingerprinting, safesport, referee_certification (minors exempted below)
 ('r_re_sh','safe_haven','REFEREE','REQUIRED','2000-01-01',NULL),
 ('r_re_co','concussion','REFEREE','REQUIRED','2012-01-01',NULL),
 ('r_re_ca','cardiac','REFEREE','REQUIRED','2017-01-01',NULL),
 ('r_re_ri','risk_status','REFEREE','REQUIRED','2005-01-01',NULL),
 ('r_re_fp','fingerprinting','REFEREE','REQUIRED','2010-01-01',NULL),
 ('r_re_ss','safesport','REFEREE','REQUIRED','2018-09-01',NULL),
 ('r_re_rc','referee_certification','REFEREE','REQUIRED','2000-01-01',NULL),
 -- Players (demo of the same engine for documents)
 ('r_pl_bc','birth_certificate','PLAYER','REQUIRED','2000-01-01',NULL),
 ('r_pl_mr','medical_release','PLAYER','REQUIRED','2000-01-01',NULL);

-- A Referee who is a MINOR (youth referee) is exempt from SafeSport and Fingerprinting.
-- applies_when {"is_minor":true} is evaluated by the engine from birthdate vs as_of.
INSERT INTO requirement_exemption(requirement_exemption_id, credential_code, role_type_code, applies_when, reason, from_date, to_date) VALUES
 ('x_yr_ss','safesport','REFEREE','{"is_minor":true}','Youth (minor) referees exempt from SafeSport','2018-09-01',NULL),
 ('x_yr_fp','fingerprinting','REFEREE','{"is_minor":true}','Youth (minor) referees exempt from LiveScan','2010-01-01',NULL);

-- Sufficiency / equivalency. Coach license & referee grade are age/grade-laddered
-- (a 12U license covers 10U...); the ladder predicate is evaluated by the app layer
-- against the role scope. Predicate NULL would mean "always satisfies".
INSERT INTO credential_sufficiency(satisfies_code, by_code, predicate) VALUES
 ('coach_license','coach_license','{"min_age_covered":"$scope.age_group"}'),
 ('referee_certification','referee_certification','{"min_grade":"$scope.grade"}');
