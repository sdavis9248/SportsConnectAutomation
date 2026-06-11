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
    phone: str = ''                # normalized later to last 10 digits for matching
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

    def by_phone(self) -> Dict[str, List[ComplianceRecord]]:
        idx: Dict[str, List[ComplianceRecord]] = {}
        for r in self.records:
            p = _digits(r.phone)
            if p:
                idx.setdefault(p, []).append(r)
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

    # cert columns in the Admin Credentials report: verified flag (+ optional date / expiry)
    CRED_CERTS = {
        'id_verified':    {'verified': 'ID Verified', 'date': 'ID Verified Date'},
        'safe_haven':     {'verified': 'AYSOs Safe Haven Verified', 'date': 'AYSOs Safe Haven Verified Date', 'expire': 'AYSOs Safe Haven Expire Date'},
        'fingerprinting': {'verified': 'CA Mandated Fingerprinting Verified', 'date': 'CA Mandated Fingerprinting Verified Date', 'expire': 'CA Mandated Fingerprinting Expire Date'},
        'concussion':     {'verified': 'Concussion Awareness Verified', 'date': 'Concussion Awareness Verified Date', 'expire': 'Concussion Awareness Expire Date'},
        'safesport':      {'verified': 'SafeSport Verified', 'date': 'SafeSport Verified Date', 'expire': 'SafeSport Expire Date'},
        'cardiac':        {'verified': 'Sudden Cardiac Arrest Verified', 'date': 'Sudden Cardiac Arrest Verified Date', 'expire': 'Sudden Cardiac Arrest Expire Date'},
    }
    # level/grade certs: present (non-empty) == held; carries the level as detail
    CRED_LEVELS = {
        'coach_license':          {'level': 'Coaching License Level', 'date': 'Coaching License\nObtained'},
        'referee_certification':  {'level': 'Referee Grade', 'date': 'Referee Grade Obtained', 'expire': 'Referee Grade Expire'},
    }
    RISK_COL = 'Risk Status'
    CRED_ID_COL = 'Admin ID'
    # identity columns present in the Credentials report (authoritative, all admins)
    CRED_FIRST, CRED_LAST, CRED_EMAIL, CRED_DOB = 'First Name', 'Last Name', 'Email', 'DOB'

    # identity columns in the Admin Details report (first match wins)
    DET_ID_COLS = ['Admin ID', 'AYSO ID', 'AYSOID', 'Member ID']
    DET_FIRST = ['First Name', 'FirstName', 'Firstname']
    DET_LAST = ['Last Name', 'LastName', 'Lastname']
    DET_EMAIL = ['Email', 'Email Address', 'EMail', 'Primary Email']
    DET_PHONE = ['Cell Phone', 'Cellphone', 'Mobile', 'Mobile Phone', 'Primary Phone',
                 'Phone', 'Home Phone', 'Telephone']
    DET_DOB = ['DOB', 'Birthdate', 'Date of Birth', 'Birth Date']

    def __init__(self, credentials_path: str, details_path: str = None, season: str = None):
        self.credentials_path = credentials_path
        self.details_path = details_path
        self.season = season

    def build_package(self) -> CompliancePackage:
        import pandas as pd
        cred = self._read_excel_skip_banner(self.credentials_path).fillna('')
        cred[self.CRED_ID_COL] = cred[self.CRED_ID_COL].astype(str).str.strip()
        details = None
        if self.details_path:
            details = self._read_excel_skip_banner(self.details_path).fillna('')
            did = self._first_col(details, self.DET_ID_COLS)
            if did:
                details[did] = details[did].astype(str).str.strip()

        det_id = self._first_col(details, self.DET_ID_COLS) if details is not None else None
        det_phone = self._first_col(details, self.DET_PHONE) if details is not None else None
        phone_by_id = {}
        if details is not None and det_id and det_phone:
            for _, row in details.iterrows():
                ph = str(row[det_phone]).strip()
                if ph:
                    phone_by_id.setdefault(str(row[det_id]).strip(), ph)

        records: List[ComplianceRecord] = []
        for _, crow in cred.iterrows():
            sid = str(crow.get(self.CRED_ID_COL, '')).strip()
            if not sid:
                continue
            certs: Dict[str, Certification] = {}
            for key, cols in self.CRED_CERTS.items():
                vcol = cols.get('verified')
                if vcol not in cred.columns:
                    continue
                verified = self._truthy(crow.get(vcol))
                expire = self._date(crow.get(cols.get('expire'))) if cols.get('expire') in cred.columns else None
                status = self._status(verified, expire)
                certs[key] = Certification(
                    type=key, verified=verified, status=status,
                    completed_date=self._date(crow.get(cols.get('date'))) if cols.get('date') in cred.columns else None,
                    expires_date=expire)
            for key, cols in self.CRED_LEVELS.items():
                lcol = cols.get('level')
                if lcol not in cred.columns:
                    continue
                level = str(crow.get(lcol, '')).strip()
                held = bool(level) and level.lower() not in ('none', 'n/a', '0')
                expire = self._date(crow.get(cols.get('expire'))) if cols.get('expire') in cred.columns else None
                certs[key] = Certification(
                    type=key, verified=held, status=self._status(held, expire),
                    completed_date=self._date(crow.get(cols.get('date'))) if cols.get('date') in cred.columns else None,
                    expires_date=expire, detail=level or None)
            rec = ComplianceRecord(
                source_id=sid,
                first_name=str(crow.get(self.CRED_FIRST, '')).strip(),
                last_name=str(crow.get(self.CRED_LAST, '')).strip(),
                email=str(crow.get(self.CRED_EMAIL, '')).strip(),
                phone=phone_by_id.get(sid, ''),     # phone only lives in the details/roster export
                dob=self._date(crow.get(self.CRED_DOB)),
                risk_status=self._risk(crow.get(self.RISK_COL)),
                certifications=certs,
                source=self.source_name,
                raw={'credentials': {k: str(v) for k, v in crow.to_dict().items()}},
            )
            records.append(rec)
        logger.info(f"Affinity adapter: built {len(records)} compliance records "
                    f"({sum(1 for r in records if r.phone)} with phone)")
        return CompliancePackage(source=self.source_name,
                                 generated_at=datetime.now().isoformat(timespec='seconds'),
                                 records=records, season=self.season)

    # helpers
    @staticmethod
    def _read_excel_skip_banner(path):
        """Read a Sports Affinity export, tolerating a title-banner row.

        Some exports (e.g. teamAdminDetail 'Administrator Information Report')
        put a merged title in row 0, so a default read makes the title the header
        and the rest 'Unnamed: N'. Detect that and re-read using the real header
        row (the first row carrying known column names). A clean export is read
        normally — this is a no-op for it."""
        import pandas as pd
        df = pd.read_excel(path).fillna('')
        cols = [str(c) for c in df.columns]
        unnamed = sum(1 for c in cols if c.startswith('Unnamed:'))
        looks_bannered = (unnamed >= max(2, len(cols) // 2)
                          or any('information report' in c.lower() for c in cols))
        if not looks_bannered:
            return df
        # Find the real header row by scanning the first several rows for known keys.
        keys = {'admin id', 'first name', 'last name', 'email', 'dob', 'phone',
                'role', 'risk status', 'season'}
        raw = pd.read_excel(path, header=None)
        for i in range(min(10, len(raw))):
            vals = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
            if sum(1 for v in vals if v in keys) >= 2:
                logger.info(f"Detected banner row in {path}; using row {i} as header.")
                return pd.read_excel(path, header=i).fillna('')
        logger.warning(f"{path} looks bannered but no header row matched known keys.")
        return df

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
    def _status(verified: bool, expire_date: Optional[str]) -> str:
        if not verified:
            return INVALID
        if expire_date:
            try:
                if datetime.fromisoformat(expire_date) < datetime.now():
                    return EXPIRED
            except Exception:
                pass
        return VALID

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


def _digits(phone: str) -> str:
    """Last 10 digits of a phone number, for matching across formats/+1 prefixes."""
    d = re.sub(r'\D', '', str(phone or ''))
    return d[-10:] if len(d) >= 10 else ''


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
        self._phone = package.by_phone()
        # overrides: volunteer email (lower) -> source_id
        self.overrides = {k.lower().strip(): str(v).strip() for k, v in (overrides or {}).items()}

    def resolve(self, volunteer: Dict[str, Any]) -> Match:
        email = (volunteer.get('email') or volunteer.get('volunteer_email') or '').lower().strip()
        first = volunteer.get('first_name') or volunteer.get('volunteer_first_name') or ''
        last = volunteer.get('last_name') or volunteer.get('volunteer_last_name') or ''
        ayso = str(volunteer.get('ayso_id') or volunteer.get('member_id') or '').strip()
        phone = _digits(volunteer.get('phone') or volunteer.get('volunteer_mobile_number')
                        or volunteer.get('volunteer_mobile') or volunteer.get('mobile')
                        or volunteer.get('volunteer_phone') or '')
        dob = (volunteer.get('dob') or '')[:10]

        if email in self.overrides and self.overrides[email] in self._sid:
            return Match(self._sid[self.overrides[email]], 'override', 'high')
        if email and email in self._email:
            return Match(self._email[email], 'email', 'high')
        if ayso and ayso in self._sid:
            return Match(self._sid[ayso], 'source_id', 'high')
        # phone: only when it maps to exactly one governing-system record (shared
        # family numbers map to several -> skip to avoid a false tie).
        if phone and len(self._phone.get(phone, [])) == 1:
            return Match(self._phone[phone][0], 'phone', 'high')
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


def build_portal_payload(package: CompliancePackage, resolved: Dict[str, Any],
                         season: str = None) -> Dict[str, Any]:
    """Shape the resolver output into the portal's compliance.json. One entry per
    volunteer row (a person can appear once per role/division), each carrying the
    division and position so the portal can filter by Director, plus a per-division
    rollup the dashboard can show at a glance."""
    vols, summary = [], {}
    for r in resolved.get('resolved', []):
        div = r.get('package_name') or r.get('Division Name') or ''
        pos = r.get('volunteer_position') or r.get('Volunteer Role') or ''
        matched = r.get('_match_method') != 'none'
        certs = r.get('certifications') or {}
        entry = {
            'email': (r.get('volunteer_email') or r.get('email') or '').strip(),
            'first_name': r.get('volunteer_first_name') or r.get('first_name') or '',
            'last_name': r.get('volunteer_last_name') or r.get('last_name') or '',
            'division': div,
            'position': pos,
            'matched': matched,
            'match_method': r.get('_match_method'),
            'match_confidence': r.get('_match_confidence'),
            'source_id': r.get('source_id', ''),
            'risk_status': r.get('risk_status'),
            'certifications': {k: {'status': c.get('status'), 'verified': c.get('verified'),
                                   'expires_date': c.get('expires_date'), 'detail': c.get('detail')}
                               for k, c in certs.items()},
        }
        vols.append(entry)
        s = summary.setdefault(div, {'volunteers': 0, 'matched': 0, 'unmatched': 0,
                                     'expired': 0, 'no_safesport': 0})
        s['volunteers'] += 1
        s['matched' if matched else 'unmatched'] += 1
        ss = certs.get('safesport', {})
        if ss.get('status') == 'expired':
            s['expired'] += 1
        if not (ss.get('verified') and ss.get('status') == 'valid'):
            s['no_safesport'] += 1
    return {
        'schema_version': SCHEMA_VERSION,
        'source': package.source,
        'season': season or package.season,
        'generated_at': package.generated_at,
        'cert_types': list(CERT_TYPES),
        'volunteers': vols,
        'summary_by_division': summary,
    }
