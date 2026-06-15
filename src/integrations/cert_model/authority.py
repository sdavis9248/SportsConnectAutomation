"""
Authority layer — the registrar asserts state the feeds don't carry, and it WINS.

This is what makes our DB the system of record rather than a mirror: actions are
re-applied every sync AFTER feed ingestion, so they take precedence over Affinity /
PlayMetrics. Actions live in a JSON file (data/cert_actions.json) — durable config,
reviewable, version-controllable (minus PII).

Action shapes (participant identified by participant_id | aysoid | email):
  {"action":"verify",  "aysoid":"12502-720126","credential":"safesport",
                        "from":"2026-01-01","to":"2027-01-01","verified_by":"registrar"}
  {"action":"exempt",  "aysoid":"...","credential":"fingerprinting","reason":"..."}
  {"action":"admit",   "aysoid":"...","role_type":"HEAD_COACH","season":"MY2026"}
  {"action":"deny",    "aysoid":"...","role_type":"REFEREE","season":"MY2026"}
  {"action":"override_identity","source_system":"playmetrics","key_kind":"email",
                        "source_key":"a@b.com","aysoid":"12502-720126"}

Modification History:
  2026-06-14  New — registrar write-paths (verify/exempt/admit/deny/override_identity).
"""
import json
import os

from integrations.cert_model import ingest, store


def _resolve_participant(con, a):
    if a.get('participant_id'):
        return a['participant_id']
    if a.get('aysoid'):
        r = con.execute("SELECT participant_id FROM external_identity WHERE key_kind='native_id' AND source_key=?",
                        (str(a['aysoid']).strip(),)).fetchone()
        if r:
            return r['participant_id']
    if a.get('email'):
        r = con.execute("SELECT participant_id FROM external_identity WHERE key_kind='email' AND source_key=?",
                        (str(a['email']).strip().lower(),)).fetchone()
        if r:
            return r['participant_id']
    return None


def apply_actions(con, actions, observed_at=None):
    """Apply registrar actions (authoritative). Returns a per-action count."""
    observed_at = observed_at or store._today()
    n = {'verify': 0, 'exempt': 0, 'admit': 0, 'deny': 0, 'override_identity': 0, 'skipped': 0}
    for a in (actions or []):
        act = str(a.get('action') or '').lower()

        if act == 'override_identity':
            pid = a.get('participant_id') or _resolve_participant(con, a)
            key = str(a.get('source_key', '')).strip()
            kind = a.get('key_kind', 'native_id')
            srcsys = a.get('source_system', 'playmetrics')
            if kind == 'email':
                key = key.lower()
            if not pid or not key:
                n['skipped'] += 1
                continue
            con.execute("DELETE FROM external_identity WHERE source_system=? AND key_kind=? AND source_key=?",
                        (srcsys, kind, key))
            con.execute("INSERT INTO external_identity(external_identity_id,participant_id,source_system,"
                        "source_key,key_kind,match_method,confidence,from_date) VALUES(?,?,?,?,?,?,?,?)",
                        (store._uid(), pid, srcsys, key, kind, 'manual_override', 'high', observed_at))
            n['override_identity'] += 1
            continue

        pid = _resolve_participant(con, a)
        if not pid:
            n['skipped'] += 1
            continue

        if act in ('verify', 'exempt'):
            detail = a.get('detail') or (f"exempt: {a.get('reason', '')}".strip() if act == 'exempt' else None)
            # verify-and-discard is enforced in store._add_verification for sensitive
            # types; we pass only provenance (evidence_kind / evidence_ref), never a doc.
            store.record_credential(con, pid, a['credential'], from_date=a.get('from'), to_date=a.get('to'),
                                    detail=detail, status='ACTIVE', source='manual',
                                    verification={'source_system': a.get('source_system', 'manual'),
                                                  'method': a.get('method') or ('exemption' if act == 'exempt' else 'document_review'),
                                                  'verified_by': a.get('verified_by', 'registrar'),
                                                  'evidence_kind': a.get('evidence_kind'),
                                                  'evidence_ref': a.get('evidence_ref'),
                                                  'observed_at': observed_at, 'confidence': 'high'})
            n[act] += 1
        elif act == 'admit':
            frm, to = ingest._season_window(a.get('season'))
            store.upsert_role(con, pid, a['role_type'], frm, to,
                              scope={'season': a.get('season'), 'source': 'manual'})
            n['admit'] += 1
        elif act == 'deny':
            frm, _ = ingest._season_window(a.get('season'))
            con.execute("DELETE FROM participant_role WHERE participant_id=? AND role_type_code=? AND from_date=?",
                        (pid, a['role_type'], frm))
            n['deny'] += 1
        else:
            n['skipped'] += 1
    con.commit()
    return n


def apply_actions_file(con, path, observed_at=None):
    if not path or not os.path.exists(path):
        return {}
    actions = json.load(open(path, encoding='utf-8'))
    if isinstance(actions, dict):
        actions = actions.get('actions', [])
    return apply_actions(con, actions, observed_at)
