"""
Multi-season volunteer credential history.

Aggregates Sports Affinity "Admin Credentials" exports across multiple seasons
into a single per-volunteer feed for the portal's Volunteer Lookup tab. Each
volunteer (keyed by AYSO ID / Admin ID) carries a per-season snapshot of their
certifications, so credential changes over time are visible (lapses, renewals,
license upgrades, people who served in a past season but not this one).

Built on AffinityComplianceAdapter (compliance_provider.py): the credentials
file is the cert source; the details file (optional) only adds phone.

Output feed (volunteer_credentials.json):
  {
    "generated_at": "...",
    "seasons": ["MY2026", "MY2025", ...],     # in the order provided (newest first)
    "volunteers": {
      "<aysoid>": {
        "aysoid": "...", "name": "...", "email": "...", "latest_season": "MY2025",
        "history": {
          "MY2025": {"risk_status": "...", "certifications": {<key>: {...}}},
          "MY2024": {...}
        }
      }
    }
  }

Modification History:
  2026-06-14  New — multi-season credential history aggregation (compliance Deliverable B).
"""
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from integrations.compliance_provider import AffinityComplianceAdapter

logger = logging.getLogger(__name__)

DEFAULT_OUT = "data/playmetrics/volunteer_credentials.json"


def build_credential_history(season_exports: List[Dict[str, str]],
                             out_path: str = DEFAULT_OUT) -> Dict[str, Any]:
    """Aggregate per-season Affinity credential exports into a volunteer history feed.

    Args:
        season_exports: ordered list, NEWEST FIRST, of
            {'label': 'MY2025', 'credentials': '<path.xlsx>',
             'details': '<path.xlsx>'  # optional}
        out_path: where to write volunteer_credentials.json

    Returns the assembled feed dict (also written to out_path). Ordering matters:
    identity fields (name/email) take the first non-empty value seen, so put the
    most recent season first to prefer current contact info.
    """
    seasons: List[str] = []
    volunteers: Dict[str, Dict[str, Any]] = {}

    for se in season_exports:
        label = se.get('label')
        cred = se.get('credentials')
        det = se.get('details')
        if not label or not cred or not Path(cred).exists():
            logger.warning(f"Skipping season {label!r}: credentials file missing ({cred!r})")
            continue
        try:
            pkg = AffinityComplianceAdapter(cred, det, season=label).build_package()
        except Exception as e:
            logger.error(f"Failed to build package for season {label}: {e}")
            continue

        seasons.append(label)
        n = 0
        for r in pkg.records:
            sid = str(r.source_id).strip()
            if not sid:
                continue
            v = volunteers.setdefault(sid, {
                'aysoid': sid, 'name': '', 'email': '', 'latest_season': None, 'history': {},
            })
            name = f"{r.first_name} {r.last_name}".strip()
            if name and not v['name']:
                v['name'] = name
            if r.email and not v['email']:
                v['email'] = r.email
            if v['latest_season'] is None:
                v['latest_season'] = label
            v['history'][label] = {
                'risk_status': r.risk_status,
                'certifications': {k: asdict(c) for k, c in r.certifications.items()},
            }
            n += 1
        logger.info(f"{label}: {n} credential records")

    feed = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'seasons': seasons,
        'volunteers': volunteers,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(feed, indent=2, default=str), encoding='utf-8')
    logger.info(f"Wrote {len(volunteers)} volunteers across {len(seasons)} seasons -> {out_path}")
    return feed
