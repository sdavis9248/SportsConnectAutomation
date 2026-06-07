"""
Google Drive sync for PlayMetrics Director report packets.

Uploads each division's report files into the matching Drive folder under
  My Drive / AYSO Region 58 Registration / Fall 2026 / <Division>
updating the existing file in place (same fileId) so per-Director folder shares
keep working. Uses OAuth user credentials (owned-by-user, no service-account
storage-quota problem). Full 'drive' scope is required so it can locate the
folders that were created outside this app and update existing files.

Auth reuses the same credentials.json OAuth client as the rest of the repo, but
keeps its own token file because the scope differs from GoogleDriveUploader.
"""
import os
import pickle
import json
import logging
from pathlib import Path
from typing import Dict, Optional, List

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

# The Fall 2026 folder created under "AYSO Region 58 Registration".
DEFAULT_SEASON_FOLDER_ID = '1aAOGrDmZI2J25Z1H8ez22ug8L9aoAqPo'


class DirectorReportDriveSync:
    """Sync per-division report files into the AYSO Region 58 Registration tree."""

    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self, config=None,
                 credentials_file: str = None,
                 token_file: str = None,
                 season_folder_id: str = None,
                 impersonate: str = None):
        self.config = config
        cfg = (config.get('director_drive', {}) if config else {}) or {}
        gcfg = (config.get('google_drive_config', {}) if config else {}) or {}
        self.credentials_file = (credentials_file or cfg.get('credentials_file')
                                 or gcfg.get('credentials_file', 'credentials.json'))
        # Separate token (full-drive scope) so it doesn't collide with token.pickle.
        self.token_file = token_file or cfg.get('token_file', 'token_drive_full.pickle')
        self.season_folder_id = (season_folder_id or cfg.get('season_folder_id')
                                 or DEFAULT_SEASON_FOLDER_ID)
        # For a service account: which Drive owner to act as (domain-wide delegation).
        # Defaults to the registrar so files land in / are owned by that account.
        self.impersonate = (impersonate or cfg.get('impersonate')
                            or gcfg.get('impersonate') or 'registrar@ayso58.org')
        self.service = None
        self.creds = None
        self._folder_cache: Dict[str, str] = {}
        self._authenticate()

    # ── auth ──────────────────────────────────────────────────────────────
    def _authenticate(self):
        if not os.path.exists(self.credentials_file):
            raise FileNotFoundError(
                f"Google Drive credentials file not found: {self.credentials_file}")
        # Detect credential type: service account key vs OAuth client secrets.
        with open(self.credentials_file, encoding='utf-8') as f:
            cred_json = json.load(f)
        if cred_json.get('type') == 'service_account':
            self._auth_service_account()
        else:
            self._auth_oauth()
        self.service = build('drive', 'v3', credentials=self.creds)
        logger.info("Google Drive sync authenticated")

    def _auth_service_account(self):
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            self.credentials_file, scopes=self.SCOPES)
        # Domain-wide delegation: act as the Drive owner so created files are owned
        # by a real account (service accounts have no storage quota of their own).
        if self.impersonate:
            creds = creds.with_subject(self.impersonate)
            logger.info(f"Service account impersonating {self.impersonate}")
        else:
            logger.warning("Service account without impersonation - file creation in "
                           "My Drive will fail (no storage quota). Set director_drive.impersonate.")
        self.creds = creds

    def _auth_oauth(self):
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as t:
                self.creds = pickle.load(t)
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                logger.info("Refreshing Drive token...")
                self.creds.refresh(Request())
            else:
                logger.info("Authorizing Google Drive (full scope, one-time)...")
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, self.SCOPES)
                self.creds = flow.run_local_server(port=0)
            with open(self.token_file, 'wb') as t:
                pickle.dump(self.creds, t)

    # ── folder / file lookup ──────────────────────────────────────────────
    @staticmethod
    def _esc(name: str) -> str:
        return name.replace("\\", "\\\\").replace("'", "\\'")

    def division_folder_id(self, division: str) -> Optional[str]:
        """Resolve the Drive folder for a division by exact name under the season folder."""
        if division in self._folder_cache:
            return self._folder_cache[division]
        q = (f"'{self.season_folder_id}' in parents and "
             f"mimeType = 'application/vnd.google-apps.folder' and "
             f"name = '{self._esc(division)}' and trashed = false")
        res = self.service.files().list(q=q, fields='files(id,name)', pageSize=5).execute()
        files = res.get('files', [])
        fid = files[0]['id'] if files else None
        if fid:
            self._folder_cache[division] = fid
        else:
            logger.warning(f"No Drive folder named '{division}' under the season folder")
        return fid

    def _existing_file_id(self, parent_id: str, title: str) -> Optional[str]:
        q = (f"'{parent_id}' in parents and name = '{self._esc(title)}' and trashed = false")
        res = self.service.files().list(q=q, fields='files(id,name)', pageSize=5).execute()
        files = res.get('files', [])
        return files[0]['id'] if files else None

    # ── upload ────────────────────────────────────────────────────────────
    def upload_or_update(self, local_path: str, parent_id: str,
                         title: str = None, mime: str = XLSX_MIME) -> Optional[str]:
        """Update the file in place if it already exists in the folder, else create it.
        Returns the Drive file ID."""
        title = title or os.path.basename(local_path)
        media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
        existing = self._existing_file_id(parent_id, title)
        if existing:
            self.service.files().update(fileId=existing, media_body=media).execute()
            logger.info(f"Updated {title} (id {existing})")
            return existing
        meta = {'name': title, 'parents': [parent_id]}
        created = self.service.files().create(body=meta, media_body=media, fields='id').execute()
        logger.info(f"Created {title} (id {created.get('id')})")
        return created.get('id')

    def sync_manifest(self, manifest_path: str) -> Dict[str, int]:
        """Read a director-reports packet_manifest.json and push every file into the
        Drive folder matching its division. Files are matched to folders by the real
        division name (e.g. '10UB Boys'), not the local safe folder name."""
        stats = {'uploaded': 0, 'skipped_no_folder': 0, 'missing_local': 0}
        with open(manifest_path, encoding='utf-8') as f:
            manifest = json.load(f)
        for pk in manifest.get('packets', {}).values():
            for rec in pk.get('files', []):
                division = rec.get('division')
                local = rec.get('path')
                if not local or not os.path.exists(local):
                    stats['missing_local'] += 1
                    continue
                folder = self.division_folder_id(division)
                if not folder:
                    stats['skipped_no_folder'] += 1
                    continue
                self.upload_or_update(local, folder, os.path.basename(local))
                stats['uploaded'] += 1
        logger.info(f"Drive sync: {stats['uploaded']} uploaded, "
                    f"{stats['skipped_no_folder']} skipped (no folder), "
                    f"{stats['missing_local']} missing local")
        return stats