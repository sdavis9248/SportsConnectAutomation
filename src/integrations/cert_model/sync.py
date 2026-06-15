"""
Sync orchestration — operate the cert_model DB as the system of record.

Idempotent, re-runnable pipeline:
  1. open the DURABLE DB (optionally pull it from the bucket first)
  2. reconcile from the feeds — Affinity volunteer_credentials.json (credentials) +
     the latest PlayMetrics volunteers CSV (who's serving). Feeds are SUPPLIERS.
  3. apply registrar AUTHORITY actions (data/cert_actions.json) — these WIN over feeds.
  4. export the portal's compliance.json FROM the DB (flips the producer).
  5. optional --publish: upload compliance.json (+ persist the DB) to the bucket.

Run:  python -m integrations.cert_model.sync           # local, no publish (safe)
      python -m integrations.cert_model.sync --publish --bucket

Modification History:
  2026-06-14  New — DB-as-system-of-record sync (reconcile feeds + authority + export).
"""
import argparse
import glob
import json
import os

from integrations.cert_model import authority, export, ingest, store

DATA = 'data/playmetrics'
DB_PATH = os.path.join(DATA, 'region58.db')
FEED = os.path.join(DATA, 'volunteer_credentials.json')
ACTIONS = 'data/cert_actions.json'
COMPLIANCE_OUT = os.path.join(DATA, 'compliance.json')
BUCKET = os.environ.get('PORTAL_BUCKET', 'region58-portal-data')
DB_BLOB = 'cert_model/region58.db'          # durable SoR home in the bucket


def _latest_volunteers():
    files = sorted(glob.glob(os.path.join(DATA, 'volunteers*.csv')), key=os.path.getmtime, reverse=True)
    return files[0] if files else None


def _bucket():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)


def pull_db(path=DB_PATH):
    try:
        b = _bucket().blob(DB_BLOB)
        if b.exists():
            b.download_to_filename(path)
            return True
    except Exception as e:
        print('pull_db skipped:', e)
    return False


def push_db(path=DB_PATH):
    _bucket().blob(DB_BLOB).upload_from_filename(path)


def publish_compliance(path=COMPLIANCE_OUT):
    _bucket().blob('compliance.json').upload_from_filename(path)


def run(season='MY2026', publish=False, use_bucket=False, as_of=None):
    if use_bucket:
        pull_db()
    con = store.open_or_create(DB_PATH)
    feeds = ingest.sync_from_feeds(con, FEED, _latest_volunteers(), season=season)
    actions = authority.apply_actions_file(con, ACTIONS)
    payload = export.write_compliance_json(con, COMPLIANCE_OUT, as_of=as_of, season=season)
    out = {'feeds': feeds, 'authority': actions,
           'serving_entries': len(payload['volunteers']),
           'divisions': len(payload['summary_by_division'])}
    if publish:
        publish_compliance()
        if use_bucket:
            push_db()
        out['published'] = True
    con.commit()
    con.close()
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', default='MY2026')
    ap.add_argument('--publish', action='store_true',
                    help='upload compliance.json (and DB if --bucket) to the GCS bucket')
    ap.add_argument('--bucket', action='store_true',
                    help='pull/persist the durable DB from/to the bucket')
    a = ap.parse_args()
    print(json.dumps(run(season=a.season, publish=a.publish, use_bucket=a.bucket), indent=2))
