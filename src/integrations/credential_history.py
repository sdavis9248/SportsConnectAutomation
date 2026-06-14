"""
Multi-season volunteer credential history (temporal-window model).

Aggregates Sports Affinity "Admin Credentials" exports across multiple seasons
into a single per-volunteer feed for the portal's Volunteer Lookup tab. Shaped
after the AYSO temporal data architecture (docs/ayso-architecture/): a canonical
person (keyed by AYSO ID) holds each certification over VALIDITY WINDOWS
[begin, end), rather than as season-stamped snapshots. A cert observed in one
season with a future expiry spans the seasons in between; possession on any date
is derivable from the windows, and "current" status is derived as of build time.

Built on AffinityComplianceAdapter (compliance_provider.py): the credentials
file is the cert source; the details file (optional) only adds phone. Each cert
observation carries completed_date/expires_date — the window endpoints — which we
merge across seasons into per-credential windows (a new obtain date = a renewal =
a new window; the same obtain date seen across seasons = one window observed in
multiple seasons).

Output feed (volunteer_credentials.json):
  {
    "generated_at": "...", "source": "sports_affinity",
    "seasons_observed": ["MY2026","MY2025", ...],         # order provided (newest first)
    "volunteers": {
      "<aysoid>": {
        "person": {"aysoid","name","email","dob"},
        "observed_seasons": ["MY2025","MY2024"],            # seasons this person appeared (activity timeline)
        "certifications": {
          "<cert_key>": {
            "windows": [ {"begin","end","detail","status","observed_in":[seasons]} ],  # sorted by begin
            "current": {"valid": bool, "begin","end","detail","status"}                # derived as of build
          }
        }
      }
    }
  }

NOTE: per-season volunteer_type/division (richer "assignments") require the
teamAdminDetail roster export, which report 143 does not carry. observed_seasons
is the coarse activity timeline for now; assignment enrichment is a follow-up.

Modification History:
  2026-06-14  Revise to temporal-window model (cert validity windows + derived
              current), per docs/ayso-architecture. Was season-stamped snapshots.
  2026-06-14  New — multi-season credential history aggregation.
"""
import json
import logging
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

from integrations.compliance_provider import AffinityComplianceAdapter

logger = logging.getLogger(__name__)

DEFAULT_OUT = "data/playmetrics/volunteer_credentials.json"


def _held(cert) -> bool:
    """An observation counts as 'held' (a possession fact) if verified, or it
    carries an obtain date or a level/detail. Not-held observations create no window."""
    return bool(cert.verified or cert.completed_date or cert.detail)


def _current_window(windows: List[Dict[str, Any]], today: str) -> Dict[str, Any]:
    """Derive current validity as of `today` (ISO yyyy-mm-dd; ISO strings compare
    chronologically). A null begin = undated-but-held; a null end = open-ended."""
    for w in windows:
        b, e = w.get('begin'), w.get('end')
        if ((not b) or b <= today) and ((not e) or today < e):
            return {'valid': True, 'begin': b, 'end': e,
                    'detail': w.get('detail'), 'status': w.get('status')}
    last = windows[-1] if windows else {}
    return {'valid': False, 'begin': last.get('begin'), 'end': last.get('end'),
            'detail': last.get('detail'), 'status': last.get('status')}


def build_credential_history(season_exports: List[Dict[str, str]],
                             out_path: str = DEFAULT_OUT) -> Dict[str, Any]:
    """Aggregate per-season Affinity credential exports into a temporal feed.

    Args:
        season_exports: ordered list, NEWEST FIRST, of
            {'label': 'MY2025', 'credentials': '<path.xlsx>', 'details': '<path.xlsx>'(optional)}
        out_path: where to write volunteer_credentials.json

    Ordering matters: identity fields (name/email/dob) take the first non-empty
    value seen, so put the most recent season first to prefer current info.
    Returns the assembled feed dict (also written to out_path).
    """
    seasons_observed: List[str] = []
    # working: vols[sid] = {person, observed_seasons, win[cert_key][window_key] = window}
    vols: Dict[str, Dict[str, Any]] = {}

    for se in season_exports:
        label, cred, det = se.get('label'), se.get('credentials'), se.get('details')
        if not label or not cred or not Path(cred).exists():
            logger.warning(f"Skipping season {label!r}: credentials file missing ({cred!r})")
            continue
        try:
            pkg = AffinityComplianceAdapter(cred, det, season=label).build_package()
        except Exception as e:
            logger.error(f"Failed to build package for season {label}: {e}")
            continue

        seasons_observed.append(label)
        n = 0
        for r in pkg.records:
            sid = str(r.source_id).strip()
            if not sid:
                continue
            v = vols.setdefault(sid, {
                'person': {'aysoid': sid, 'name': '', 'email': '', 'dob': None},
                'observed_seasons': [], 'win': {},
            })
            name = f"{r.first_name} {r.last_name}".strip()
            if name and not v['person']['name']:
                v['person']['name'] = name
            if r.email and not v['person']['email']:
                v['person']['email'] = r.email
            if r.dob and not v['person']['dob']:
                v['person']['dob'] = r.dob
            if label not in v['observed_seasons']:
                v['observed_seasons'].append(label)

            for cert_key, cert in r.certifications.items():
                if not _held(cert):
                    continue
                # window identity: the obtain date uniquely identifies a credential
                # instance; same date across seasons = one window, new date = a renewal.
                wkey = cert.completed_date or f"undated::{cert.detail or 'held'}"
                cw = v['win'].setdefault(cert_key, {})
                w = cw.setdefault(wkey, {
                    'begin': cert.completed_date, 'end': cert.expires_date,
                    'detail': cert.detail, 'status': cert.status, 'observed_in': [],
                })
                if label not in w['observed_in']:
                    w['observed_in'].append(label)
                # newest-first wins; backfill end/detail/status if a later (older) season has them
                if not w['end'] and cert.expires_date:
                    w['end'] = cert.expires_date
                if not w['detail'] and cert.detail:
                    w['detail'] = cert.detail
            n += 1
        logger.info(f"{label}: {n} credential records")

    today = date.today().isoformat()
    volunteers: Dict[str, Any] = {}
    for sid, v in vols.items():
        certs_out: Dict[str, Any] = {}
        for cert_key, windows_by_key in v['win'].items():
            windows = sorted(windows_by_key.values(), key=lambda w: (w['begin'] or ''))
            certs_out[cert_key] = {'windows': windows, 'current': _current_window(windows, today)}
        volunteers[sid] = {
            'person': v['person'],
            'observed_seasons': v['observed_seasons'],
            'certifications': certs_out,
        }

    feed = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'source': AffinityComplianceAdapter.source_name,
        'seasons_observed': seasons_observed,
        'volunteers': volunteers,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(feed, indent=2, default=str), encoding='utf-8')
    logger.info(f"Wrote {len(volunteers)} volunteers across {len(seasons_observed)} seasons "
                f"-> {out_path}")
    return feed
