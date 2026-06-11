"""
Synthetic smoke test for the eTrainu <-> compliance matcher. No login, no real
data, no network. Run from the repo root:

    python test_etrainu_compliance.py

It builds a handful of fake events + resolved volunteers that exercise every
branch (youth-ref exemptions, Risk Status, insufficient coach license, untracked
roles, unmatched), runs the matcher, prints the per-volunteer next step, asserts
the logic, and writes a worklist to reports/ so you can eyeball the xlsx/csv.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
from integrations import etrainu_compliance_matcher as m  # noqa: E402


def cert(status='valid', verified=True, detail=None):
    d = {'status': status, 'verified': verified}
    if detail:
        d['detail'] = detail
    return d


EVENTS = [
    {'title': '10U Coach Course', 'course_type': '10U Coach', 'region': 'Region 58',
     'sessions': [{'date': '2026-08-15', 'day_of_week': 'Saturday',
                   'start_time': '09:00', 'end_time': '12:00', 'location': 'VNSO Memorial Park'}],
     'enroll_info': {'data_event': 'E10U', 'data_session': 'S1'},
     'contact': {'name': 'Pat Lead', 'email': 'lead@ayso58.org'}},
    {'title': '12U Coach Course', 'course_type': '12U Coach', 'region': 'Region 58',
     'sessions': [{'date': '2026-08-20', 'day_of_week': 'Thursday',
                   'start_time': '18:00', 'end_time': '21:00', 'location': 'VNSO'}],
     'enroll_info': {'data_event': 'E12U'}, 'contact': {}},
    {'title': 'Regional Referee Course', 'course_type': 'Regional Referee', 'region': 'Region 58',
     'sessions': [{'date': '2026-08-02', 'day_of_week': 'Saturday',
                   'start_time': '08:00', 'end_time': '17:00', 'location': 'Balboa Park'}],
     'enroll_info': {'data_event': 'ERR'}, 'contact': {}},
]

GENERAL = {k: cert() for k in ('safe_haven', 'fingerprinting', 'concussion', 'safesport', 'cardiac')}

RESOLVED = [
    # Youth Referee: no SafeSport/Fingerprinting at all, green risk, has grade -> COMPLIANT (exempt)
    {'volunteer_email': 'youth@x.org', 'volunteer_first_name': 'Yu', 'volunteer_last_name': 'Ref',
     'volunteer_position': 'Youth Referee', '_match_method': 'email', '_match_confidence': 'high',
     'risk_status': 'green',
     'certifications': {'safe_haven': cert(), 'concussion': cert(), 'cardiac': cert(),
                        'referee_certification': cert(detail='Regional Referee')}},
    # Referee: SafeSport expired (NOT exempt), yellow risk (ok for refs) -> one online gap
    {'volunteer_email': 'ref@x.org', 'volunteer_first_name': 'Re', 'volunteer_last_name': 'Ref',
     'volunteer_position': 'Referee', '_match_method': 'email', '_match_confidence': 'high',
     'risk_status': 'yellow',
     'certifications': {**GENERAL, 'safesport': cert('expired', True),
                        'referee_certification': cert(detail='Regional')}},
    # 12U Head Coach holding a 10U license (insufficient) + brown risk (restricts coaches)
    {'volunteer_email': 'coach@x.org', 'volunteer_first_name': 'Ha', 'volunteer_last_name': 'Coach',
     'volunteer_position': 'Head Coach', 'package_name': '12U Boys',
     '_match_method': 'email', '_match_confidence': 'high', 'risk_status': 'brown',
     'certifications': {**GENERAL, 'coach_license': cert(detail='10U')}},
    # Team Parent -> untracked, never on the chase list
    {'volunteer_email': 'parent@x.org', 'volunteer_first_name': 'Te', 'volunteer_last_name': 'Parent',
     'volunteer_position': 'Team Parent', '_match_method': 'email', '_match_confidence': 'high',
     'risk_status': 'green'},
    # Assistant Coach with no governing-system match -> verify identity, no invented gaps
    {'volunteer_email': 'unmatched@x.org', 'volunteer_first_name': 'As', 'volunteer_last_name': 'Coach',
     'volunteer_position': 'Assistant Coach', '_match_method': 'none', '_match_confidence': 'none'},
]


def main():
    rem = m.build_remediation(RESOLVED, EVENTS, today=date(2026, 6, 10))

    print("\nPer-volunteer next step:")
    for r in rem:
        print(f"  {r['last_name']:7} [{r['role']:13}] tracked={str(r.get('tracked')):5} -> {r['summary']}")

    by = {r['email']: r for r in rem}
    # Youth ref exempt from SafeSport+Fingerprinting -> compliant
    assert by['youth@x.org']['gaps'] == [] and by['youth@x.org']['summary'] == 'Compliant.'
    # Referee: only the SafeSport gap, routed to the real SafeSport portal
    rgaps = {g['cert']: g for g in by['ref@x.org']['gaps']}
    assert set(rgaps) == {'safesport'} and 'safesporttrained.org' in rgaps['safesport']['portal']['url']
    # Coach: insufficient license -> 12U course; brown risk -> admin coaching restriction
    cgaps = {g['cert']: g for g in by['coach@x.org']['gaps']}
    assert cgaps['coach_license']['next_session']['course_type'] == '12U Coach'
    assert cgaps['risk_status']['channel'] == 'admin'
    # Untracked + unmatched behave as designed
    assert by['parent@x.org']['tracked'] is False
    assert not by['unmatched@x.org']['matched'] and by['unmatched@x.org']['gaps'] == []
    print("\nAll assertions passed.")

    paths = m.write_worklist(rem, 'reports')
    print(f"Worklist written:\n  {paths['xlsx']}\n  {paths['csv']}")


if __name__ == '__main__':
    main()
