"""
Multi-season volunteer credential + assignment history.

Aggregates Sports Affinity exports across seasons into a per-volunteer feed for
the portal's Volunteer Lookup tab, shaped after the AYSO temporal data
architecture (docs/ayso-architecture/): a canonical person (keyed by AYSO ID)
with a temporal **assignment** timeline and **certification** validity windows.

Two sources, with different temporal character (confirmed empirically):
- Admin Credentials report (143, via export_credential_history): rich per-cert
  verified flags + dates, but a CURRENT/dynamic view — identical across seasons.
  So certifications are modeled as validity **windows** [begin, end) reflecting
  current state (history will accrue only if we snapshot over time).
- Admin Details report (teamAdminDetail, via export_admin_details_history):
  season-tagged ROLE/TEAM rows that genuinely vary by season. So **assignments**
  are real per-season history; the cert/risk fields it also carries are current
  (redundant with 143) and not used here.

Output feed (volunteer_credentials.json):
  {
    "generated_at": "...", "source": "sports_affinity",
    "seasons_observed": ["MY2026","MY2025", ...],
    "volunteers": {
      "<aysoid>": {
        "person": {"aysoid","name","email","dob"},
        "observed_seasons": ["MY2025","MY2024", ...],        # newest first
        "assignments": [ {"season","role","team","play_level","play_type"} ],  # historical, newest first
        "certifications": {
          "<cert_key>": { "windows": [ {"begin","end","detail","status","observed_in":[...]} ],
                          "current": {"valid","begin","end","detail","status"} }   # current as of build
        }
      }
    }
  }

Modification History:
  2026-06-14  Add assignment timeline from teamAdminDetail (historical); keep
              certifications as current windows from report 143.
  2026-06-14  Temporal-window model for certifications.
  2026-06-14  New — multi-season credential history aggregation.
"""
import json
import logging
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from integrations.compliance_provider import AffinityComplianceAdapter

logger = logging.getLogger(__name__)

DEFAULT_OUT = "data/playmetrics/volunteer_credentials.json"


def _new_vol(sid: str) -> Dict[str, Any]:
    return {'person': {'aysoid': sid, 'name': '', 'email': '', 'dob': None},
            'observed_seasons': [], 'assignments': [], 'win': {}}


def _fill_identity(v, first, last, email, dob):
    name = f"{str(first).strip()} {str(last).strip()}".strip()
    if name and not v['person']['name']:
        v['person']['name'] = name
    if email and not v['person']['email']:
        v['person']['email'] = str(email).strip()
    if dob and not v['person']['dob']:
        v['person']['dob'] = str(dob).strip()


def _held(cert) -> bool:
    return bool(cert.verified or cert.completed_date or cert.detail)


def _current_window(windows: List[Dict[str, Any]], today: str) -> Dict[str, Any]:
    for w in windows:
        b, e = w.get('begin'), w.get('end')
        if ((not b) or b <= today) and ((not e) or today < e):
            return {'valid': True, 'begin': b, 'end': e,
                    'detail': w.get('detail'), 'status': w.get('status')}
    last = windows[-1] if windows else {}
    return {'valid': False, 'begin': last.get('begin'), 'end': last.get('end'),
            'detail': last.get('detail'), 'status': last.get('status')}


def build_credential_history(credential_exports: List[Dict[str, str]],
                             detail_exports: Optional[List[Dict[str, str]]] = None,
                             out_path: str = DEFAULT_OUT) -> Dict[str, Any]:
    """Build the volunteer credential + assignment history feed.

    Args:
        credential_exports: NEWEST-FIRST list of
            {'label','credentials','details'(optional)} — Admin Credentials reports.
        detail_exports: NEWEST-FIRST list of {'label','details'} — teamAdminDetail
            reports, for the per-season assignment timeline.
        out_path: where to write volunteer_credentials.json
    Returns the feed dict (also written). Order matters: identity fields take the
    first non-empty value, so pass newest first to prefer current info.
    """
    seasons_observed: List[str] = []
    vols: Dict[str, Dict[str, Any]] = {}

    # 1) Certifications (current windows) + identity from Admin Credentials
    for se in (credential_exports or []):
        label, cred, det = se.get('label'), se.get('credentials'), se.get('details')
        if not label or not cred or not Path(cred).exists():
            logger.warning(f"Skipping credentials season {label!r}: file missing ({cred!r})")
            continue
        try:
            pkg = AffinityComplianceAdapter(cred, det, season=label).build_package()
        except Exception as e:
            logger.error(f"Failed to read credentials for {label}: {e}")
            continue
        if label not in seasons_observed:
            seasons_observed.append(label)
        for r in pkg.records:
            sid = str(r.source_id).strip()
            if not sid:
                continue
            v = vols.setdefault(sid, _new_vol(sid))
            _fill_identity(v, r.first_name, r.last_name, r.email, r.dob)
            if label not in v['observed_seasons']:
                v['observed_seasons'].append(label)
            for cert_key, cert in r.certifications.items():
                if not _held(cert):
                    continue
                wkey = cert.completed_date or f"undated::{cert.detail or 'held'}"
                w = v['win'].setdefault(cert_key, {}).setdefault(wkey, {
                    'begin': cert.completed_date, 'end': cert.expires_date,
                    'detail': cert.detail, 'status': cert.status, 'observed_in': []})
                if label not in w['observed_in']:
                    w['observed_in'].append(label)
                if not w['end'] and cert.expires_date:
                    w['end'] = cert.expires_date
                if not w['detail'] and cert.detail:
                    w['detail'] = cert.detail

    # 2) Assignment timeline (historical) from teamAdminDetail
    for se in (detail_exports or []):
        label, det = se.get('label'), se.get('details')
        if not label or not det or not Path(det).exists():
            logger.warning(f"Skipping details season {label!r}: file missing ({det!r})")
            continue
        try:
            df = AffinityComplianceAdapter._read_excel_skip_banner(det).fillna('')
        except Exception as e:
            logger.error(f"Failed to read details for {label}: {e}")
            continue
        if label not in seasons_observed:
            seasons_observed.append(label)
        seen = set()
        for _, row in df.iterrows():
            sid = str(row.get('Admin ID', '')).strip()
            if not sid:
                continue
            v = vols.setdefault(sid, _new_vol(sid))
            _fill_identity(v, row.get('First Name', ''), row.get('Last Name', ''),
                           row.get('Email', ''), row.get('DOB', ''))
            if label not in v['observed_seasons']:
                v['observed_seasons'].append(label)
            role = str(row.get('Role', '')).strip()
            team = str(row.get('Team', '')).strip()
            if not role and not team:
                continue
            key = (sid, label, role, team)
            if key in seen:
                continue
            seen.add(key)
            v['assignments'].append({
                'season': label, 'role': role, 'team': team,
                'play_level': str(row.get('Play Level', '')).strip(),
                'play_type': str(row.get('Play Type', '')).strip()})

    # 3) Finalize
    today = date.today().isoformat()
    volunteers: Dict[str, Any] = {}
    for sid, v in vols.items():
        certs_out: Dict[str, Any] = {}
        for cert_key, windows_by_key in v['win'].items():
            windows = sorted(windows_by_key.values(), key=lambda w: (w['begin'] or ''))
            certs_out[cert_key] = {'windows': windows, 'current': _current_window(windows, today)}
        volunteers[sid] = {
            'person': v['person'],
            'observed_seasons': sorted(set(v['observed_seasons']), reverse=True),
            'assignments': sorted(v['assignments'], key=lambda a: a['season'], reverse=True),
            'certifications': certs_out,
        }

    feed = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'source': AffinityComplianceAdapter.source_name,
        'seasons_observed': sorted(set(seasons_observed), reverse=True),
        'volunteers': volunteers,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(feed, indent=2, default=str), encoding='utf-8')
    logger.info(f"Wrote {len(volunteers)} volunteers ({len(seasons_observed)} seasons) -> {out_path}")
    return feed
