"""
Exporter — cert_model DB -> the portal's compliance.json (drop-in schema).

This is what FLIPS the producer: the portal's Compliance + division views are now
derived from our system-of-record (configured requirements + reconciled feeds +
registrar authority), not from the old ad-hoc matcher. Emits the exact schema the
portal already consumes (group_compliance_volunteers / get_compliance); the portal
still joins eTrainu next_steps itself from compliance_next_steps.json.

Modification History:
  2026-06-14  New — DB-derived compliance.json.
"""
import json

from integrations.cert_model import store

# cert columns the portal renders (order matters for the table)
CERT_TYPES = ('id_verified', 'safe_haven', 'concussion', 'safesport', 'cardiac',
              'fingerprinting', 'coach_license', 'referee_certification')

_ROLE_LABEL = {'HEAD_COACH': 'Head Coach', 'ASST_COACH': 'Assistant Coach',
               'REFEREE': 'Referee', 'TEAM_MANAGER': 'Team Manager', 'PLAYER': 'Player'}


def _certifications(con, pid, held, as_of):
    """Per-cert-type status block in the portal's shape. held = currently-valid set."""
    out = {}
    for ct in CERT_TYPES:
        row = con.execute(
            "SELECT detail, to_date, status FROM participant_credential "
            "WHERE participant_id=? AND credential_code=? AND status IN ('ACTIVE','UNVERIFIED') "
            "ORDER BY IFNULL(to_date,'9999-12-31') DESC LIMIT 1", (pid, ct)).fetchone()
        if ct in held:
            out[ct] = {'status': 'valid', 'verified': True,
                       'expires_date': row['to_date'] if row else None,
                       'detail': row['detail'] if row else None}
        elif row:                      # on file but not currently valid (expired/unverified)
            out[ct] = {'status': 'expired', 'verified': False,
                       'expires_date': row['to_date'], 'detail': row['detail']}
        # else: missing -> omit (portal renders a dash)
    return out


def export_compliance_payload(con, as_of=None, season='MY2026'):
    as_of = as_of or store._today()
    serving = [r['participant_id'] for r in con.execute(
        "SELECT DISTINCT participant_id FROM participant_role "
        "WHERE from_date<=? AND (to_date IS NULL OR ?<to_date)", (as_of, as_of))]

    vols, summary = [], {}
    for pid in serving:
        p = con.execute("SELECT legal_name, email, risk_status FROM participant WHERE participant_id=?",
                        (pid,)).fetchone()
        first, _, last = (p['legal_name'] or '').partition(' ')
        held = store.held_as_of(con, pid, as_of)
        certs = _certifications(con, pid, held, as_of)

        roles = con.execute("SELECT role_type_code, scope FROM participant_role WHERE participant_id=? "
                            "AND from_date<=? AND (to_date IS NULL OR ?<to_date)", (pid, as_of, as_of))
        seen = set()
        for r in roles:
            scope = json.loads(r['scope']) if r['scope'] else {}
            division = scope.get('division') or scope.get('age_group') or 'Unassigned'
            position = _ROLE_LABEL.get(r['role_type_code'], r['role_type_code'])
            if (position, division) in seen:
                continue
            seen.add((position, division))
            vols.append({
                'email': p['email'] or '', 'first_name': first.strip(), 'last_name': last.strip(),
                'division': division, 'position': position,
                'matched': True, 'match_method': 'system_of_record', 'match_confidence': 'high',
                'source_id': pid, 'risk_status': p['risk_status'], 'certifications': certs,
            })
            s = summary.setdefault(division, {'volunteers': 0, 'matched': 0, 'unmatched': 0,
                                              'expired': 0, 'no_safesport': 0})
            s['volunteers'] += 1
            s['matched'] += 1
            ss = certs.get('safesport', {})
            if ss.get('status') == 'expired':
                s['expired'] += 1
            if not (ss.get('verified') and ss.get('status') == 'valid'):
                s['no_safesport'] += 1

    return {'schema_version': '1.0', 'source': 'cert_model', 'season': season,
            'generated_at': store._today(), 'cert_types': list(CERT_TYPES),
            'volunteers': vols, 'summary_by_division': summary}


def write_compliance_json(con, out_path, as_of=None, season='MY2026'):
    payload = export_compliance_payload(con, as_of, season)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, default=str)
    return payload
