"""
Volunteer compliance provider — a governing-system-agnostic bridge.

Goal: surface coach/AC/referee certifications (currently from Sports Affinity) in
the board portal, structured so that swapping to a future governing system means
writing ONE new adapter and changing nothing downstream.

Layers
------
1. CompliancePackage  - normalized, source-independent schema (this file is the
   contract; portal + resolver depend only on it, never on Affinity specifics).
2. ComplianceSourceAdapter - ABC. build_package() -> CompliancePackage.
   AffinityComplianceAdapter implements it from the existing Admin Credentials +
   Admin Details exports. A new system = a new subclass.
3. IdentityResolver - ties a PlayMetrics volunteer (email/name, no AYSO ID) to a
   governing-system ComplianceRecord, since the old AYSO-ID join no longer exists.

The package serializes to JSON for the portal and is fully decoupled from how the
data was obtained (Selenium export, .mdb macro, future API, etc.).
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Iterable, Tuple

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"

# Stable certification keys. Adapters map their native columns onto THESE; the
# portal renders THESE. Adding a cert type is the only schema change ever needed.
CERT_TYPES = (
    'id_verified',        # identity verified
    'safe_haven',         # AYSO Safe Haven
    'concussion',         # concussion awareness
    'safesport',          # SafeSport
    'cardiac',            # sudden cardiac arrest
    'fingerprinting',     # CA mandated fingerprinting / LiveScan
    'background_check',   # JDP / background screening
    'coach_license',      # coaching certification/level
    'referee_certification',
)

VALID, INVALID, EXPIRED, PENDING, UNKNOWN = 'valid', 'invalid', 'expired', 'pending', 'unknown'


@dataclass
class Certification:
    type: str
    status: str = UNKNOWN          # valid | invalid | expired | pending | unknown
    verified: bool = False
    completed_date: Optional[str] = None
    expires_date: Optional[str] = None
    detail: Optional[str] = None   # level, course name, source note


@dataclass
class ComplianceRecord:
    source_id: str                 # governing-system native id (e.g. AYSO ID)
    first_name: str = ''
    last_name: str = ''
    email: str = ''
    dob: Optional[str] = None
    risk_status: Optional[str] = None         # normalized: green|yellow|red|None
    certifications: Dict[str, Certification] = field(default_factory=dict)
    roles: List[str] = field(default_factory=list)
    source: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)

    def is_valid(self, cert_type: str) -> bool:
        c = self.certifications.get(cert_type)
        return bool(c and c.verified and c.status == VALID)


@dataclass
class CompliancePackage:
    source: str
    generated_at: str
    records: List[ComplianceRecord] = field(default_factory=list)
    season: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    # ── serialization ──────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'source': self.source,
            'season': self.season,
            'generated_at': self.generated_at,
            'records': [self._rec_to_dict(r) for r in self.records],
        }

    @staticmethod
    def _rec_to_dict(r: ComplianceRecord) -> Dict[str, Any]:
        d = asdict(r)
        d['certifications'] = {k: asdict(v) for k, v in r.certifications.items()}
        return d

    def to_json(self, path: str = None, include_raw: bool = False) -> str:
        d = self.to_dict()
        if not include_raw:
            for r in d['records']:
                r.pop('raw', None)
        text = json.dumps(d, indent=2, default=str)
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text, encoding='utf-8')
        return text

    # ── indexes for resolution ─────────────────────────────────────────
    def by_email(self) -> Dict[str, ComplianceRecord]:
        return {r.email.lower().strip(): r for r in self.records if r.email}

    def by_source_id(self) -> Dict[str, ComplianceRecord]:
        return {str(r.source_id).strip(): r for r in self.records if r.source_id}

    def by_name(self) -> Dict[str, List[ComplianceRecord]]:
        idx: Dict[str, List[ComplianceRecord]] = {}
        for r in self.records:
            idx.setdefault(_name_key(r.first_name, r.last_name), []).append(r)
        return idx


# ──────────────────────────────────────────────────────────────────────────
#  Adapter contract
# ──────────────────────────────────────────────────────────────────────────
class ComplianceSourceAdapter(ABC):
    """Implement build_package() for each governing system. Nothing else changes."""
    source_name: str = 'unknown'

    @abstractmethod
    def build_package(self) -> CompliancePackage:
        ...


# ──────────────────────────────────────────────────────────────────────────
#  Sports Affinity adapter (current source)
# ──────────────────────────────────────────────────────────────────────────
class AffinityComplianceAdapter(ComplianceSourceAdapter):
    """Builds a CompliancePackage from the Affinity 'Admin Credentials' and
    'Admin Details (All Fields)' exports (the files SportsAffinityManager produces).
    The Admin ID is the join key between the two reports and is used as source_id."""
    source_name = 'sports_affinity'

    # native cert columns (Admin Credentials report) -> normalized cert key
    CRED_MAP = {
        'id_verified':    'ID Verified',
        'safe_haven':     'AYSOs Safe Haven Verified',
        'fingerprinting': 'CA Mandated Fingerprinting Verified',
        'concussion':     'Concussion Awareness Verified',
        'safesport':      'SafeSport Verified',
        'cardiac':        'Sudden Cardiac Arrest Verified',
    }
    DATE_HINT = {  # optional companion date columns, if present
        'id_verified': 'ID Verified Date',
    }
    RISK_COL = 'Risk Status'
    CRED_ID_COL = 'Admin ID'

    # identity columns in the Admin Details report (first match wins)
    DET_ID_COLS = ['Admin ID', 'AYSO ID', 'AYSOID', 'Member ID']
    DET_FIRST = ['First Name', 'FirstName', 'Firstname']
    DET_LAST = ['Last Name', 'LastName', 'Lastname']
    DET_EMAIL = ['Email', 'Email Address', 'EMail', 'Primary Email']
    DET_DOB = ['DOB', 'Birthdate', 'Date of Birth', 'Birth Date']

    def __init__(self, credentials_path: str, details_path: str = None, season: str = None):
        self.credentials_path = credentials_path
        self.details_path = details_path
        self.season = season

    def build_package(self) -> CompliancePackage:
        import pandas as pd
        cred = pd.read_excel(self.credentials_path).fillna('')
        cred[self.CRED_ID_COL] = cred[self.CRED_ID_COL].astype(str).str.strip()
        details = None
        if self.details_path:
            details = pd.read_excel(self.details_path).fillna('')
            did = self._first_col(details, self.DET_ID_COLS)
            if did:
                details[did] = details[did].astype(str).str.strip()

        det_id = self._first_col(details, self.DET_ID_COLS) if details is not None else None
        det_first = self._first_col(details, self.DET_FIRST) if details is not None else None
        det_last = self._first_col(details, self.DET_LAST) if details is not None else None
        det_email = self._first_col(details, self.DET_EMAIL) if details is not None else None
        det_dob = self._first_col(details, self.DET_DOB) if details is not None else None
        det_by_id = {}
        if details is not None and det_id:
            for _, row in details.iterrows():
                det_by_id[str(row[det_id]).strip()] = row

        records: List[ComplianceRecord] = []
        for _, crow in cred.iterrows():
            sid = str(crow.get(self.CRED_ID_COL, '')).strip()
            if not sid:
                continue
            drow = det_by_id.get(sid)
            certs: Dict[str, Certification] = {}
            for key, col in self.CRED_MAP.items():
                if col in cred.columns:
                    verified = self._truthy(crow.get(col))
                    certs[key] = Certification(
                        type=key, verified=verified,
                        status=VALID if verified else INVALID,
                        completed_date=self._date(crow.get(self.DATE_HINT.get(key))) if self.DATE_HINT.get(key) in cred.columns else None,
                    )
            rec = ComplianceRecord(
                source_id=sid,
                first_name=str(drow[det_first]).strip() if drow is not None and det_first else '',
                last_name=str(drow[det_last]).strip() if drow is not None and det_last else '',
                email=str(drow[det_email]).strip() if drow is not None and det_email else '',
                dob=self._date(drow[det_dob]) if drow is not None and det_dob else None,
                risk_status=self._risk(crow.get(self.RISK_COL)),
                certifications=certs,
                source=self.source_name,
                raw={'credentials': {k: str(v) for k, v in crow.to_dict().items()}},
            )
            records.append(rec)
        logger.info(f"Affinity adapter: built {len(records)} compliance records")
        return CompliancePackage(source=self.source_name,
                                 generated_at=datetime.now().isoformat(timespec='seconds'),
                                 records=records, season=self.season)

    # helpers
    @staticmethod
    def _first_col(df, candidates):
        if df is None:
            return None
        for c in candidates:
            if c in df.columns:
                return c
        return None

    @staticmethod
    def _truthy(v) -> bool:
        return str(v).strip().lower() in ('y', 'yes', 'true', '1', 'verified', 'green', 'complete', 'completed')

    @staticmethod
    def _risk(v) -> Optional[str]:
        s = str(v).strip().lower()
        return s or None if s in ('green', 'yellow', 'red') else (s or None)

    @staticmethod
    def _date(v) -> Optional[str]:
        if v in (None, '', 'NaT'):
            return None
        try:
            return str(v)[:10]
        except Exception:
            return None


# ──────────────────────────────────────────────────────────────────────────
#  Identity resolution: PlayMetrics volunteer  ->  ComplianceRecord
# ──────────────────────────────────────────────────────────────────────────
def _name_key(first: str, last: str) -> str:
    return f"{(last or '').strip().lower()}|{(first or '').strip().lower()}"


@dataclass
class Match:
    record: Optional[ComplianceRecord]
    method: str          # 'email' | 'source_id' | 'name' | 'name_dob' | 'override' | 'none'
    confidence: str      # 'high' | 'medium' | 'low' | 'none'


class IdentityResolver:
    """Resolve a PM volunteer (dict with at least email/first/last, optionally
    ayso_id, dob) to a ComplianceRecord. Match order: manual override > email >
    AYSO id > name(+DOB) > name. Returns the match plus a confidence so the portal
    can flag low-confidence/unmatched volunteers for human review."""

    def __init__(self, package: CompliancePackage, overrides: Dict[str, str] = None):
        self.package = package
        self._email = package.by_email()
        self._sid = package.by_source_id()
        self._name = package.by_name()
        # overrides: volunteer email (lower) -> source_id
        self.overrides = {k.lower().strip(): str(v).strip() for k, v in (overrides or {}).items()}

    def resolve(self, volunteer: Dict[str, Any]) -> Match:
        email = (volunteer.get('email') or volunteer.get('volunteer_email') or '').lower().strip()
        first = volunteer.get('first_name') or volunteer.get('volunteer_first_name') or ''
        last = volunteer.get('last_name') or volunteer.get('volunteer_last_name') or ''
        ayso = str(volunteer.get('ayso_id') or volunteer.get('member_id') or '').strip()
        dob = (volunteer.get('dob') or '')[:10]

        if email in self.overrides and self.overrides[email] in self._sid:
            return Match(self._sid[self.overrides[email]], 'override', 'high')
        if email and email in self._email:
            return Match(self._email[email], 'email', 'high')
        if ayso and ayso in self._sid:
            return Match(self._sid[ayso], 'source_id', 'high')
        cands = self._name.get(_name_key(first, last), [])
        if len(cands) == 1:
            method = 'name_dob' if (dob and cands[0].dob == dob) else 'name'
            return Match(cands[0], method, 'medium' if method == 'name_dob' else 'low')
        if len(cands) > 1 and dob:
            for c in cands:
                if c.dob == dob:
                    return Match(c, 'name_dob', 'medium')
        return Match(None, 'none', 'none')

    def attach(self, volunteers: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """Resolve a list of volunteers. Returns resolved rows (volunteer + certs +
        match metadata) and the unmatched lists in both directions for review."""
        resolved, unmatched_vols = [], []
        used_ids = set()
        for v in volunteers:
            m = self.resolve(v)
            row = dict(v)
            row['_match_method'] = m.method
            row['_match_confidence'] = m.confidence
            if m.record:
                used_ids.add(m.record.source_id)
                row['source_id'] = m.record.source_id
                row['risk_status'] = m.record.risk_status
                row['certifications'] = {k: asdict(c) for k, c in m.record.certifications.items()}
            else:
                row['certifications'] = {}
                unmatched_vols.append(v)
            resolved.append(row)
        unmatched_records = [r.source_id for r in self.package.records if r.source_id not in used_ids]
        logger.info(f"Identity resolve: {len(resolved)-len(unmatched_vols)}/{len(resolved)} volunteers matched; "
                    f"{len(unmatched_records)} governing-system records unused")
        return {'resolved': resolved,
                'unmatched_volunteers': unmatched_vols,
                'unmatched_records': unmatched_records}
