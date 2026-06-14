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
  2026-06-14  Enrich from teamAdminDetail: capture risk_status/risk_expires and a
              thin cert set (license level, concussion Y/N) for prior-roster people
              not in the current credentials export. These are 'unverified' windows
              (never counted as currently valid) carrying source='teamAdminDetail'.
  2026-06-14  Collect per-person identity aliases (all distinct emails/phones/
              names/dobs across seasons) + risk_status, so the compliance matcher
              can match a PM volunteer on a historical alias (HistoryIndex).
  2026-06-14  Normalize all cert dates to ISO (_iso_date) at ingestion — fixes a
              validity bug where US-format expiries (MM/DD/YYYY) string-compared
              wrong against ISO 'today' (e.g. SafeSport read as expired), and the
              inconsistent display of mixed date formats.
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


def _iso_date(val) -> Optional[str]:
    """Normalize a date to ISO YYYY-MM-DD so windows sort and compare correctly.

    Affinity exports mix ISO (2022-08-24) and US (08/22/2011) formats. Because
    _current_window compares dates as strings against an ISO 'today', a US-format
    expiry silently breaks validity (e.g. '11/08/2026' < '2026-06-14' is True by
    string order, so a cert good until Nov 2026 reads as expired). Accepts
    datetimes/Timestamps and common string formats; returns None for empty, or the
    original string unchanged if it can't be parsed.
    """
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.strftime('%Y-%m-%d')
    s = str(val).strip()
    if not s or s.lower() in ('nan', 'nat', 'none'):
        return None
    head = s.split(' ')[0].split('T')[0]
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%Y/%m/%d', '%m-%d-%Y'):
        try:
            return datetime.strptime(head, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return s


def _new_vol(sid: str) -> Dict[str, Any]:
    return {'person': {'aysoid': sid, 'name': '', 'email': '', 'dob': None,
                       'risk_status': None, 'risk_expires': None,
                       # every distinct identity value seen across seasons, so the
                       # compliance matcher can match on a HISTORICAL alias too.
                       'aliases': {'emails': [], 'phones': [], 'names': [], 'dobs': []}},
            'observed_seasons': [], 'assignments': [], 'win': {}}


def _fill_identity(v, first, last, email, dob):
    name = f"{str(first).strip()} {str(last).strip()}".strip()
    if name and not v['person']['name']:
        v['person']['name'] = name
    if email and not v['person']['email']:
        v['person']['email'] = str(email).strip()
    if dob and not v['person']['dob']:
        v['person']['dob'] = str(dob).strip()


_DET_PHONE_COLS = ('Cell Phone', 'Cellphone', 'Mobile', 'Mobile Phone', 'Primary Phone',
                   'Phone', 'Home Phone', 'Telephone')


def _digits10(phone) -> str:
    d = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    return d[-10:] if len(d) >= 10 else ''


def _detail_phone(row) -> str:
    for c in _DET_PHONE_COLS:
        if str(row.get(c, '')).strip():
            return row.get(c, '')
    return ''


def _detail_certs(row):
    """Best-effort cert facts carried by teamAdminDetail (a thinner set than the
    Admin Credentials report): a license level (no expiry) and a concussion Y/N
    flag. Returned as 'unverified' windows so they inform without ever counting as
    currently valid. Risk status is captured separately on the person."""
    out = []
    role = str(row.get('Role', '')).strip().lower()
    lic = str(row.get('Lic. Level', '')).strip()
    if lic and lic.upper() != 'N':
        if 'referee' in role or role in ('re', 'ar') or lic.isalpha():
            ck = 'referee_certification'
        elif 'coach' in role or role in ('hc', 'ac') or lic.isdigit():
            ck = 'coach_license'
        else:
            ck = None
        if ck:
            out.append((ck, {'begin': None, 'end': _iso_date(row.get('Certification Expire Date', '')),
                             'detail': lic, 'status': 'on_file', 'source': 'teamAdminDetail',
                             'unverified': True}))
    if str(row.get('Concussion Certificate  Loaded', '')).strip().upper() == 'Y':
        out.append(('concussion', {'begin': None, 'end': None, 'detail': 'loaded',
                                   'status': 'on_file', 'source': 'teamAdminDetail',
                                   'unverified': True}))
    return out


def _add_alias(person, first='', last='', email='', phone='', dob=''):
    """Accumulate every distinct email / phone / (first,last) / dob seen for a
    person, so a PlayMetrics volunteer can be matched on a *historical* identity
    value (e.g. an email they used three seasons ago), not just their current one."""
    al = person['aliases']
    e = str(email or '').strip().lower()
    if e and e not in al['emails']:
        al['emails'].append(e)
    p = _digits10(phone)
    if p and p not in al['phones']:
        al['phones'].append(p)
    pair = [str(first or '').strip(), str(last or '').strip()]
    if any(pair) and pair not in al['names']:
        al['names'].append(pair)
    d = str(dob or '').strip()[:10]
    if d and d not in al['dobs']:
        al['dobs'].append(d)


def _held(cert) -> bool:
    return bool(cert.verified or cert.completed_date or cert.detail)


def _current_window(windows: List[Dict[str, Any]], today: str) -> Dict[str, Any]:
    for w in windows:
        # 'unverified' = a prior-season teamAdminDetail value (e.g. undated license /
        # concussion Y) — informative but NOT proof of current standing, so never
        # let it count as currently valid (would falsely read as compliant).
        if w.get('unverified'):
            continue
        b, e = w.get('begin'), w.get('end')
        if ((not b) or b <= today) and ((not e) or today < e):
            return {'valid': True, 'begin': b, 'end': e, 'detail': w.get('detail'),
                    'status': w.get('status'), 'source': w.get('source')}
    last = windows[-1] if windows else {}
    return {'valid': False, 'begin': last.get('begin'), 'end': last.get('end'),
            'detail': last.get('detail'), 'status': last.get('status'),
            'source': last.get('source')}


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
            _add_alias(v['person'], r.first_name, r.last_name, r.email, r.phone, r.dob)
            if not v['person'].get('risk_status') and r.risk_status:
                v['person']['risk_status'] = r.risk_status
            if label not in v['observed_seasons']:
                v['observed_seasons'].append(label)
            for cert_key, cert in r.certifications.items():
                if not _held(cert):
                    continue
                begin = _iso_date(cert.completed_date)
                end = _iso_date(cert.expires_date)
                wkey = begin or f"undated::{cert.detail or 'held'}"
                w = v['win'].setdefault(cert_key, {}).setdefault(wkey, {
                    'begin': begin, 'end': end,
                    'detail': cert.detail, 'status': cert.status, 'observed_in': []})
                if label not in w['observed_in']:
                    w['observed_in'].append(label)
                if not w['end'] and end:
                    w['end'] = end
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
            _add_alias(v['person'], row.get('First Name', ''), row.get('Last Name', ''),
                       row.get('Email', ''), _detail_phone(row), row.get('DOB', ''))
            if label not in v['observed_seasons']:
                v['observed_seasons'].append(label)
            # Risk status + thin cert facts from teamAdminDetail. Only fill cert
            # types the authoritative Admin Credentials report didn't already give
            # (i.e. for prior-roster people not in the current credentials export).
            rstat = str(row.get('Risk Status', '')).strip()
            if rstat:
                if not v['person'].get('risk_status'):
                    v['person']['risk_status'] = rstat
                if not v['person'].get('risk_expires'):
                    v['person']['risk_expires'] = _iso_date(row.get('Risk Expire Date', ''))
            for ck, w in _detail_certs(row):
                if ck in v['win']:
                    continue
                wkey = w['end'] or f"prior::{label}::{w.get('detail') or ck}"
                v['win'].setdefault(ck, {})[wkey] = {**w, 'observed_in': [label]}
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
