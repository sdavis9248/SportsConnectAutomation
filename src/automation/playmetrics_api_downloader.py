"""
PlayMetrics API Download Module
================================

Hybrid approach: Selenium login → extract Firebase JWT → download via HTTP.
One login, all downloads via requests. No UI clicking after authentication.

Usage:
    downloader = PlayMetricsAPIDownloader(driver, program_id, download_dir)
    downloader.authenticate()  # extracts JWT from Selenium session
    
    # Then download any export directly:
    downloader.download('waitlist')
    downloader.download('responses')
    downloader.download('volunteers')
    downloader.download('coaching')

URL patterns are configured in API_ENDPOINTS — add new ones as discovered
from the PlayMetrics admin UI (DevTools Network tab → click export → copy URL).
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ── API endpoint registry ──
# Add URL patterns here as they are discovered from the PM admin UI.
# Use {program_id} as placeholder — it gets replaced at runtime.
# The access_key and fbt (Firebase JWT) are appended automatically.

API_ENDPOINTS = {
    'waitlist': {
        'path': '/program_admin/programs/{program_id}/waitlists.csv',
        'filename': 'waitlist',
        'description': 'Waitlist responses export',
    },
    # Add these as you discover the URL patterns from DevTools:
    #
    # 'responses': {
    #     'path': '/program_admin/programs/{program_id}/registrations.csv',
    #     'filename': 'registration-responses',
    #     'description': 'Registration responses export',
    # },
    # 'volunteers': {
    #     'path': '/program_admin/programs/{program_id}/volunteers.csv',
    #     'filename': 'volunteers',
    #     'description': 'Volunteer info export',
    # },
    # 'coaching': {
    #     'path': '/program_admin/programs/{program_id}/coaching_requests.csv',
    #     'filename': 'coaching-requests',
    #     'description': 'Coaching requests export',
    # },
}

API_BASE = 'https://api.playmetrics.com'


class PlayMetricsAPIDownloader:
    """Download PlayMetrics exports via direct API calls."""

    def __init__(self, driver, program_id, download_dir):
        """
        Args:
            driver: Selenium WebDriver (already logged in to PM)
            program_id: PlayMetrics program ID (e.g., 101848)
            download_dir: Where to save downloaded files
        """
        self.driver = driver
        self.program_id = str(program_id)
        self.download_dir = download_dir
        self.firebase_jwt = None
        self.access_key = None
        self.jwt_expiry = None
        self.session = requests.Session()

        Path(download_dir).mkdir(parents=True, exist_ok=True)

    def authenticate(self):
        """Extract Firebase JWT and access key from the Selenium session."""
        try:
            # Extract Firebase auth data from localStorage
            raw = self.driver.execute_script("""
                var entries = Object.entries(localStorage);
                for (var i = 0; i < entries.length; i++) {
                    if (entries[i][0].indexOf('firebase:authUser') !== -1) {
                        return entries[i][1];
                    }
                }
                return null;
            """)

            if not raw:
                logger.error("No Firebase auth data in localStorage. Is the user logged in?")
                return False

            auth_data = json.loads(raw)
            token_manager = auth_data.get('stsTokenManager', {})
            self.firebase_jwt = token_manager.get('accessToken')
            expiry_ms = token_manager.get('expirationTime', 0)
            self.jwt_expiry = datetime.fromtimestamp(expiry_ms / 1000) if expiry_ms else None

            if not self.firebase_jwt:
                logger.error("Firebase JWT not found in auth data")
                return False

            # Extract access key from cookies or generate from session
            cookies = {c['name']: c['value'] for c in self.driver.get_cookies()}
            self.session.cookies.update(cookies)

            # Set up session headers
            user_agent = self.driver.execute_script("return navigator.userAgent")
            self.session.headers.update({
                'User-Agent': user_agent,
                'Referer': 'https://playmetrics.com/',
            })

            # Try to extract access_key from a known export link on the page
            self.access_key = self._extract_access_key()

            expiry_str = self.jwt_expiry.strftime('%H:%M:%S') if self.jwt_expiry else 'unknown'
            logger.info(f"Authenticated — JWT expires at {expiry_str}")
            logger.info(f"Access key: {'found' if self.access_key else 'not found (will use JWT only)'}")

            return True

        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _extract_access_key(self):
        """Try to extract the access_key from an export link on the current page."""
        try:
            # Look for any download link that has access_key in the href
            links = self.driver.execute_script("""
                var links = document.querySelectorAll('a[href*="access_key"]');
                if (links.length > 0) {
                    return links[0].href;
                }
                return null;
            """)
            if links:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(links)
                params = parse_qs(parsed.query)
                return params.get('access_key', [None])[0]
        except Exception:
            pass
        return None

    def is_jwt_valid(self):
        """Check if the Firebase JWT is still valid (not expired)."""
        if not self.firebase_jwt:
            return False
        if not self.jwt_expiry:
            return True  # no expiry info, assume valid
        # Add 60-second buffer
        return datetime.now() < (self.jwt_expiry - timedelta(seconds=60))

    def refresh_jwt(self):
        """Re-extract JWT from the browser session if it's been refreshed."""
        logger.info("Refreshing Firebase JWT from browser session...")
        # Navigate to PM to trigger token refresh
        self.driver.get('https://playmetrics.com/program-admin/programs/' + self.program_id)
        time.sleep(3)
        return self.authenticate()

    def download(self, export_type, force=False):
        """
        Download an export by type.

        Args:
            export_type: Key from API_ENDPOINTS ('waitlist', 'responses', etc.)
            force: Download even if a recent file exists

        Returns:
            Path to downloaded file, or None on failure
        """
        endpoint = API_ENDPOINTS.get(export_type)
        if not endpoint:
            available = ', '.join(API_ENDPOINTS.keys())
            logger.error(f"Unknown export type '{export_type}'. Available: {available}")
            return None

        if not self.firebase_jwt:
            logger.error("Not authenticated. Call authenticate() first.")
            return None

        # Check JWT validity
        if not self.is_jwt_valid():
            logger.warning("JWT expired, attempting refresh...")
            if not self.refresh_jwt():
                logger.error("JWT refresh failed")
                return None

        # Build the URL
        path = endpoint['path'].replace('{program_id}', self.program_id)
        url = API_BASE + path

        params = {'fbt': self.firebase_jwt}
        if self.access_key:
            params['access_key'] = self.access_key

        logger.info(f"Downloading {endpoint['description']}...")
        logger.info(f"  URL: {url[:80]}...")

        try:
            resp = self.session.get(url, params=params, timeout=60, allow_redirects=True)

            if resp.status_code == 200 and resp.content:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{endpoint['filename']}_{timestamp}.csv"
                filepath = os.path.join(self.download_dir, filename)

                with open(filepath, 'wb') as f:
                    f.write(resp.content)

                size_kb = len(resp.content) / 1024
                logger.info(f"  Saved: {filepath} ({size_kb:.1f} KB)")
                return filepath
            else:
                logger.error(f"  Download failed: HTTP {resp.status_code}")
                if resp.status_code == 401:
                    logger.error("  Token may be expired. Try re-authenticating.")
                elif resp.status_code == 403:
                    logger.error("  Access denied. Check permissions.")
                logger.debug(f"  Response: {resp.text[:200]}")
                return None

        except requests.Timeout:
            logger.error(f"  Download timed out")
            return None
        except Exception as e:
            logger.error(f"  Download failed: {e}")
            return None

    def download_all(self):
        """Download all configured exports."""
        results = {}
        for export_type in API_ENDPOINTS:
            result = self.download(export_type)
            results[export_type] = result
        return results

    def download_via_url(self, url, filename_prefix="export"):
        """Download from a full API URL (for ad-hoc/discovered endpoints).

        Use this when you have the complete URL from DevTools but haven't
        added it to API_ENDPOINTS yet.
        """
        if not self.firebase_jwt:
            logger.error("Not authenticated.")
            return None

        # If the URL already has fbt param, use as-is; otherwise append
        if 'fbt=' not in url:
            sep = '&' if '?' in url else '?'
            url = f"{url}{sep}fbt={self.firebase_jwt}"

        logger.info(f"Downloading from URL: {url[:80]}...")

        try:
            resp = self.session.get(url, timeout=60, allow_redirects=True)
            if resp.status_code == 200 and resp.content:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filepath = os.path.join(self.download_dir, f"{filename_prefix}_{timestamp}.csv")
                with open(filepath, 'wb') as f:
                    f.write(resp.content)
                logger.info(f"  Saved: {filepath} ({len(resp.content)/1024:.1f} KB)")
                return filepath
            else:
                logger.error(f"  Failed: HTTP {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"  Failed: {e}")
            return None
