"""
PlayMetrics Portal Data Uploader (Cloud Storage)
=================================================

Uploads the latest data exports to Google Cloud Storage for the portal.
Run after --pm-download all to push fresh data.

Usage:
    python src/automation/playmetrics_portal_upload.py

Bucket: gs://region58-portal-data/
"""

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

BUCKET_NAME = os.environ.get('PORTAL_BUCKET', 'region58-portal-data')

UPLOAD_FILES = {
    "packages":               {"gcs_name": "packages.json"},
    "registration-responses": {"gcs_name": "registration-responses.csv"},
    "volunteers":             {"gcs_name": "volunteers.csv"},
    "coaching-requests":      {"gcs_name": "coaching-requests.csv"},
    "waitlist":               {"gcs_name": "waitlist.csv"},
    "compliance":             {"gcs_name": "compliance.json"},
    "compliance_next_steps":  {"gcs_name": "compliance_next_steps.json"},
    "etrainu_events":         {"gcs_name": "etrainu_events.json"},
    "volunteer_credentials":  {"gcs_name": "volunteer_credentials.json"},
}

# Also upload the API credentials (JWT) for portal-triggered refreshes
API_CREDS_FILE = "_api_credentials.json"


def _find_latest(data_dir, prefix):
    d = Path(data_dir)
    if not d.exists():
        return None
    pattern = re.compile(rf'^{re.escape(prefix)}_\d{{8}}_\d{{6}}\.\w+$')
    candidates = [f for f in d.iterdir() if f.is_file() and pattern.match(f.name)]
    if candidates:
        return max(candidates, key=lambda f: f.name)
    # Fall back to a stable (non-timestamped) name, e.g. compliance_next_steps.json
    for ext in ('json', 'csv'):
        stable = d / f"{prefix}.{ext}"
        if stable.is_file():
            return stable
    return None


def upload_portal_data(data_dir="data/playmetrics", bucket_name=None):
    from google.cloud import storage

    bucket_name = bucket_name or BUCKET_NAME
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    results = {}
    for prefix, config in UPLOAD_FILES.items():
        local_file = _find_latest(data_dir, prefix)
        if not local_file:
            logger.warning(f"No {prefix} file found in {data_dir}")
            continue

        gcs_name = config['gcs_name']
        blob = bucket.blob(gcs_name)
        blob.upload_from_filename(str(local_file))
        size_kb = local_file.stat().st_size / 1024
        logger.info(f"Uploaded: {gcs_name} ({size_kb:.1f} KB) from {local_file.name}")
        results[gcs_name] = str(local_file)

    # Upload metadata
    meta = json.dumps({
        'uploaded_at': datetime.now().isoformat(),
        'files': {k: str(v) for k, v in results.items()},
    }, indent=2)
    blob = bucket.blob('_metadata.json')
    blob.upload_from_string(meta, content_type='application/json')

    # Upload API credentials if available (for portal-triggered refreshes)
    creds_path = Path(data_dir) / API_CREDS_FILE
    if creds_path.exists():
        blob = bucket.blob(API_CREDS_FILE)
        blob.upload_from_filename(str(creds_path))
        logger.info(f"Uploaded: {API_CREDS_FILE} (API credentials for portal refresh)")

    # Sync player photos (only upload new ones)
    photos_dir = Path(data_dir) / 'player_photos'
    if photos_dir.exists():
        local_photos = list(photos_dir.glob('*.png'))
        if local_photos:
            # List existing photos in bucket
            existing = set(b.name for b in bucket.list_blobs(prefix='player_photos/'))
            new_photos = [p for p in local_photos if f'player_photos/{p.name}' not in existing]
            if new_photos:
                for photo in new_photos:
                    blob = bucket.blob(f'player_photos/{photo.name}')
                    blob.upload_from_filename(str(photo))
                logger.info(f"Uploaded {len(new_photos)} new player photos ({len(local_photos)} total)")
            else:
                logger.info(f"Player photos: {len(local_photos)} photos, all already in bucket")

    logger.info(f"Portal data upload complete: {len(results)} files to gs://{bucket_name}/")
    return results


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    import argparse
    p = argparse.ArgumentParser(description='Upload PlayMetrics data to Cloud Storage')
    p.add_argument('--data-dir', default='data/playmetrics')
    p.add_argument('--bucket', default=BUCKET_NAME)
    a = p.parse_args()
    results = upload_portal_data(a.data_dir, a.bucket)
    print(f"Uploaded {len(results)} files")
