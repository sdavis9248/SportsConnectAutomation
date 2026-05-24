"""
PlayMetrics Download Manager for Sports Connect Automation

Automates CSV export downloads from the PlayMetrics admin portal.
Downloads the three exports required for the Enrollment Summary Report:
  1. Registration Responses (Programs → More Actions → Export Responses)
  2. Volunteers (Programs → More Actions → Export Volunteers)
  3. Coaching Requests (Leagues → Coaching Requests → More Actions → Export)

Architecture follows the SportsAffinityManager pattern:
  - Takes a Selenium WebDriver + ConfigManager
  - Uses ElementInteractor for robust multi-selector element finding
  - Can operate standalone or share a driver with the main automation
  - Downloads land in data/playmetrics/ for consumption by PlayMetricsDataManager

PlayMetrics is a React SPA — all selectors use explicit waits and
multiple fallback strategies (text content, aria-labels, data-testid, CSS).
"""
import os
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    ElementClickInterceptedException, StaleElementReferenceException
)

logger = logging.getLogger(__name__)


class PlayMetricsExportType:
    """Export types available in PlayMetrics admin"""
    REGISTRATION_RESPONSES = "registration_responses"
    VOLUNTEERS = "volunteers"
    COACHING_REQUESTS = "coaching_requests"
    PLAYERS = "players"
    SUBSCRIPTIONS = "subscriptions"


class PlayMetricsDownloadManager:
    """
    Automates PlayMetrics admin CSV export downloads via Selenium.

    Usage:
        # Standalone (creates its own driver)
        manager = PlayMetricsDownloadManager(config=config)
        manager.initialize()
        manager.login()
        files = manager.download_all_enrollment_exports()
        manager.cleanup()

        # Shared driver (from SportsConnectAutomation)
        manager = PlayMetricsDownloadManager(
            driver=automation.driver,
            config=config
        )
        manager.login()
        files = manager.download_all_enrollment_exports()
    """

    # Default PlayMetrics admin URL
    DEFAULT_BASE_URL = "https://admin.playmetrics.com"

    # Download filename patterns for each export type
    EXPORT_PATTERNS = {
        PlayMetricsExportType.REGISTRATION_RESPONSES: [
            "registration-responses*.csv",
            "registration_responses*.csv",
            "*responses*.csv",
        ],
        PlayMetricsExportType.VOLUNTEERS: [
            "volunteers*.csv",
            "volunteer*.csv",
        ],
        PlayMetricsExportType.COACHING_REQUESTS: [
            "*coaching-requests*.csv",
            "*coaching_requests*.csv",
            "*coaching*.csv",
        ],
        PlayMetricsExportType.PLAYERS: [
            "players*.csv",
            "*player*.csv",
        ],
        PlayMetricsExportType.SUBSCRIPTIONS: [
            "subscriptions*.csv",
            "*subscription*.csv",
        ],
    }

    def __init__(self, driver=None, config=None):
        """
        Initialize PlayMetrics Download Manager.

        Args:
            driver: Existing Selenium WebDriver (None = create our own)
            config: ConfigManager instance
        """
        self.config = config
        self.driver = driver
        self.owns_driver = driver is None
        self.interactor = None
        self.wait = None
        self.logged_in = False
        self.driver_manager = None

        # PlayMetrics-specific config
        pm_config = config.get('playmetrics_config', {}) if config else {}
        self.base_url = pm_config.get('base_url', self.DEFAULT_BASE_URL)
        self.program_name = pm_config.get(
            'program_name',
            config.get('season', '2026 Fall Core') if config else '2026 Fall Core'
        )
        self.league_name = pm_config.get('league_name', '')

        # Credentials
        self.pm_username = pm_config.get('username', '')
        self.pm_password = pm_config.get('password', '')
        self.credentials_file = pm_config.get(
            'credentials_file', 'config/playmetrics_creds.csv'
        )

        # Download directory — matches PlayMetricsDataManager expectation
        self.download_dir = pm_config.get(
            'download_dir',
            str(Path(config.get('paths.data_dir', 'data') if config else 'data') / 'playmetrics')
        )
        Path(self.download_dir).mkdir(parents=True, exist_ok=True)

        # Timing
        self.page_load_wait = pm_config.get('page_load_wait', 8)
        self.export_wait = pm_config.get('export_wait', 15)
        self.download_timeout = pm_config.get('download_timeout', 30)

        # Download tracking
        self.downloaded_files: Dict[str, str] = {}

    # =========================================================
    #  LIFECYCLE
    # =========================================================

    def initialize(self):
        """Create WebDriver if we don't have one (standalone mode)."""
        if self.driver is not None:
            # Using shared driver — just set up interactor
            from core.element_interactor import ElementInteractor
            self.interactor = ElementInteractor(self.driver)
            self.wait = WebDriverWait(self.driver, 15)
            return

        # Standalone mode — create our own driver
        from core.webdriver_manager import WebDriverManager as WDM
        self.driver_manager = WDM(
            download_dir=self.download_dir,
            headless=self.config.get('headless_mode', False) if self.config else False
        )
        self.driver = self.driver_manager.create_driver()

        from core.element_interactor import ElementInteractor
        self.interactor = ElementInteractor(self.driver)
        self.wait = WebDriverWait(self.driver, 15)

        logger.info("PlayMetrics Download Manager initialized (standalone driver)")

    def cleanup(self):
        """Clean up driver if we own it."""
        if self.owns_driver and self.driver_manager:
            self.driver_manager.quit()
            self.driver = None
            logger.info("PlayMetrics Download Manager cleaned up")

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    # =========================================================
    #  LOGIN
    # =========================================================

    def _load_credentials(self) -> Tuple[str, str]:
        """
        Load PlayMetrics credentials.

        Tries in order:
          1. Config values (playmetrics_config.username/password)
          2. CSV file (playmetrics_creds.csv)
          3. Environment variables (PM_USERNAME, PM_PASSWORD)
        """
        if self.pm_username and self.pm_password:
            return self.pm_username, self.pm_password

        # Try CSV file
        creds_path = Path(self.credentials_file)
        if creds_path.exists():
            import csv
            with open(creds_path, 'r') as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                row = next(reader, None)
                if row and len(row) >= 2:
                    logger.info(f"Loaded PM credentials from {creds_path}")
                    return row[0].strip(), row[1].strip()

        # Try environment variables
        env_user = os.environ.get('PM_USERNAME', '')
        env_pass = os.environ.get('PM_PASSWORD', '')
        if env_user and env_pass:
            logger.info("Loaded PM credentials from environment variables")
            return env_user, env_pass

        raise ValueError(
            "PlayMetrics credentials not found. "
            "Set playmetrics_config.username/password in config.json, "
            "create config/playmetrics_creds.csv, "
            "or set PM_USERNAME/PM_PASSWORD environment variables."
        )

    def login(self) -> bool:
        """
        Log into the PlayMetrics admin portal.

        Returns:
            True if login succeeded
        """
        logger.info("Logging into PlayMetrics...")

        try:
            username, password = self._load_credentials()

            # Navigate to login page
            login_url = f"{self.base_url}/login"
            logger.info(f"Navigating to: {login_url}")
            self.driver.get(login_url)
            time.sleep(self.page_load_wait)

            # --- Enter email ---
            email_selectors = [
                (By.CSS_SELECTOR, 'input[type="email"]'),
                (By.CSS_SELECTOR, 'input[name="email"]'),
                (By.XPATH, '//input[@placeholder="Email" or @placeholder="Email address"]'),
                (By.CSS_SELECTOR, 'input[autocomplete="email"]'),
                (By.CSS_SELECTOR, 'input[data-testid="email-input"]'),
            ]
            if not self.interactor.try_multiple_selectors(
                email_selectors, "send_keys", text=username, timeout=10
            ):
                raise Exception("Could not find email field")
            logger.info("Entered email")

            # --- Enter password ---
            password_selectors = [
                (By.CSS_SELECTOR, 'input[type="password"]'),
                (By.CSS_SELECTOR, 'input[name="password"]'),
                (By.XPATH, '//input[@placeholder="Password"]'),
                (By.CSS_SELECTOR, 'input[data-testid="password-input"]'),
            ]
            if not self.interactor.try_multiple_selectors(
                password_selectors, "send_keys", text=password, timeout=5
            ):
                raise Exception("Could not find password field")
            logger.info("Entered password")

            # --- Click login/sign-in button ---
            login_btn_selectors = [
                (By.XPATH, '//button[contains(text(), "Log In")]'),
                (By.XPATH, '//button[contains(text(), "Sign In")]'),
                (By.XPATH, '//button[contains(text(), "Login")]'),
                (By.CSS_SELECTOR, 'button[type="submit"]'),
                (By.CSS_SELECTOR, 'button[data-testid="login-button"]'),
            ]
            if not self.interactor.try_multiple_selectors(
                login_btn_selectors, "click", timeout=5
            ):
                raise Exception("Could not find login button")
            logger.info("Clicked login button")

            # Wait for dashboard to load
            time.sleep(self.page_load_wait)

            # Verify login succeeded — look for dashboard indicators
            dashboard_selectors = [
                (By.XPATH, '//span[contains(text(), "Dashboard")]'),
                (By.XPATH, '//a[contains(text(), "Programs")]'),
                (By.XPATH, '//*[contains(text(), "Welcome")]'),
                (By.CSS_SELECTOR, '[data-testid="main-nav"]'),
                (By.CSS_SELECTOR, 'nav'),
            ]

            # Check URL — should no longer be on login page
            current_url = self.driver.current_url
            if "login" in current_url.lower():
                self._take_screenshot("pm_login_failed")
                raise Exception("Still on login page after submit")

            self.logged_in = True
            logger.info("PlayMetrics login successful")
            return True

        except Exception as e:
            logger.error(f"PlayMetrics login failed: {e}")
            self._take_screenshot("pm_login_error")
            return False

    # =========================================================
    #  NAVIGATION
    # =========================================================

    def _navigate_to_programs(self) -> bool:
        """Navigate to the Programs section."""
        logger.info("Navigating to Programs...")
        try:
            programs_selectors = [
                (By.XPATH, '//a[contains(text(), "Programs")]'),
                (By.XPATH, '//span[contains(text(), "Programs")]'),
                (By.CSS_SELECTOR, 'a[href*="/programs"]'),
                (By.CSS_SELECTOR, '[data-testid="nav-programs"]'),
            ]
            if self.interactor.try_multiple_selectors(
                programs_selectors, "click", timeout=10
            ):
                time.sleep(self.page_load_wait)
                logger.info("Navigated to Programs")
                return True

            # Fallback: direct URL navigation
            self.driver.get(f"{self.base_url}/programs")
            time.sleep(self.page_load_wait)
            return True

        except Exception as e:
            logger.error(f"Failed to navigate to Programs: {e}")
            return False

    def _navigate_to_program(self, program_name: str = None) -> bool:
        """
        Navigate into a specific program (e.g., '2026 Fall Core').

        Args:
            program_name: Program name to click into (defaults to config)
        """
        program_name = program_name or self.program_name
        logger.info(f"Navigating to program: {program_name}")

        try:
            # First get to Programs list
            if not self._navigate_to_programs():
                return False

            # Click on the specific program
            program_selectors = [
                (By.XPATH, f'//a[contains(text(), "{program_name}")]'),
                (By.XPATH, f'//*[contains(text(), "{program_name}")]'),
                (By.XPATH, f'//td[contains(text(), "{program_name}")]'),
                (By.XPATH, f'//div[contains(text(), "{program_name}")]'),
            ]

            if self.interactor.try_multiple_selectors(
                program_selectors, "click", timeout=10
            ):
                time.sleep(self.page_load_wait)
                logger.info(f"Opened program: {program_name}")
                return True

            logger.error(f"Could not find program: {program_name}")
            self._take_screenshot("pm_program_not_found")
            return False

        except Exception as e:
            logger.error(f"Failed to navigate to program: {e}")
            return False

    def _click_more_actions(self) -> bool:
        """Click the 'More Actions' dropdown button."""
        logger.info("Looking for More Actions button...")

        more_actions_selectors = [
            (By.XPATH, '//button[contains(text(), "More Actions")]'),
            (By.XPATH, '//button[contains(text(), "More actions")]'),
            (By.XPATH, '//span[contains(text(), "More Actions")]/..'),
            (By.CSS_SELECTOR, 'button[data-testid="more-actions"]'),
            (By.CSS_SELECTOR, '[aria-label="More Actions"]'),
            # Some PM UIs use a three-dot menu icon
            (By.CSS_SELECTOR, 'button[aria-label="more"]'),
            (By.XPATH, '//button[contains(@class, "more-actions")]'),
        ]

        if self.interactor.try_multiple_selectors(
            more_actions_selectors, "click", timeout=10
        ):
            time.sleep(1)  # wait for dropdown to render
            logger.info("Clicked More Actions")
            return True

        logger.error("Could not find More Actions button")
        self._take_screenshot("pm_more_actions_not_found")
        return False

    def _click_export_option(self, option_text: str) -> bool:
        """
        Click a specific export option from the More Actions dropdown.

        Args:
            option_text: Text of the menu item (e.g., 'Export Responses')
        """
        logger.info(f"Looking for export option: {option_text}")

        # Build selectors for the dropdown menu item
        option_selectors = [
            (By.XPATH, f'//a[contains(text(), "{option_text}")]'),
            (By.XPATH, f'//button[contains(text(), "{option_text}")]'),
            (By.XPATH, f'//li[contains(text(), "{option_text}")]'),
            (By.XPATH, f'//div[contains(text(), "{option_text}")]'),
            (By.XPATH, f'//span[contains(text(), "{option_text}")]/..'),
            (By.XPATH, f'//*[@role="menuitem"][contains(text(), "{option_text}")]'),
            (By.XPATH, f'//*[@role="menuitem"]//span[contains(text(), "{option_text}")]'),
        ]

        if self.interactor.try_multiple_selectors(
            option_selectors, "click", timeout=8
        ):
            logger.info(f"Clicked: {option_text}")
            return True

        logger.error(f"Could not find export option: {option_text}")
        self._take_screenshot(f"pm_export_{option_text.replace(' ', '_')}_not_found")
        return False

    # =========================================================
    #  DOWNLOAD HELPERS
    # =========================================================

    def _wait_for_download(self, patterns: List[str],
                           timeout: int = None) -> Optional[str]:
        """
        Wait for a CSV file to appear in the download directory.

        Args:
            patterns: Glob patterns to match (tried in order)
            timeout: Max seconds to wait

        Returns:
            Path to downloaded file, or None
        """
        timeout = timeout or self.download_timeout
        download_dir = Path(self.download_dir)

        # Record existing files before download
        existing = set()
        for pattern in patterns:
            existing.update(str(f) for f in download_dir.glob(pattern))

        logger.info(f"Waiting for download (timeout={timeout}s)...")

        start = time.time()
        while time.time() - start < timeout:
            # Check for partial downloads
            partials = list(download_dir.glob("*.crdownload")) + \
                       list(download_dir.glob("*.tmp"))
            if partials:
                time.sleep(1)
                continue

            # Look for new files matching our patterns
            for pattern in patterns:
                for f in download_dir.glob(pattern):
                    if str(f) not in existing:
                        logger.info(f"Download complete: {f.name}")
                        return str(f)

            time.sleep(1)

        # Timeout — log what's in the directory for debugging
        all_files = [f.name for f in download_dir.iterdir() if f.is_file()]
        logger.warning(f"Download timed out. Files in {download_dir}: {all_files}")
        return None

    def _find_latest_csv(self, patterns: List[str]) -> Optional[str]:
        """
        Find the most recently modified CSV matching any of the patterns.

        Args:
            patterns: Glob patterns to try

        Returns:
            Path to newest matching file, or None
        """
        download_dir = Path(self.download_dir)
        candidates = []

        for pattern in patterns:
            candidates.extend(download_dir.glob(pattern))

        if not candidates:
            return None

        latest = max(candidates, key=lambda f: f.stat().st_mtime)
        return str(latest)

    def _take_screenshot(self, name: str):
        """Take a debug screenshot."""
        try:
            if self.driver_manager:
                self.driver_manager.take_screenshot(f"{name}.png")
            elif self.driver:
                screenshot_dir = Path("logs/screenshots")
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = screenshot_dir / f"{name}_{ts}.png"
                self.driver.save_screenshot(str(path))
                logger.info(f"Screenshot: {path}")
        except Exception as e:
            logger.debug(f"Screenshot failed: {e}")

    # =========================================================
    #  EXPORT DOWNLOADERS
    # =========================================================

    def download_registration_responses(self) -> Optional[str]:
        """
        Download Export Responses CSV from Programs → [Program] → More Actions.

        This is the primary export — contains player info, package/division,
        parent contacts, volunteer interest, and all player question answers.

        Returns:
            Path to downloaded CSV, or None
        """
        logger.info("=== Downloading Registration Responses ===")

        try:
            if not self._navigate_to_program():
                return None

            if not self._click_more_actions():
                return None

            # Click Export Responses
            export_labels = ["Export Responses", "Export Player Responses"]
            for label in export_labels:
                if self._click_export_option(label):
                    break
            else:
                logger.error("Could not find Export Responses menu item")
                return None

            # Wait for download
            patterns = self.EXPORT_PATTERNS[
                PlayMetricsExportType.REGISTRATION_RESPONSES
            ]
            filepath = self._wait_for_download(patterns, timeout=self.download_timeout)

            if filepath:
                self.downloaded_files[
                    PlayMetricsExportType.REGISTRATION_RESPONSES
                ] = filepath
                logger.info(f"Registration responses saved: {filepath}")

            return filepath

        except Exception as e:
            logger.error(f"Failed to download registration responses: {e}")
            self._take_screenshot("pm_responses_error")
            return None

    def download_volunteers(self) -> Optional[str]:
        """
        Download Export Volunteers CSV from Programs → [Program] → More Actions.

        Returns:
            Path to downloaded CSV, or None
        """
        logger.info("=== Downloading Volunteers ===")

        try:
            if not self._navigate_to_program():
                return None

            if not self._click_more_actions():
                return None

            # Click Export Volunteers
            export_labels = ["Export Volunteers", "Export Volunteer Responses"]
            for label in export_labels:
                if self._click_export_option(label):
                    break
            else:
                logger.error("Could not find Export Volunteers menu item")
                return None

            # Wait for download
            patterns = self.EXPORT_PATTERNS[PlayMetricsExportType.VOLUNTEERS]
            filepath = self._wait_for_download(patterns, timeout=self.download_timeout)

            if filepath:
                self.downloaded_files[PlayMetricsExportType.VOLUNTEERS] = filepath
                logger.info(f"Volunteers saved: {filepath}")

            return filepath

        except Exception as e:
            logger.error(f"Failed to download volunteers: {e}")
            self._take_screenshot("pm_volunteers_error")
            return None

    def download_coaching_requests(self) -> Optional[str]:
        """
        Download Coaching Requests CSV from
        Programs → Leagues → [League] → Coaching Requests → More Actions → Export.

        This navigates a different path than the program-level exports.

        Returns:
            Path to downloaded CSV, or None
        """
        logger.info("=== Downloading Coaching Requests ===")

        try:
            # Navigate to Programs → Leagues
            if not self._navigate_to_programs():
                return None

            # Click into Leagues tab or section
            leagues_selectors = [
                (By.XPATH, '//a[contains(text(), "Leagues")]'),
                (By.XPATH, '//span[contains(text(), "Leagues")]'),
                (By.XPATH, '//button[contains(text(), "Leagues")]'),
                (By.XPATH, '//*[@role="tab"][contains(text(), "Leagues")]'),
                (By.CSS_SELECTOR, 'a[href*="/leagues"]'),
            ]
            if self.interactor.try_multiple_selectors(
                leagues_selectors, "click", timeout=10
            ):
                time.sleep(self.page_load_wait)
                logger.info("Navigated to Leagues")
            else:
                # Try direct URL
                self.driver.get(f"{self.base_url}/programs/leagues")
                time.sleep(self.page_load_wait)

            # Click into the specific league
            if self.league_name:
                league_selectors = [
                    (By.XPATH, f'//a[contains(text(), "{self.league_name}")]'),
                    (By.XPATH, f'//*[contains(text(), "{self.league_name}")]'),
                ]
                if self.interactor.try_multiple_selectors(
                    league_selectors, "click", timeout=8
                ):
                    time.sleep(self.page_load_wait)
                    logger.info(f"Opened league: {self.league_name}")
                else:
                    logger.warning(
                        f"Could not find league '{self.league_name}', "
                        "trying first available league"
                    )
                    # Click the first league link
                    first_league = [
                        (By.CSS_SELECTOR, 'table tbody tr:first-child a'),
                        (By.CSS_SELECTOR, '.league-list a:first-child'),
                    ]
                    self.interactor.try_multiple_selectors(
                        first_league, "click", timeout=5
                    )
                    time.sleep(self.page_load_wait)

            # Navigate to Coaching Requests tab/section within the league
            coaching_selectors = [
                (By.XPATH, '//a[contains(text(), "Coaching Requests")]'),
                (By.XPATH, '//span[contains(text(), "Coaching Requests")]'),
                (By.XPATH, '//button[contains(text(), "Coaching Requests")]'),
                (By.XPATH, '//*[@role="tab"][contains(text(), "Coaching")]'),
            ]
            if self.interactor.try_multiple_selectors(
                coaching_selectors, "click", timeout=8
            ):
                time.sleep(self.page_load_wait)
                logger.info("Navigated to Coaching Requests")

            # Click More Actions → Export
            if not self._click_more_actions():
                return None

            export_labels = ["Export", "Export Coaching Requests", "Export All"]
            for label in export_labels:
                if self._click_export_option(label):
                    break
            else:
                logger.error("Could not find coaching requests export option")
                return None

            # Wait for download
            patterns = self.EXPORT_PATTERNS[
                PlayMetricsExportType.COACHING_REQUESTS
            ]
            filepath = self._wait_for_download(patterns, timeout=self.download_timeout)

            if filepath:
                self.downloaded_files[
                    PlayMetricsExportType.COACHING_REQUESTS
                ] = filepath
                logger.info(f"Coaching requests saved: {filepath}")

            return filepath

        except Exception as e:
            logger.error(f"Failed to download coaching requests: {e}")
            self._take_screenshot("pm_coaching_error")
            return None

    # =========================================================
    #  ORCHESTRATION
    # =========================================================

    def download_all_enrollment_exports(self) -> Dict[str, Optional[str]]:
        """
        Download all three CSV exports needed for the Enrollment Summary Report.

        Returns:
            Dict mapping export type to file path (or None if failed)
        """
        logger.info("=" * 60)
        logger.info("PlayMetrics: Downloading all enrollment summary exports")
        logger.info("=" * 60)

        results = {}

        # 1. Registration Responses (the big one)
        results[PlayMetricsExportType.REGISTRATION_RESPONSES] = \
            self.download_registration_responses()

        # 2. Volunteers
        results[PlayMetricsExportType.VOLUNTEERS] = \
            self.download_volunteers()

        # 3. Coaching Requests
        results[PlayMetricsExportType.COACHING_REQUESTS] = \
            self.download_coaching_requests()

        # Summary
        succeeded = sum(1 for v in results.values() if v is not None)
        total = len(results)
        logger.info(f"Download results: {succeeded}/{total} exports succeeded")

        for export_type, filepath in results.items():
            status = filepath if filepath else "FAILED"
            logger.info(f"  {export_type}: {status}")

        return results

    def download_single_export(self, export_type: str) -> Optional[str]:
        """
        Download a single export by type.

        Args:
            export_type: One of PlayMetricsExportType constants

        Returns:
            Path to downloaded file, or None
        """
        dispatch = {
            PlayMetricsExportType.REGISTRATION_RESPONSES:
                self.download_registration_responses,
            PlayMetricsExportType.VOLUNTEERS:
                self.download_volunteers,
            PlayMetricsExportType.COACHING_REQUESTS:
                self.download_coaching_requests,
        }

        handler = dispatch.get(export_type)
        if not handler:
            logger.error(f"Unknown export type: {export_type}")
            return None

        return handler()

    # =========================================================
    #  STATUS / DIAGNOSTICS
    # =========================================================

    def check_existing_exports(self) -> Dict[str, Optional[str]]:
        """
        Check what export files already exist in the download directory.

        Returns:
            Dict mapping export type to latest file path (or None)
        """
        results = {}
        for export_type, patterns in self.EXPORT_PATTERNS.items():
            filepath = self._find_latest_csv(patterns)
            results[export_type] = filepath
        return results

    def get_download_summary(self) -> str:
        """Get a formatted summary of download status."""
        existing = self.check_existing_exports()

        lines = [
            "PlayMetrics Export Status",
            "=" * 50,
            f"Download directory: {self.download_dir}",
            "",
        ]

        for export_type, filepath in existing.items():
            if filepath:
                p = Path(filepath)
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                size_kb = p.stat().st_size / 1024
                lines.append(
                    f"  {export_type}: {p.name} "
                    f"({size_kb:.0f} KB, {mtime:%Y-%m-%d %H:%M})"
                )
            else:
                lines.append(f"  {export_type}: NOT FOUND")

        return "\n".join(lines)
