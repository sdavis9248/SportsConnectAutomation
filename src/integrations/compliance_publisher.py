"""
Publish volunteer compliance to the board portal.

Pipeline:
  Affinity exports + volunteers.csv
    -> AffinityComplianceAdapter.build_package()        (governing-system agnostic)
    -> IdentityResolver.attach(volunteers)              (email > phone > name)
    -> build_portal_payload()                           (portal compliance.json shape)
    -> upload compliance.json to the portal data store.

The portal reads stable-named files from the GCS bucket 'region58-portal-data'
(primary on Cloud Run) and/or the Drive 'portal-data' folder. Writing a blob to
the bucket has no storage-quota issue (bucket storage is project-owned), so the
service account you already have works directly. A Drive upload path is included
for parity with the portal's DriveDataSource.
"""
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

PORTAL_BUCKET = 'region58-portal-data'
PORTAL_DRIVE_FOLDER_ID = '1n-b7de6lMOl6myu5HA-0OmODUK-SLK4W'  # Fall 2026/portal-data
COMPLIANCE_FILENAME = 'compliance.json'


def build_compliance_payload(credentials_path, details_path, volunteers_path,
                             season=None, overrides=None, history_path=None):
    """Run the full provider pipeline and return the portal compliance.json dict.

    history_path: volunteer_credentials.json (the multi-season alias pool). If not
    given, it's auto-discovered next to the volunteers file; when present it lets
    the resolver match PM volunteers on a historical email/phone/name, recovering
    matches the single current-season export misses.
    """
    import csv
    from integrations.compliance_provider import (
        AffinityComplianceAdapter, IdentityResolver, build_portal_payload,
        load_credential_history)
    pkg = AffinityComplianceAdapter(credentials_path, details_path, season=season).build_package()
    with open(volunteers_path, newline='', encoding='utf-8-sig') as f:
        vols = list(csv.DictReader(f))
    if isinstance(overrides, str) and os.path.exists(overrides):
        overrides = json.load(open(overrides))
    if history_path is None:
        cand = os.path.join(os.path.dirname(volunteers_path) or '.', 'volunteer_credentials.json')
        history_path = cand if os.path.exists(cand) else None
    history = load_credential_history(history_path) if history_path else None
    resolved = IdentityResolver(pkg, overrides=overrides, history=history).attach(vols)
    payload = build_portal_payload(pkg, resolved, season=season)
    payload['_stats'] = {
        'records': len(pkg.records),
        'volunteers': len(resolved['resolved']),
        'matched': len(resolved['resolved']) - len(resolved['unmatched_volunteers']),
        'unmatched': len(resolved['unmatched_volunteers']),
        'history_matched': sum(1 for r in resolved['resolved']
                               if str(r.get('_match_method', '')).endswith('_history')),
    }
    return payload


def upload_to_gcs(payload, bucket_name=PORTAL_BUCKET, filename=COMPLIANCE_FILENAME,
                  credentials_file=None):
    """Upload compliance.json to the portal GCS bucket. Returns gs:// path."""
    from google.cloud import storage
    if credentials_file and os.path.exists(credentials_file):
        client = storage.Client.from_service_account_json(credentials_file)
    else:
        client = storage.Client()  # Application Default Credentials
    blob = client.bucket(bucket_name).blob(filename)
    blob.upload_from_string(json.dumps(payload, default=str), content_type='application/json')
    logger.info(f"Uploaded {filename} to gs://{bucket_name}/{filename}")
    return f"gs://{bucket_name}/{filename}"


def upload_to_drive(payload, folder_id=PORTAL_DRIVE_FOLDER_ID, filename=COMPLIANCE_FILENAME,
                    credentials_file=None, impersonate=None):
    """Upload/update compliance.json in the portal Drive folder (parity with the
    portal's DriveDataSource). Updates in place if it already exists."""
    import io
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    creds = _drive_creds(credentials_file, impersonate)
    svc = build('drive', 'v3', credentials=creds)
    media = MediaIoBaseUpload(io.BytesIO(json.dumps(payload, default=str).encode('utf-8')),
                              mimetype='application/json', resumable=True)
    q = f"'{folder_id}' in parents and name = '{filename}' and trashed = false"
    found = svc.files().list(q=q, fields='files(id)').execute().get('files', [])
    if found:
        svc.files().update(fileId=found[0]['id'], media_body=media).execute()
        logger.info(f"Updated {filename} in portal Drive folder")
        return found[0]['id']
    meta = {'name': filename, 'parents': [folder_id]}
    created = svc.files().create(body=meta, media_body=media, fields='id').execute()
    logger.info(f"Created {filename} in portal Drive folder")
    return created.get('id')


def _drive_creds(credentials_file, impersonate):
    if credentials_file and os.path.exists(credentials_file):
        with open(credentials_file, encoding='utf-8') as f:
            kind = json.load(f).get('type')
        if kind == 'service_account':
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                credentials_file, scopes=['https://www.googleapis.com/auth/drive'])
            return creds.with_subject(impersonate) if impersonate else creds
    import google.auth
    creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/drive'])
    return creds


def write_to_data_dir(payload, data_dir="data/playmetrics"):
    """Write compliance_<timestamp>.json into the data dir so the existing portal
    uploader (playmetrics_portal_upload.py) pushes it as compliance.json."""
    os.makedirs(data_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(data_dir, f"compliance_{ts}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info(f"Wrote {path}")
    return path


def publish(config=None, credentials_path=None, details_path=None, volunteers_path=None,
            season=None, overrides=None, data_dir="data/playmetrics", target='local',
            out_path=None):
    """Build the compliance payload and publish it.

    target:
      'local' (default) - write compliance_<ts>.json into data_dir; the existing
                          playmetrics_portal_upload.py then pushes it to the bucket.
                          Reuses the trusted upload path - recommended.
      'gcs'             - upload compliance.json straight to the portal bucket.
      'drive'           - upload into the portal Drive folder.
      'both'            - gcs + drive.
    """
    cfg = (config.get('director_drive', {}) if config else {}) or {}
    gcfg = (config.get('google_drive_config', {}) if config else {}) or {}
    sa = (cfg.get('credentials_file') or gcfg.get('credentials_file'))
    impersonate = cfg.get('impersonate') or gcfg.get('impersonate') or 'registrar@ayso58.org'

    payload = build_compliance_payload(credentials_path, details_path, volunteers_path,
                                       season=season, overrides=overrides)
    if target == 'local':
        write_to_data_dir(payload, data_dir)
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, default=str)
    if target in ('gcs', 'both'):
        upload_to_gcs(payload, credentials_file=sa)
    if target in ('drive', 'both'):
        upload_to_drive(payload, credentials_file=sa, impersonate=impersonate)
    return payload['_stats']


def handle_pm_compliance(config, args):
    """main.py entry point for `--compliance`. Auto-discovers the Affinity exports
    and the latest volunteers CSV so the bare `--compliance` flag works, then builds
    and stages compliance.json. Override any input with the --compliance-* flags."""
    import glob
    log = logging.getLogger(__name__)

    data_dir = getattr(args, 'compliance_data_dir', None) or 'data/playmetrics'
    downloads = getattr(args, 'compliance_downloads', None) or 'data/downloads'

    def latest(*globs):
        hits = []
        for g in globs:
            hits += glob.glob(g)
        return max(hits, key=os.path.getmtime) if hits else None

    cred = getattr(args, 'compliance_credentials', None) or latest(
        os.path.join(downloads, 'AdminCredentials*.xlsx'),
        os.path.join(downloads, 'AdminCredentialsStatusDynamic*.xlsx'))
    det = getattr(args, 'compliance_details', None) or latest(
        os.path.join(downloads, 'teamAdminDetail*.xlsx'),
        os.path.join(downloads, 'AdminDetail*.xlsx'))
    vols = getattr(args, 'compliance_volunteers', None) or latest(
        os.path.join(data_dir, 'volunteers_*.csv'))

    if not cred:
        log.error(f"No Admin Credentials .xlsx found in {downloads}; pass --compliance-credentials")
        return 1
    if not vols:
        log.error(f"No volunteers_*.csv found in {data_dir}; pass --compliance-volunteers")
        return 1
    if not det:
        log.warning("No Admin Details export found; phone matching will be limited")

    season = getattr(args, 'compliance_season', None) or 'Fall 2026'
    target = getattr(args, 'compliance_target', None) or 'local'
    overrides = getattr(args, 'compliance_overrides', None)

    log.info(f"Compliance: creds={os.path.basename(cred)} "
             f"details={os.path.basename(det) if det else None} "
             f"volunteers={os.path.basename(vols)} -> target={target}")
    # local target needs no cloud creds; gcs/drive fall back to Application Default Credentials
    stats = publish(config=None, credentials_path=cred, details_path=det, volunteers_path=vols,
                    season=season, overrides=overrides, data_dir=data_dir, target=target)
    print(f"Compliance staged: {stats['matched']}/{stats['volunteers']} volunteers matched "
          f"to {stats['records']} governing-system records ({stats['unmatched']} unmatched).")
    if target == 'local':
        print(r"Next: python src\automation\playmetrics_portal_upload.py  "
              "(pushes compliance.json to the portal bucket)")
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    import argparse
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    ap = argparse.ArgumentParser(description='Build volunteer compliance and stage it for the portal')
    ap.add_argument('--credentials', required=True, help='Affinity Admin Credentials .xlsx')
    ap.add_argument('--details', help='Affinity Admin Details (All Fields) .xlsx')
    ap.add_argument('--volunteers', required=True, help='PlayMetrics volunteers_*.csv')
    ap.add_argument('--data-dir', default='data/playmetrics')
    ap.add_argument('--season', default='Fall 2026')
    ap.add_argument('--overrides', help='JSON map: volunteer email -> AYSO ID')
    ap.add_argument('--target', default='local', choices=['local', 'gcs', 'drive', 'both'])
    a = ap.parse_args()
    stats = publish(credentials_path=a.credentials, details_path=a.details,
                    volunteers_path=a.volunteers, season=a.season, overrides=a.overrides,
                    data_dir=a.data_dir, target=a.target)
    print(f"Compliance: {stats['matched']}/{stats['volunteers']} volunteers matched "
          f"to {stats['records']} governing-system records ({stats['unmatched']} unmatched).")
