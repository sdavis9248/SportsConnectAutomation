"""
Standalone test for the compliance provider. Run from the repo root:

    python compliance_test.py --credentials "Admin_Credentials.xlsx" \
                              --details "Admin_Details.xlsx" \
                              --volunteers data\\playmetrics\\volunteers_20260604.csv

What it does (no portal, no Affinity login needed):
  1. Builds a CompliancePackage from the two Affinity exports.
  2. Resolves every volunteer in volunteers.csv to a governing-system record.
  3. Prints a match-rate summary by method/confidence and writes JSON to --out:
       compliance_package.json   (the normalized, source-agnostic package)
       compliance_resolved.json  (each volunteer + matched certs + confidence)
       compliance_unmatched.json (volunteers with no match + unused records)

Use --overrides overrides.json  ({"volunteer@email": "AYSO_ID", ...}) to pin any
ambiguous name-only matches. Use --synthetic to run on built-in fake data first,
just to confirm the mechanics before pointing it at real files.
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
from integrations.compliance_provider import (  # noqa: E402
    AffinityComplianceAdapter, IdentityResolver, CompliancePackage)


def _read_volunteers(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def _make_synthetic(tmp):
    import pandas as pd
    cred = Path(tmp) / 'syn_credentials.xlsx'
    det = Path(tmp) / 'syn_details.xlsx'
    vol = Path(tmp) / 'syn_volunteers.csv'
    pd.DataFrame([
        {'Admin ID': '1001', 'ID Verified': 'Y', 'AYSOs Safe Haven Verified': 'Y',
         'CA Mandated Fingerprinting Verified': 'Y', 'Concussion Awareness Verified': 'Y',
         'SafeSport Verified': 'Y', 'Sudden Cardiac Arrest Verified': 'N', 'Risk Status': 'Green'},
        {'Admin ID': '1002', 'ID Verified': 'Y', 'AYSOs Safe Haven Verified': 'N',
         'CA Mandated Fingerprinting Verified': 'N', 'Concussion Awareness Verified': 'Y',
         'SafeSport Verified': 'N', 'Sudden Cardiac Arrest Verified': 'N', 'Risk Status': 'Yellow'},
    ]).to_excel(cred, index=False)
    pd.DataFrame([
        {'Admin ID': '1001', 'First Name': 'Mike', 'Last Name': 'Alpha', 'Email': 'mike@x.com', 'DOB': '1980-05-01'},
        {'Admin ID': '1002', 'First Name': 'Sara', 'Last Name': 'Beta', 'Email': 'sara@x.com', 'DOB': '1985-03-12'},
    ]).to_excel(det, index=False)
    with open(vol, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['volunteer_email', 'volunteer_first_name', 'volunteer_last_name', 'volunteer_position'])
        w.writerow(['mike@x.com', 'Mike', 'Alpha', 'Head Coach'])      # email match
        w.writerow(['', 'Sara', 'Beta', 'Referee'])                    # name match
        w.writerow(['ghost@x.com', 'Zed', 'Omega', 'Assistant Coach']) # unmatched
    return str(cred), str(det), str(vol)


def _diagnose(a):
    """Print column detection + capture counts so we can see why a key isn't matching.
    Outputs only column NAMES and counts (no PII)."""
    import pandas as pd
    from integrations.compliance_provider import AffinityComplianceAdapter as AA, _digits
    print("=" * 60)
    cred = pd.read_excel(a.credentials).fillna('')
    print("ADMIN CREDENTIALS columns:\n  ", list(cred.columns))
    if a.details:
        det = pd.read_excel(a.details).fillna('')
        print("\nADMIN DETAILS columns:\n  ", list(det.columns))
        pick = lambda cands: next((c for c in cands if c in det.columns), None)
        print("\nAdapter would use from DETAILS:")
        print("   id    ->", pick(AA.DET_ID_COLS))
        print("   first ->", pick(AA.DET_FIRST))
        print("   last  ->", pick(AA.DET_LAST))
        print("   email ->", pick(AA.DET_EMAIL))
        print("   phone ->", pick(AA.DET_PHONE), "  <-- if None, that's why phone match fails")
        print("   dob   ->", pick(AA.DET_DOB))
    pkg = AA(a.credentials, a.details, season=a.season).build_package()
    with_email = sum(1 for r in pkg.records if r.email)
    with_phone = sum(1 for r in pkg.records if _digits(r.phone))
    print(f"\nPackage: {len(pkg.records)} records | with email: {with_email} | with phone: {with_phone}")
    vols = _read_volunteers(a.volunteers)
    print(f"\nVOLUNTEERS columns:\n   {list(vols[0].keys()) if vols else '(empty)'}")
    phone_keys = ('phone', 'volunteer_mobile_number', 'volunteer_mobile', 'mobile', 'volunteer_phone')
    email_keys = ('email', 'volunteer_email')
    vphone = sum(1 for v in vols if _digits(next((v[k] for k in phone_keys if v.get(k)), '')))
    vemail = sum(1 for v in vols if next((v[k] for k in email_keys if v.get(k)), ''))
    print(f"Volunteers: {len(vols)} | with email: {vemail} | with phone (recognized cols): {vphone}")
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--credentials', help='Affinity Admin Credentials .xlsx')
    ap.add_argument('--details', help='Affinity Admin Details (All Fields) .xlsx')
    ap.add_argument('--volunteers', help='PlayMetrics volunteers_*.csv')
    ap.add_argument('--overrides', help='JSON map: volunteer email -> AYSO ID')
    ap.add_argument('--out', default='compliance_test_out')
    ap.add_argument('--season', default=None)
    ap.add_argument('--synthetic', action='store_true', help='Run on built-in fake data')
    ap.add_argument('--diagnose', action='store_true', help='Print column detection + capture counts and exit')
    a = ap.parse_args()
    if a.diagnose:
        if not (a.credentials and a.volunteers):
            ap.error("--diagnose needs --credentials and --volunteers (and ideally --details)")
        return _diagnose(a)

    if a.synthetic:
        a.credentials, a.details, a.volunteers = _make_synthetic(a.out if os.path.isdir(a.out) else '.')
        print(f"[synthetic] credentials={a.credentials}\n[synthetic] details={a.details}\n[synthetic] volunteers={a.volunteers}\n")
    missing = [n for n in ('credentials', 'volunteers') if not getattr(a, n)]
    if missing:
        ap.error("required: --" + ", --".join(missing) + " (or use --synthetic)")

    pkg = AffinityComplianceAdapter(a.credentials, a.details, season=a.season).build_package()
    overrides = json.load(open(a.overrides)) if a.overrides else None
    vols = _read_volunteers(a.volunteers)
    result = IdentityResolver(pkg, overrides=overrides).attach(vols)

    os.makedirs(a.out, exist_ok=True)
    pkg.to_json(os.path.join(a.out, 'compliance_package.json'))
    json.dump(result['resolved'], open(os.path.join(a.out, 'compliance_resolved.json'), 'w'), indent=2, default=str)
    json.dump({'unmatched_volunteers': result['unmatched_volunteers'],
               'unmatched_records': result['unmatched_records']},
              open(os.path.join(a.out, 'compliance_unmatched.json'), 'w'), indent=2, default=str)

    methods = Counter(r['_match_method'] for r in result['resolved'])
    conf = Counter(r['_match_confidence'] for r in result['resolved'])
    matched = sum(1 for r in result['resolved'] if r['_match_method'] != 'none')
    total = len(result['resolved'])
    print("=" * 56)
    print(f"Governing-system records: {len(pkg.records)}   (source={pkg.source})")
    print(f"Volunteers:               {total}")
    print(f"Matched:                  {matched}/{total} ({100*matched/total:.0f}%)" if total else "no volunteers")
    print(f"  by method:     " + ", ".join(f"{k}={v}" for k, v in methods.items()))
    print(f"  by confidence: " + ", ".join(f"{k}={v}" for k, v in conf.items()))
    print(f"Unmatched volunteers:     {len(result['unmatched_volunteers'])}")
    print(f"Unused gov records:       {len(result['unmatched_records'])}")
    print("=" * 56)
    low = [r for r in result['resolved'] if r['_match_confidence'] in ('low', 'medium')]
    if low:
        print(f"\nReview these {len(low)} lower-confidence (name) matches; add to --overrides if wrong:")
        for r in low[:25]:
            print(f"  {r.get('volunteer_first_name','')} {r.get('volunteer_last_name','')} "
                  f"<{r.get('volunteer_email','')}> -> AYSO {r.get('source_id','?')} ({r['_match_confidence']})")
    print(f"\nWrote package + resolved + unmatched JSON to: {a.out}\\")


if __name__ == '__main__':
    main()
