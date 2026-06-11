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


def _explain_unmatched(a):
    """Cross-check the unmatched volunteers against the governing-system package
    to tell near-misses (same person under a variant name/email -> pin via
    --overrides) apart from truly-absent volunteers (not in AYSO yet -> the real
    chase list). Reads the JSON the real build already wrote to --out."""
    import difflib
    pkg_path = os.path.join(a.out, 'compliance_package.json')
    unm_path = os.path.join(a.out, 'compliance_unmatched.json')
    if not (os.path.exists(pkg_path) and os.path.exists(unm_path)):
        print(f"Need compliance_package.json and compliance_unmatched.json in '{a.out}'.")
        print("Run the real build first (same command without --diagnose/--explain-unmatched).")
        return

    def norm(s):
        return ''.join(ch for ch in str(s or '').lower() if ch.isalnum() or ch == ' ').strip()
    def fullname(f, l):
        return (norm(f) + ' ' + norm(l)).strip()
    def localpart(e):
        return str(e or '').lower().split('@')[0].strip()

    recs = json.load(open(pkg_path, encoding='utf-8')).get('records', [])
    gov = [{
        'name': fullname(r.get('first_name', ''), r.get('last_name', '')),
        'first': norm(r.get('first_name', '')), 'last': norm(r.get('last_name', '')),
        'email_lp': localpart(r.get('email', '')), 'dob': (r.get('dob') or '')[:10],
        'ayso': r.get('source_id', ''),
        'raw_name': f"{r.get('first_name','')} {r.get('last_name','')}".strip(),
        'raw_email': r.get('email', ''),
    } for r in recs]
    gov_lps = {g['email_lp'] for g in gov if g['email_lp']}

    unm = json.load(open(unm_path, encoding='utf-8')).get('unmatched_volunteers', [])

    def tracked(pos):
        p = str(pos or '').lower()
        return ('coach' in p) or ('referee' in p) or (p.strip() == 'ref')

    rows = []
    for v in unm:
        vf = v.get('volunteer_first_name', '') or v.get('first_name', '')
        vl = v.get('volunteer_last_name', '') or v.get('last_name', '')
        ve = v.get('volunteer_email', '') or v.get('email', '')
        vpos = v.get('volunteer_position', '') or v.get('position', '')
        vname, vlast, vfirst, vlp = fullname(vf, vl), norm(vl), norm(vf), localpart(ve)
        vdob = (v.get('dob') or '')[:10]

        best, best_score = None, 0.0
        for g in gov:
            s = difflib.SequenceMatcher(None, vname, g['name']).ratio()
            if s > best_score:
                best_score, best = s, g
        last_exact = bool(best) and bool(vlast) and vlast == best['last']
        first_init = bool(best) and bool(vfirst) and best['first'][:1] == vfirst[:1]
        email_hit = bool(vlp) and vlp in gov_lps
        dob_hit = bool(best) and bool(vdob) and best['dob'] == vdob

        if email_hit or best_score >= 0.88 or (last_exact and first_init):
            verdict = 'near-miss'
        elif last_exact and best_score >= 0.60:
            verdict = 'maybe'
        else:
            verdict = 'absent'

        rows.append({
            'volunteer': f"{vf} {vl}".strip(), 'email': ve, 'position': vpos,
            'tracked': 'Y' if tracked(vpos) else '',
            'best_gov': best['raw_name'] if best else '', 'best_ayso': best['ayso'] if best else '',
            'best_gov_email': best['raw_email'] if best else '', 'score': round(best_score, 2),
            'last_exact': 'Y' if last_exact else '', 'email_hit': 'Y' if email_hit else '',
            'dob_match': 'Y' if dob_hit else '', 'verdict': verdict,
        })

    order = {'near-miss': 0, 'maybe': 1, 'absent': 2}
    rows.sort(key=lambda r: (order[r['verdict']], -r['score']))

    vc = Counter(r['verdict'] for r in rows)
    vct = Counter(r['verdict'] for r in rows if r['tracked'])
    ntracked = sum(1 for r in rows if r['tracked'])
    print("=" * 64)
    print(f"Unmatched volunteers cross-checked: {len(rows)}  (tracked coach/ref: {ntracked})")
    print(f"  near-miss (likely in AYSO; pin via --overrides): {vc['near-miss']:>3}  [tracked {vct['near-miss']}]")
    print(f"  maybe     (same last name; eyeball):             {vc['maybe']:>3}  [tracked {vct['maybe']}]")
    print(f"  absent    (no plausible gov record -> chase):    {vc['absent']:>3}  [tracked {vct['absent']}]")
    print("=" * 64)
    show = [r for r in rows if r['verdict'] in ('near-miss', 'maybe')]
    if show:
        print("Review (pin good ones into overrides.json as {\"email\": \"AYSO-ID\"}):")
        for r in show:
            flags = ('LASTNAME ' if r['last_exact'] else '') + ('EMAIL ' if r['email_hit'] else '')
            print(f"  [{r['verdict']:9}] {r['volunteer']:24.24} <{r['email']}>")
            print(f"      ~ {r['best_gov']} (AYSO {r['best_ayso']}, score {r['score']}) {flags}".rstrip())
    out_csv = os.path.join(a.out, 'compliance_unmatched_explained.csv')
    cols = ['volunteer', 'email', 'position', 'tracked', 'best_gov', 'best_ayso',
            'best_gov_email', 'score', 'last_exact', 'email_hit', 'dob_match', 'verdict']
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {out_csv} ({len(rows)} rows)")


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
    ap.add_argument('--explain-unmatched', action='store_true',
                    help='Cross-check unmatched volunteers vs gov records (reads JSON from --out) and exit')
    a = ap.parse_args()
    if a.explain_unmatched:
        return _explain_unmatched(a)
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
