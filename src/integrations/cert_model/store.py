"""
Certification system-of-record (first concrete cut) — SQLite, stdlib only.

Implements the temporal participant + certification model from
docs/certification-architecture.md: participants hold typed ROLES over time,
roles (a "volunteer" characteristic) require CREDENTIALS over time
(required_from/to), participants hold credentials over time (valid_from/to), and
compliance is DERIVED as-of any date:

    required(participant, as_of) - held(participant, as_of) = gaps

"Youth referee" is not a role — it's a Referee who is a minor at `as_of` (from
birthdate vs. age of majority); minor status fires the SafeSport/fingerprinting
exemption. Half-open windows are (from_date, to_date) ISO strings; to_date NULL =
open. SQLite (no server) is the system of record; export JSON snapshots to the
portal. Postgres is a later port (see the architecture doc).

Worked demo:  python -m integrations.cert_model.store

Modification History:
  2026-06-14  New — runnable first cut (schema + Region 58 seed + as-of resolution).
"""
import json
import os
import sqlite3
import uuid
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
AGE_OF_MAJORITY = 18


def _uid():
    return uuid.uuid4().hex


def _today():
    return date.today().isoformat()


def build(path=':memory:', seed=True):
    """Create a fresh DB (schema + optional Region 58 seed) and return the connection."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(open(os.path.join(_HERE, 'schema_sqlite.sql'), encoding='utf-8').read())
    if seed:
        con.executescript(open(os.path.join(_HERE, 'seed_region58.sql'), encoding='utf-8').read())
    con.commit()
    return con


# ── Temporal / predicate helpers ──────────────────────────────────────────
def _is_minor(birthdate, as_of, majority=AGE_OF_MAJORITY):
    """Has this person NOT reached the age of majority as of the given date?"""
    if not birthdate:
        return False
    try:
        by, bm, bd = (int(x) for x in str(birthdate)[:10].split('-'))
        ay, am, ad = (int(x) for x in str(as_of)[:10].split('-'))
    except (ValueError, AttributeError):
        return False
    age = ay - by - ((am, ad) < (bm, bd))
    return age < majority


def _eval_predicate(pred_json, ctx):
    """Evaluate a small exemption/sufficiency predicate against ctx. Supports
    {"is_minor": true|false}. NULL/empty = always true. Unknown predicate -> False
    (never silently exempt on a predicate we don't understand)."""
    if not pred_json:
        return True
    try:
        pred = json.loads(pred_json)
    except (TypeError, ValueError):
        return False
    if 'is_minor' in pred:
        return bool(ctx.get('is_minor')) == bool(pred['is_minor'])
    return False


# ── Resolution (the point of the whole thing) ─────────────────────────────
def active_roles(con, participant_id, as_of):
    return [r['role_type_code'] for r in con.execute(
        "SELECT DISTINCT role_type_code FROM participant_role WHERE participant_id=? "
        "AND from_date<=? AND (to_date IS NULL OR ?<to_date)", (participant_id, as_of, as_of))]


def required_as_of(con, participant_id, as_of=None):
    """Set of credential_codes this participant must hold on `as_of`, given the
    roles active that date, minus any exemptions whose condition holds."""
    as_of = as_of or _today()
    p = con.execute("SELECT birthdate FROM participant WHERE participant_id=?",
                    (participant_id,)).fetchone()
    ctx = {'is_minor': _is_minor(p['birthdate'], as_of) if p else False}
    roles = set(active_roles(con, participant_id, as_of))
    if not roles:
        return set()

    req = set()
    for r in con.execute(
            "SELECT credential_code, role_type_code FROM requirement "
            "WHERE requirement_level='REQUIRED' AND from_date<=? AND (to_date IS NULL OR ?<to_date)",
            (as_of, as_of)):
        if r['role_type_code'] in roles:
            req.add(r['credential_code'])

    for e in con.execute(
            "SELECT credential_code, role_type_code, applies_when FROM requirement_exemption "
            "WHERE from_date<=? AND (to_date IS NULL OR ?<to_date)", (as_of, as_of)):
        if e['role_type_code'] in roles and _eval_predicate(e['applies_when'], ctx):
            req.discard(e['credential_code'])
    return req


def held_as_of(con, participant_id, as_of=None):
    """Set of credential_codes the participant holds on `as_of` (ACTIVE only),
    expanded by predicate-free sufficiency rules."""
    as_of = as_of or _today()
    held = {c['credential_code'] for c in con.execute(
        "SELECT credential_code FROM participant_credential WHERE participant_id=? AND status='ACTIVE' "
        "AND (from_date IS NULL OR from_date<=?) AND (to_date IS NULL OR ?<to_date)",
        (participant_id, as_of, as_of))}
    for s in con.execute("SELECT satisfies_code, by_code, predicate FROM credential_sufficiency"):
        if s['by_code'] in held and s['predicate'] is None:
            held.add(s['satisfies_code'])
    return held


def compliance_as_of(con, participant_id, as_of=None):
    as_of = as_of or _today()
    roles = active_roles(con, participant_id, as_of)
    req = required_as_of(con, participant_id, as_of)
    held = held_as_of(con, participant_id, as_of)
    gaps = sorted(req - held)
    # No active role on this date => not currently serving; "compliant" doesn't apply.
    status = 'no_active_role' if not roles else ('gaps' if gaps else 'compliant')
    return {'participant_id': participant_id, 'as_of': as_of, 'active_roles': roles,
            'required': sorted(req), 'held_relevant': sorted(req & held),
            'gaps': gaps, 'status': status, 'compliant': bool(roles) and not gaps}


# ── Inserts / ingestion ───────────────────────────────────────────────────
def add_participant(con, legal_name, birthdate=None, email=None, phone=None,
                    risk_status=None, participant_id=None, external_ref=None):
    pid = participant_id or _uid()
    con.execute("INSERT INTO participant(participant_id,legal_name,birthdate,email,phone,risk_status,external_ref)"
                " VALUES(?,?,?,?,?,?,?)",
                (pid, legal_name, birthdate, email, phone, risk_status,
                 json.dumps(external_ref) if external_ref else None))
    return pid


def add_role(con, participant_id, role_type_code, from_date, to_date=None, scope=None):
    rid = _uid()
    con.execute("INSERT INTO participant_role(participant_role_id,participant_id,role_type_code,scope,from_date,to_date)"
                " VALUES(?,?,?,?,?,?)",
                (rid, participant_id, role_type_code, json.dumps(scope) if scope else None, from_date, to_date))
    return rid


def add_credential(con, participant_id, credential_code, from_date=None, to_date=None,
                   detail=None, status='ACTIVE', source=None, verification=None):
    cid = _uid()
    con.execute("INSERT INTO participant_credential(participant_credential_id,participant_id,credential_code,"
                "from_date,to_date,detail,status,source) VALUES(?,?,?,?,?,?,?,?)",
                (cid, participant_id, credential_code, from_date, to_date, detail, status, source))
    if verification:
        v = verification
        con.execute("INSERT INTO credential_verification(credential_verification_id,participant_credential_id,"
                    "source_system,source_ref,method,verified_by,observed_at,evidence_uri,confidence,raw)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (_uid(), cid, v.get('source_system', 'manual'), v.get('source_ref'), v.get('method'),
                     v.get('verified_by'), v.get('observed_at') or _today(), v.get('evidence_uri'),
                     v.get('confidence'), json.dumps(v.get('raw')) if v.get('raw') is not None else None))
    return cid


def resolve_or_create_identity(con, source_system, key_kind, source_key,
                               legal_name='(unknown)', **participant_kwargs):
    """Identity-resolution layer: map a source key (AYSO id / email / phone) to a
    canonical participant, creating it + the alias on first sight."""
    row = con.execute("SELECT participant_id FROM external_identity "
                      "WHERE source_system=? AND key_kind=? AND source_key=?",
                      (source_system, key_kind, str(source_key))).fetchone()
    if row:
        return row['participant_id']
    pid = add_participant(con, legal_name, **participant_kwargs)
    con.execute("INSERT INTO external_identity(external_identity_id,participant_id,source_system,source_key,key_kind,from_date)"
                " VALUES(?,?,?,?,?,?)", (_uid(), pid, source_system, str(source_key), key_kind, _today()))
    return pid


def demo():
    con = build()
    today = '2026-06-14'

    # A Head Coach of a 10U team, tenured since 2015 — has everything except SafeSport
    hc = add_participant(con, 'Pat Coach', birthdate='1985-04-02', email='pat@example.com', risk_status='green')
    add_role(con, hc, 'HEAD_COACH', '2015-08-01', scope={'age_group': '10U'})
    for code, frm, to in [('safe_haven', '2024-08-10', None), ('concussion', '2024-08-10', '2026-08-10'),
                          ('cardiac', '2024-08-10', None), ('risk_status', '2024-08-10', '2026-09-02'),
                          ('fingerprinting', '2020-01-01', None), ('coach_license', '2024-08-10', None)]:
        add_credential(con, hc, code, from_date=frm, to_date=to,
                       verification={'source_system': 'sports_affinity', 'method': 'export',
                                     'observed_at': today, 'confidence': 'high'})
    con.commit()
    print("Head Coach compliance @", today, "->", compliance_as_of(con, hc, today))

    # Same role (Referee), different requirements purely from age:
    yr = add_participant(con, 'Sam Young', birthdate='2011-05-01')   # ~15 -> minor
    add_role(con, yr, 'REFEREE', '2025-08-01')
    ar = add_participant(con, 'Alex Adult', birthdate='1990-01-01')  # adult
    add_role(con, ar, 'REFEREE', '2025-08-01')
    print("Youth Referee (minor) required:", sorted(required_as_of(con, yr, today)))
    print("Adult Referee required:        ", sorted(required_as_of(con, ar, today)))

    # Temporal: same tenured coach, before SafeSport existed as a requirement (2018-09-01)
    print("Head Coach required @ 2017-01-01 (pre-SafeSport):", sorted(required_as_of(con, hc, '2017-01-01')))
    print("Head Coach required @", today, "                :", sorted(required_as_of(con, hc, today)))


if __name__ == '__main__':
    demo()
