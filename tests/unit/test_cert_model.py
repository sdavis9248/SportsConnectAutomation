"""Tests for the certification system-of-record (integrations.cert_model.store).

Proves the three things the model is for: requirements attach to roles, they are
temporal (not enforced before their introduced date), and "youth referee" is just
a Referee who is a minor (age-derived exemption).
"""
from integrations.cert_model import store

TODAY = '2026-06-14'


def _head_coach(con, birthdate='1985-04-02'):
    pid = store.add_participant(con, 'Pat Coach', birthdate=birthdate)
    store.add_role(con, pid, 'HEAD_COACH', '2024-08-01', scope={'age_group': '10U'})
    return pid


def test_coach_requires_full_set_incl_safesport():
    con = store.build()
    req = store.required_as_of(con, _head_coach(con), TODAY)
    assert req == {'safe_haven', 'concussion', 'cardiac', 'risk_status',
                   'fingerprinting', 'safesport', 'coach_license'}


def test_minor_referee_is_exempt_adult_is_not():
    con = store.build()
    minor = store.add_participant(con, 'Sam Young', birthdate='2011-05-01')  # ~15 at TODAY
    store.add_role(con, minor, 'REFEREE', '2025-08-01')
    adult = store.add_participant(con, 'Alex Adult', birthdate='1990-01-01')
    store.add_role(con, adult, 'REFEREE', '2025-08-01')

    minor_req = store.required_as_of(con, minor, TODAY)
    adult_req = store.required_as_of(con, adult, TODAY)
    # Youth (minor) referee: no SafeSport, no Fingerprinting
    assert 'safesport' not in minor_req and 'fingerprinting' not in minor_req
    assert 'referee_certification' in minor_req and 'safe_haven' in minor_req
    # Adult referee: both required
    assert 'safesport' in adult_req and 'fingerprinting' in adult_req


def test_requirements_are_temporal():
    con = store.build()
    # tenured since 2015 so the role is active at BOTH dates — isolates requirement timing
    pid = store.add_participant(con, 'Tenured Coach', birthdate='1980-01-01')
    store.add_role(con, pid, 'HEAD_COACH', '2015-08-01')
    early = store.required_as_of(con, pid, '2017-01-01')
    assert 'safesport' not in early          # SafeSport not introduced until 2018-09-01
    assert 'safe_haven' in early             # but long-standing requirements still apply
    assert 'safesport' in store.required_as_of(con, pid, TODAY)


def test_gaps_and_compliant_flip():
    con = store.build()
    pid = _head_coach(con)
    for c in ('safe_haven', 'concussion', 'cardiac', 'risk_status', 'fingerprinting', 'coach_license'):
        store.add_credential(con, pid, c, from_date='2024-08-10')
    comp = store.compliance_as_of(con, pid, TODAY)
    assert comp['gaps'] == ['safesport'] and comp['compliant'] is False
    store.add_credential(con, pid, 'safesport', from_date='2024-08-10')
    assert store.compliance_as_of(con, pid, TODAY)['compliant'] is True


def test_expired_credential_is_not_held():
    con = store.build()
    pid = _head_coach(con)
    store.add_credential(con, pid, 'safesport', from_date='2020-01-01', to_date='2024-01-01')
    assert 'safesport' in store.compliance_as_of(con, pid, TODAY)['gaps']


def test_unverified_prior_credential_does_not_count():
    con = store.build()
    pid = _head_coach(con)
    store.add_credential(con, pid, 'coach_license', from_date='2022-08-01',
                         status='UNVERIFIED', source='teamAdminDetail')
    assert 'coach_license' in store.compliance_as_of(con, pid, TODAY)['gaps']


def test_identity_resolution_is_idempotent():
    con = store.build()
    a = store.resolve_or_create_identity(con, 'sports_affinity', 'native_id', '12502-720126',
                                         legal_name='Sheldon Costin')
    b = store.resolve_or_create_identity(con, 'sports_affinity', 'native_id', '12502-720126')
    assert a == b
    assert con.execute("SELECT COUNT(*) FROM participant").fetchone()[0] == 1


def test_no_active_role_is_not_compliant():
    con = store.build()
    pid = store.add_participant(con, 'Past Coach', birthdate='1980-01-01')
    store.add_role(con, pid, 'HEAD_COACH', '2022-08-01', '2023-07-31')   # ended
    comp = store.compliance_as_of(con, pid, TODAY)
    assert comp['status'] == 'no_active_role' and comp['compliant'] is False


def test_ingest_affinity_feed(tmp_path):
    import json
    from integrations.cert_model import ingest
    feed = {'generated_at': '2026-06-14T00:00:00', 'volunteers': {
        '111-1': {'person': {'aysoid': '111-1', 'name': 'Casey Coach', 'dob': '1980-01-01',
                             'email': 'casey@x.com', 'risk_status': 'green', 'risk_expires': '2027-01-01',
                             'aliases': {'emails': ['casey@x.com'], 'phones': ['5551234567'],
                                         'names': [], 'dobs': []}},
                  'assignments': [{'season': 'MY2026', 'role': 'Head Coach', 'team': 'A', 'play_level': '10U'}],
                  'certifications': {
                      'safe_haven': {'windows': [{'begin': '2025-08-01', 'end': None}], 'current': {}},
                      'coach_license': {'windows': [{'begin': None, 'end': None, 'detail': '10',
                                                     'unverified': True, 'source': 'teamAdminDetail'}], 'current': {}},
                  }}}}
    fp = tmp_path / 'feed.json'
    fp.write_text(json.dumps(feed))
    con = store.build()
    stats = ingest.ingest_affinity_feed(con, str(fp))
    assert stats['participants'] == 1 and stats['roles'] == 1

    comp = store.compliance_as_of(con, '111-1', TODAY)
    assert comp['status'] == 'gaps'
    assert 'safe_haven' not in comp['gaps']     # ACTIVE window -> held
    assert 'coach_license' in comp['gaps']      # UNVERIFIED -> not held
    assert 'risk_status' not in comp['gaps']    # green + future expiry -> held
    # identity (email alias) persisted and resolvable
    row = con.execute("SELECT participant_id FROM external_identity WHERE key_kind='email' AND source_key='casey@x.com'").fetchone()
    assert row['participant_id'] == '111-1'


def test_ingest_playmetrics_resolves_by_email(tmp_path):
    from integrations.cert_model import ingest
    con = store.build()
    store.add_participant(con, 'Casey Coach', participant_id='111-1', email='casey@x.com')
    ingest._add_identity(con, '111-1', 'sports_affinity', 'email', 'casey@x.com')
    con.commit()
    csvp = tmp_path / 'vols.csv'
    csvp.write_text('volunteer_email,volunteer_first_name,volunteer_last_name,volunteer_position\n'
                    'casey@x.com,Casey,Coach,Head Coach\n'
                    'new@x.com,New,Person,Referee\n')
    stats = ingest.ingest_playmetrics_volunteers(con, str(csvp), season='MY2026')
    assert stats['matched'] == 1 and stats['created_unresolved'] == 1
    assert 'HEAD_COACH' in store.active_roles(con, '111-1', TODAY)


def _tiny_feed(ts='2026-06-14T00:00:00'):
    return {'generated_at': ts, 'volunteers': {'1-1': {
        'person': {'aysoid': '1-1', 'name': 'Avery Coach',
                   'aliases': {'emails': ['a@b.com'], 'phones': [], 'names': [], 'dobs': []}},
        'assignments': [{'season': 'MY2026', 'role': 'Head Coach', 'play_level': '10UB Boys'}],
        'certifications': {'safe_haven': {'windows': [{'begin': '2025-08-01', 'end': None}]}}}}}


def test_upsert_idempotent(tmp_path):
    import json
    from integrations.cert_model import ingest
    fp = tmp_path / 'f.json'
    fp.write_text(json.dumps(_tiny_feed()))
    con = store.build()
    ingest.ingest_affinity_feed(con, str(fp))
    ingest.ingest_affinity_feed(con, str(fp))      # same feed again
    c = lambda t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    assert c('participant_role') == 1 and c('participant_credential') == 1
    assert c('credential_verification') == 1        # same observed_at -> deduped


def test_verification_accrues_on_new_pull(tmp_path):
    import json
    from integrations.cert_model import ingest
    con = store.build()
    f1 = tmp_path / 'a.json'; f1.write_text(json.dumps(_tiny_feed('2026-06-14T00:00:00')))
    f2 = tmp_path / 'b.json'; f2.write_text(json.dumps(_tiny_feed('2026-09-01T00:00:00')))
    ingest.ingest_affinity_feed(con, str(f1))
    ingest.ingest_affinity_feed(con, str(f2))      # later pull -> new observation
    assert con.execute("SELECT COUNT(*) FROM participant_credential").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM credential_verification").fetchone()[0] == 2


def test_authority_verify_then_deny():
    from integrations.cert_model import authority, ingest
    con = store.build()
    store.add_participant(con, 'Pat Coach', participant_id='1-1', birthdate='1980-01-01')
    ingest._add_identity(con, '1-1', 'sports_affinity', 'native_id', '1-1')
    store.upsert_role(con, '1-1', 'HEAD_COACH', '2025-08-01', '2026-07-31', scope={'season': 'MY2026'})
    assert 'safesport' in store.compliance_as_of(con, '1-1', TODAY)['gaps']
    authority.apply_actions(con, [{'action': 'verify', 'aysoid': '1-1', 'credential': 'safesport',
                                   'from': '2026-01-01', 'to': '2027-01-01'}])
    assert 'safesport' not in store.compliance_as_of(con, '1-1', TODAY)['gaps']   # registrar verification wins
    authority.apply_actions(con, [{'action': 'deny', 'aysoid': '1-1', 'role_type': 'HEAD_COACH', 'season': 'MY2026'}])
    assert store.compliance_as_of(con, '1-1', TODAY)['status'] == 'no_active_role'


def test_export_matches_portal_schema():
    from integrations.cert_model import export
    con = store.build()
    store.add_participant(con, 'Pat Coach', participant_id='1-1', email='p@x.com', risk_status='green')
    store.upsert_role(con, '1-1', 'HEAD_COACH', '2025-08-01', '2026-07-31',
                      scope={'season': 'MY2026', 'division': '10UB Boys'})
    store.record_credential(con, '1-1', 'safe_haven', from_date='2025-08-01')
    payload = export.export_compliance_payload(con, TODAY)
    assert payload['source'] == 'cert_model' and payload['cert_types']
    v = payload['volunteers'][0]
    assert v['division'] == '10UB Boys' and v['position'] == 'Head Coach' and v['matched'] is True
    assert v['certifications']['safe_haven']['status'] == 'valid'
    assert '10UB Boys' in payload['summary_by_division']


def test_sensitive_evidence_is_discarded():
    con = store.build()
    pid = store.add_participant(con, 'Kid Player', participant_id='p-1', birthdate='2016-05-01')
    # try to sneak in an image URI + raw sensitive payload on a SENSITIVE credential
    store.record_credential(con, pid, 'birth_certificate', status='ACTIVE',
                            verification={'source_system': 'manual', 'method': 'document_review',
                                          'verified_by': 'registrar', 'evidence_kind': 'birth_certificate',
                                          'evidence_ref': 'CA DPH', 'observed_at': '2026-06-15',
                                          'evidence_uri': 'gs://secret/birthcert.jpg',
                                          'raw': {'doc_no': '123456789', 'dob': '2016-05-01'}})
    row = con.execute("SELECT v.evidence_uri, v.raw, v.evidence_kind, v.verified_by "
                      "FROM credential_verification v JOIN participant_credential c "
                      "USING(participant_credential_id) WHERE c.participant_id='p-1'").fetchone()
    assert row['evidence_uri'] is None and row['raw'] is None     # artifact DISCARDED
    assert row['evidence_kind'] == 'birth_certificate' and row['verified_by'] == 'registrar'  # provenance kept

    # a NON-sensitive electronic cert keeps its reference link
    cid = store.record_credential(con, pid, 'safesport',
                                  verification={'source_system': 'safesport', 'method': 'api',
                                                'evidence_uri': 'https://safesport/record/123',
                                                'observed_at': '2026-06-15'})
    r2 = con.execute("SELECT evidence_uri FROM credential_verification WHERE participant_credential_id=?",
                     (cid,)).fetchone()
    assert r2['evidence_uri'] == 'https://safesport/record/123'
