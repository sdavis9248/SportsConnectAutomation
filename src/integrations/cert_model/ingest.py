"""
Ingestion: real Affinity / PlayMetrics data -> cert_model SQLite DB.

Populates the participant + certification system-of-record from the artifacts the
pipeline already produces:

  * volunteer_credentials.json (Affinity, from credential_history) -> participants,
    external identities (AYSO id + email/phone aliases), roles (from the season
    assignment timeline), credentials (from the cert windows, with verification
    provenance), and risk status.
  * volunteers_*.csv (PlayMetrics) -> resolves each current volunteer to a canonical
    participant via the persisted external identities (the matcher, now in the DB) and
    records a current-season role. New people are created + flagged for review.

Build the DB from both:  build_region58_db('region58.db', feed, volunteers_csv)

Modification History:
  2026-06-14  New — Affinity feed + PlayMetrics volunteer ingestion.
"""
import csv
import json

from integrations.cert_model import store

# Affinity/PM role label -> role_type_code. Unknown labels (Board Member, Field Prep,
# Concessions, ...) are intentionally skipped — they aren't compliance roles.
_ROLE_MAP = {
    'head coach': 'HEAD_COACH', 'hc': 'HEAD_COACH',
    'assistant coach': 'ASST_COACH', 'ac': 'ASST_COACH',
    'referee': 'REFEREE', 'youth referee': 'REFEREE', 're': 'REFEREE',
    'team manager': 'TEAM_MANAGER', 'manager': 'TEAM_MANAGER',
    'player': 'PLAYER',
}


def _roles_from(role_str):
    out = []
    for tok in str(role_str or '').split(','):
        rc = _ROLE_MAP.get(tok.strip().lower())
        if rc and rc not in out:
            out.append(rc)
    return out


def _season_window(season):
    """AYSO Membership Year 'MY2026' -> approximate validity window [Aug prior yr, Jul].
    Approximate (membership-year boundaries vary); good enough for as-of role activity."""
    s = str(season or '').strip().upper()
    if s.startswith('MY') and s[2:].isdigit():
        y = int(s[2:])
        return (f"{y - 1}-08-01", f"{y}-07-31")
    return ('2000-01-01', None)


def _add_identity(con, pid, source_system, key_kind, key, match_method=None, confidence=None):
    key = str(key or '').strip()
    if not key:
        return
    if con.execute("SELECT 1 FROM external_identity WHERE source_system=? AND key_kind=? AND source_key=?",
                   (source_system, key_kind, key)).fetchone():
        return                       # first participant to claim a key wins (avoid ambiguous fan-out)
    con.execute("INSERT INTO external_identity(external_identity_id,participant_id,source_system,source_key,"
                "key_kind,match_method,confidence,from_date) VALUES(?,?,?,?,?,?,?,?)",
                (store._uid(), pid, source_system, key, key_kind, match_method, confidence, store._today()))


def ingest_affinity_feed(con, feed_path, observed_at=None):
    """Load volunteer_credentials.json (Affinity) into the DB. Idempotent on AYSO id."""
    feed = json.load(open(feed_path, encoding='utf-8'))
    observed_at = observed_at or feed.get('generated_at') or store._today()
    n_p = n_r = n_c = 0
    for aysoid, v in (feed.get('volunteers') or {}).items():
        pid = str(aysoid).strip()
        if not pid:
            continue
        p = v.get('person') or {}
        al = p.get('aliases') or {}
        phones = al.get('phones') or []
        if not con.execute("SELECT 1 FROM participant WHERE participant_id=?", (pid,)).fetchone():
            store.add_participant(con, p.get('name') or '(unknown)', birthdate=p.get('dob'),
                                  email=p.get('email'), phone=(phones[0] if phones else None),
                                  risk_status=p.get('risk_status'), participant_id=pid,
                                  external_ref={'aysoid': aysoid})
            n_p += 1

        _add_identity(con, pid, 'sports_affinity', 'native_id', aysoid)
        for e in (al.get('emails') or []):
            _add_identity(con, pid, 'sports_affinity', 'email', e)
        for ph in phones:
            _add_identity(con, pid, 'sports_affinity', 'phone', ph)

        for a in (v.get('assignments') or []):
            frm, to = _season_window(a.get('season'))
            for rc in _roles_from(a.get('role')):
                store.upsert_role(con, pid, rc, frm, to,
                                  scope={'season': a.get('season'), 'team': a.get('team'),
                                         'age_group': a.get('play_level'), 'division': a.get('play_level')})
                n_r += 1

        for code, c in (v.get('certifications') or {}).items():
            for w in (c.get('windows') or []):
                unver = bool(w.get('unverified'))
                store.record_credential(con, pid, code, from_date=w.get('begin'), to_date=w.get('end'),
                                        detail=w.get('detail'),
                                        status='UNVERIFIED' if unver else 'ACTIVE',
                                        source=w.get('source') or 'sports_affinity',
                                        verification={'source_system': 'sports_affinity', 'method': 'export',
                                                      'observed_at': observed_at,
                                                      'source_ref': ','.join(w.get('observed_in') or []),
                                                      'confidence': 'low' if unver else 'high'})
                n_c += 1

        rs = str(p.get('risk_status') or '').strip().lower()
        if rs:
            store.record_credential(con, pid, 'risk_status', from_date=None, to_date=p.get('risk_expires'),
                                    detail=p.get('risk_status'),
                                    status='REVOKED' if rs == 'expired' else 'ACTIVE',
                                    source='sports_affinity',
                                    verification={'source_system': 'sports_affinity', 'method': 'export',
                                                  'observed_at': observed_at, 'confidence': 'high'})
            n_c += 1
    con.commit()
    return {'participants': n_p, 'roles': n_r, 'credentials': n_c}


def _first(row, *names):
    for n in names:
        if row.get(n):
            return row[n]
    return ''


def ingest_playmetrics_volunteers(con, csv_path, season='MY2026', as_of=None):
    """Resolve each current PlayMetrics volunteer to a participant (via the persisted
    Affinity identities — email then AYSO id) and record a current-season role. People
    we can't resolve are created and flagged source='playmetrics' for review."""
    as_of = as_of or store._today()
    frm, to = _season_window(season)
    matched = created = roles = 0
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            email = _first(row, 'volunteer_email', 'email', 'Email').strip().lower()
            ayso = str(_first(row, 'ayso_id', 'member_id', 'AYSO ID')).strip()
            first = _first(row, 'volunteer_first_name', 'first_name', 'First Name')
            last = _first(row, 'volunteer_last_name', 'last_name', 'Last Name')
            position = _first(row, 'volunteer_position', 'position', 'Volunteer Role', 'Role')
            division = _first(row, 'package_name', 'division', 'Division Name', 'age_group')

            pid = None
            if email:
                r = con.execute("SELECT participant_id FROM external_identity WHERE key_kind='email' AND source_key=?",
                                (email,)).fetchone()
                pid = r['participant_id'] if r else None
            if not pid and ayso:
                r = con.execute("SELECT participant_id FROM external_identity WHERE key_kind='native_id' AND source_key=?",
                                (ayso,)).fetchone()
                pid = r['participant_id'] if r else None

            if pid:
                matched += 1
            else:
                pid = store.add_participant(con, f"{first} {last}".strip() or '(unknown)',
                                            email=email or None, external_ref={'source': 'playmetrics'})
                if email:
                    _add_identity(con, pid, 'playmetrics', 'email', email, match_method='created')
                created += 1

            for rc in _roles_from(position):
                store.upsert_role(con, pid, rc, frm, to,
                                  scope={'season': season, 'division': division or None, 'source': 'playmetrics'})
                roles += 1
    con.commit()
    return {'matched': matched, 'created_unresolved': created, 'roles': roles}


def sync_from_feeds(con, feed_path, volunteers_csv=None, observed_at=None, season='MY2026'):
    """Reconcile the durable DB from the current feeds (idempotent upserts; verifications
    accrue). PlayMetrics is a pure supplier of who's serving — it never defines compliance."""
    stats = {'affinity': ingest_affinity_feed(con, feed_path, observed_at)}
    if volunteers_csv:
        stats['playmetrics'] = ingest_playmetrics_volunteers(con, volunteers_csv, season=season)
    return stats


def build_region58_db(db_path, feed_path, volunteers_csv=None, observed_at=None, season='MY2026'):
    """Open (or create) the durable region58.db and reconcile it from the feeds."""
    con = store.open_or_create(db_path)   # durable: schema+seed only if new
    stats = sync_from_feeds(con, feed_path, volunteers_csv, observed_at, season)
    return con, stats
