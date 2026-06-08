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
    """Export types available in PlayMetrics admin.

    Confirmed from More Actions dropdown menu on program detail page.
    Menu items are <div class="has-link" role="menuitem"> elements.
    """
    REGISTRATION_RESPONSES = "registration_responses"
    VOLUNTEERS = "volunteers"
    COACHING_REQUESTS = "coaching_requests"
    SUBSCRIPTIONS = "subscriptions"
    PAYMENTS = "payments"
    FINANCIAL_AID = "financial_aid"

    # Mapping of export type → exact menu item text in the dropdown
    MENU_LABELS = {
        "registration_responses": "Export Responses",
        "volunteers": "Export Volunteer Info",
        "subscriptions": "Export Subscriptions",
        "payments": "Export Payments",
        "financial_aid": "Export Financial Aid Requests",
    }

    # API download: direct HTTP instead of UI navigation
    API_BASE = "https://api.playmetrics.com"

    # Full API path templates per export type (discovered from DevTools)
    # {program_id} and {league_id} are replaced at runtime
    API_PATHS = {
        "waitlist":                {"path": "program_admin/programs/{program_id}/waitlists.csv"},
        "registration_responses":  {"path": "program_admin/programs/{program_id}/export.csv"},
        "volunteers":              {"path": "program_admin/programs/{program_id}/volunteers.csv"},
        "coaching_requests":       {"path": "club_admin/club_leagues/{league_id}/coach_requests/all-coaching-requests.csv"},
    }


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

    # Default PlayMetrics URL
    DEFAULT_BASE_URL = "https://playmetrics.com"

    # Standardized filenames for each export type.
    # Downloaded files are renamed to: {canonical_name}_{YYYYMMDD_HHMMSS}.csv
    # Up to MAX_HISTORY versions are kept; oldest are pruned automatically.
    CANONICAL_NAMES = {
        PlayMetricsExportType.REGISTRATION_RESPONSES: "registration-responses",
        PlayMetricsExportType.VOLUNTEERS: "volunteers",
        PlayMetricsExportType.COACHING_REQUESTS: "coaching-requests",
        PlayMetricsExportType.SUBSCRIPTIONS: "subscriptions",
        PlayMetricsExportType.PAYMENTS: "payments",
        PlayMetricsExportType.FINANCIAL_AID: "financial-aid",
        "packages": "packages",  # scraped, not downloaded
    }

    # Patterns to match raw downloads from PlayMetrics (before rename).
    # These catch whatever PM names the file, including Chrome's (n) duplicates.
    RAW_DOWNLOAD_PATTERNS = {
        PlayMetricsExportType.REGISTRATION_RESPONSES: [
            "registration-responses*.csv", "export*.csv", "*responses*.csv",
        ],
        PlayMetricsExportType.VOLUNTEERS: [
            "volunteers*.csv", "volunteer*.csv",
        ],
        PlayMetricsExportType.COACHING_REQUESTS: [
            "*coaching-requests*.csv", "*coaching_requests*.csv",
            "*coaching*.csv",
        ],
        PlayMetricsExportType.SUBSCRIPTIONS: [
            "subscriptions*.csv", "*subscription*.csv",
        ],
        PlayMetricsExportType.PAYMENTS: [
            "payments*.csv", "*payment*.csv",
        ],
        PlayMetricsExportType.FINANCIAL_AID: [
            "*financial*aid*.csv", "*financial*.csv",
        ],
    }

    # Max historical versions to keep per export type
    MAX_HISTORY = 5

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
        self.program_id = pm_config.get('program_id', '')
        self.league_name = pm_config.get('league_name', '')
        self.league_id = pm_config.get('league_id', '')

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

        # Persistent Chrome profile for MFA device trust
        # After first-run setup (--pm-setup), the device stays "known"
        # and subsequent runs skip the SMS challenge.
        self.chrome_profile_dir = pm_config.get(
            'chrome_profile_dir',
            str(Path('data/pm_chrome_profile').absolute())
        )

        # Setup mode flag — set externally before initialize()
        self.setup_mode = False

        # Download tracking
        self.downloaded_files: Dict[str, str] = {}

    # =========================================================
    #  LIFECYCLE
    # =========================================================

    def initialize(self, setup_mode: bool = False):
        """
        Create WebDriver if we don't have one (standalone mode).

        Args:
            setup_mode: If True, forces non-headless mode for first-run
                        MFA setup (user enters SMS code manually).
        """
        self.setup_mode = setup_mode

        if self.driver is not None:
            # Using shared driver — just set up interactor
            from core.element_interactor import ElementInteractor
            self.interactor = ElementInteractor(self.driver)
            self.wait = WebDriverWait(self.driver, 15)
            return

        # Standalone mode — create driver with persistent profile
        headless = False if setup_mode else (
            self.config.get('headless_mode', False) if self.config else False
        )

        self._create_driver_with_profile(headless)

        from core.element_interactor import ElementInteractor
        self.interactor = ElementInteractor(self.driver)
        self.wait = WebDriverWait(self.driver, 15)

        mode_str = "SETUP (non-headless)" if setup_mode else "normal"
        logger.info(
            f"PlayMetrics Download Manager initialized "
            f"({mode_str}, profile: {self.chrome_profile_dir})"
        )

    def _create_driver_with_profile(self, headless: bool = False):
        """
        Create a Chrome WebDriver with a persistent user data directory.

        This preserves cookies, local storage, and device trust between
        runs so that PlayMetrics' SMS MFA challenge is only triggered once.
        """
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        # Ensure profile directory exists
        Path(self.chrome_profile_dir).mkdir(parents=True, exist_ok=True)

        options = Options()

        # Persistent profile — key to keeping device "known"
        options.add_argument(f'--user-data-dir={self.chrome_profile_dir}')

        # Download directory
        prefs = {
            "download.default_directory": str(Path(self.download_dir).absolute()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "safebrowsing.disable_download_protection": True,
            "profile.default_content_settings.popups": 0,
            "profile.default_content_setting_values.automatic_downloads": 1,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        options.add_experimental_option("prefs", prefs)

        if headless:
            options.add_argument("--headless")
            options.add_argument("--window-size=1920,1080")

        # Stability options
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--disable-extensions")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")

        # User agent
        options.add_argument(
            'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )

        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
        except Exception:
            service = Service()  # hope chromedriver is on PATH

        self.driver = webdriver.Chrome(service=service, options=options)
        if not headless:
            self.driver.maximize_window()

        # Store a reference for cleanup
        self._owns_chrome = True
        logger.info(f"Chrome started with persistent profile: {self.chrome_profile_dir}")

    def cleanup(self):
        """Clean up driver if we own it."""
        if self.owns_driver and self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.debug(f"Driver cleanup error: {e}")
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
        Log into PlayMetrics.

        Navigates directly to playmetrics.com/login (skips landing page
        Sign In button which opens a new tab).

        With a persistent Chrome profile, the session may still be active
        from a previous run. In that case, navigating to /login redirects
        straight to the dashboard — no credentials needed.

        Returns:
            True if login succeeded
        """
        logger.info("Logging into PlayMetrics...")

        try:
            # Navigate to login page
            login_url = f"{self.base_url}/login"
            logger.info(f"Navigating to: {login_url}")
            self.driver.get(login_url)
            time.sleep(self.page_load_wait)

            # ── Check if already logged in ──
            # If the persistent profile has a valid session, /login
            # redirects to the dashboard or programs page.
            current_url = self.driver.current_url
            if "login" not in current_url.lower():
                logger.info(
                    f"Already authenticated (redirected to {current_url})"
                )
                self.logged_in = True
                self._init_api_session()
                return True

            # Also check if login form is actually present
            # (page might be /login but session is valid and Vue hasn't
            # redirected yet)
            try:
                self.driver.find_element(By.ID, 'username')
                logger.info("Login form detected — entering credentials")
            except NoSuchElementException:
                # No login form found — might be loading or already auth'd
                time.sleep(3)
                current_url = self.driver.current_url
                if "login" not in current_url.lower():
                    logger.info(
                        f"Already authenticated after wait "
                        f"(redirected to {current_url})"
                    )
                    self.logged_in = True
                    self._init_api_session()
                    return True
                # Still on login page but no form — unexpected
                logger.warning("On login page but no form found, proceeding...")

            # ── Credentials form ──
            username, password = self._load_credentials()
            # Email field — confirmed element:
            # <input id="username" class="input is-medium"
            #        type="email" placeholder="Email" autocomplete="username">
            email_selectors = [
                (By.ID, 'username'),
                (By.CSS_SELECTOR, 'input#username'),
                (By.CSS_SELECTOR, 'input[type="email"][autocomplete="username"]'),
                (By.CSS_SELECTOR, 'input.input.is-medium[type="email"]'),
                (By.XPATH, '//input[@placeholder="Email"]'),
            ]
            if not self.interactor.try_multiple_selectors(
                email_selectors, "send_keys", text=username, timeout=10
            ):
                raise Exception("Could not find email/username field")
            logger.info("Entered email")

            # Password field — confirmed element:
            # <input id="password" class="input is-medium"
            #        type="password" placeholder="Password"
            #        autocomplete="current-password">
            password_selectors = [
                (By.ID, 'password'),
                (By.CSS_SELECTOR, 'input#password'),
                (By.CSS_SELECTOR, 'input[type="password"]'),
                (By.CSS_SELECTOR, 'input.input.is-medium[type="password"]'),
                (By.XPATH, '//input[@placeholder="Password"]'),
                (By.CSS_SELECTOR, 'input[autocomplete="current-password"]'),
            ]
            if not self.interactor.try_multiple_selectors(
                password_selectors, "send_keys", text=password, timeout=5
            ):
                raise Exception("Could not find password field")
            logger.info("Entered password")

            # Submit / Log In button — confirmed element:
            # <button id="submit" class="button is-primary is-medium
            #   is-fullwidth" type="submit" disabled=""> Login </button>
            # Note: button starts disabled, enables after fields are filled.
            # try_multiple_selectors waits for "clickable" which checks is_enabled().
            login_btn_selectors = [
                (By.ID, 'submit'),
                (By.CSS_SELECTOR, 'button#submit'),
                (By.CSS_SELECTOR, 'button.button.is-primary.is-fullwidth'),
                (By.XPATH, '//button[contains(text(), "Login")]'),
                (By.CSS_SELECTOR, 'button[type="submit"]'),
            ]
            if not self.interactor.try_multiple_selectors(
                login_btn_selectors, "click", timeout=5
            ):
                raise Exception("Could not find login/submit button")
            logger.info("Clicked login button")

            # Wait for post-login page
            time.sleep(self.page_load_wait)

            # Check if MFA/SMS challenge appeared
            if self._is_mfa_page():
                if self.setup_mode:
                    # Setup mode — wait for user to enter SMS code manually
                    logger.info("=" * 50)
                    logger.info("MFA CHALLENGE DETECTED")
                    logger.info("Enter the SMS code in the browser window.")
                    logger.info("The browser will wait for you to complete it.")
                    logger.info("=" * 50)
                    print("\n>>> MFA code sent to your phone.")
                    print(">>> Enter the code in the browser window,")
                    print(">>> then press Enter here when done...")
                    input()  # Pause for user
                    time.sleep(3)  # Wait for post-MFA redirect
                else:
                    # Not in setup mode — persistent profile should have
                    # bypassed MFA. If we're here, the profile is stale.
                    logger.error(
                        "MFA challenge appeared but not in setup mode. "
                        "Run --pm-setup first to establish device trust."
                    )
                    self._take_screenshot("pm_mfa_unexpected")
                    return False

            # Verify login succeeded
            current_url = self.driver.current_url
            if "login" in current_url.lower():
                self._take_screenshot("pm_login_failed")
                raise Exception("Still on login page after submit")

            self.logged_in = True
            logger.info("PlayMetrics login successful")

            # Initialize API session for direct downloads
            self._init_api_session()

            return True

        except Exception as e:
            logger.error(f"PlayMetrics login failed: {e}")
            self._take_screenshot("pm_login_error")
            return False

    def _is_mfa_page(self) -> bool:
        """Check if the current page is an MFA/SMS code challenge."""
        mfa_indicators = [
            (By.XPATH, '//*[contains(text(), "verification code")]'),
            (By.XPATH, '//*[contains(text(), "Verification Code")]'),
            (By.XPATH, '//*[contains(text(), "code sent")]'),
            (By.XPATH, '//*[contains(text(), "Enter code")]'),
            (By.XPATH, '//*[contains(text(), "enter the code")]'),
            (By.XPATH, '//*[contains(text(), "SMS")]'),
            (By.XPATH, '//*[contains(text(), "two-factor")]'),
            (By.XPATH, '//*[contains(text(), "2-step")]'),
            (By.CSS_SELECTOR, 'input[name="code"]'),
            (By.CSS_SELECTOR, 'input[autocomplete="one-time-code"]'),
        ]
        for by, selector in mfa_indicators:
            try:
                self.driver.find_element(by, selector)
                logger.info(f"MFA indicator found: {selector}")
                return True
            except NoSuchElementException:
                continue
        return False

    def setup_first_run(self) -> bool:
        """
        First-run setup: login with manual MFA code entry.

        Runs in non-headless mode so the user can see the browser
        and enter the SMS verification code. After completion, the
        persistent Chrome profile stores device trust so subsequent
        runs with --pm-download skip the MFA challenge.

        Returns:
            True if setup completed successfully
        """
        logger.info("=" * 60)
        logger.info("PlayMetrics First-Run Setup")
        logger.info("This will open a browser for you to complete")
        logger.info("the SMS verification. Subsequent runs will be")
        logger.info("unattended using the saved device trust.")
        logger.info("=" * 60)

        self.initialize(setup_mode=True)

        if not self.login():
            logger.error("Setup login failed")
            return False

        # Verify we can reach the programs page
        if self._navigate_to_programs():
            logger.info("=" * 60)
            logger.info("SETUP COMPLETE")
            logger.info(f"Device trust saved to: {self.chrome_profile_dir}")
            logger.info("You can now run --pm-download unattended.")
            logger.info("=" * 60)
            return True
        else:
            logger.error("Setup succeeded at login but failed to reach Programs")
            return False

    # =========================================================
    #  API DOWNLOAD (Firebase JWT + direct HTTP)
    # =========================================================

    def _init_api_session(self) -> bool:
        """Extract Firebase JWT from an export link for direct API downloads.
        
        Navigates to the program page, clicks More Actions, and extracts
        the fbt (Firebase JWT) and access_key from an export link's href.
        These are the same tokens the UI uses for downloads.
        """
        try:
            import requests as req
            self._firebase_jwt = None
            self._access_key = None

            # Navigate to program detail page
            logger.info("API session: extracting JWT from export link...")
            if not self.program_id:
                logger.warning("API session: no program_id configured")
                self._api_session = None
                return False

            self.driver.get(
                f"{self.base_url}/program-admin/programs/{self.program_id}/details"
            )
            time.sleep(self.page_load_wait)

            # Click More Actions to reveal export links
            more_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((
                    By.XPATH, '//span[text()="More Actions"]'
                ))
            )
            more_btn.click()
            time.sleep(1)

            # Some export links have API URLs directly in their href
            # (e.g., Export Volunteer Info). Check those first.
            links = self.driver.find_elements(
                By.CSS_SELECTOR, 'a[href*="api.playmetrics.com"]'
            )

            if not links:
                # Others require clicking to get an intermediary page
                # (e.g., Export Responses). Click the first export option.
                logger.info("API session: clicking export to reach intermediary page...")
                export_items = self.driver.find_elements(
                    By.XPATH,
                    '//div[@role="menuitem"]//a[contains(text(), "Export")]'
                )
                if export_items:
                    export_items[0].click()
                    time.sleep(3)
                    links = self.driver.find_elements(
                        By.CSS_SELECTOR, 'a[href*="api.playmetrics.com"]'
                    )

            # Extract fbt and access_key from the first matching link
            for link in links:
                href = link.get_attribute('href') or ''
                if 'fbt=' in href:
                    from urllib.parse import urlparse, parse_qs
                    params = parse_qs(urlparse(href).query)
                    jwt_list = params.get('fbt', [])
                    if jwt_list:
                        self._firebase_jwt = jwt_list[0]
                        access_keys = params.get('access_key', [])
                        self._access_key = access_keys[0] if access_keys else None
                        break

            if not self._firebase_jwt:
                logger.warning("API session: could not extract JWT from any export link")
                self._api_session = None
                return False

            # Set up requests session with browser cookies
            self._api_session = req.Session()
            cookies = {c['name']: c['value'] for c in self.driver.get_cookies()}
            self._api_session.cookies.update(cookies)
            user_agent = self.driver.execute_script("return navigator.userAgent")
            self._api_session.headers.update({
                'User-Agent': user_agent,
                'Referer': 'https://playmetrics.com/',
            })

            jwt_preview = self._firebase_jwt[:20] + '...' if self._firebase_jwt else 'none'
            logger.info(f"API session initialized — JWT: {jwt_preview}, access_key: {'yes' if self._access_key else 'no'}")
            return True

        except Exception as e:
            logger.warning(f"API session init failed: {e}")
            import traceback
            traceback.print_exc()
            self._api_session = None
            return False

    def _try_api_download(self, export_type: str) -> Optional[str]:
        """Try to download an export via the API. Returns filepath or None.

        Falls through silently if:
          - API session not initialized
          - No API path registered for this export type
          - HTTP request fails

        The caller should fall back to the Selenium UI approach if this returns None.
        """
        if not getattr(self, '_api_session', None) or not getattr(self, '_firebase_jwt', None):
            return None

        endpoint = PlayMetricsExportType.API_PATHS.get(export_type)
        if not endpoint:
            return None  # no API path registered — use Selenium

        path_template = endpoint['path'] if isinstance(endpoint, dict) else endpoint
        api_path = path_template.replace('{program_id}', self.program_id).replace('{league_id}', self.league_id)
        url = f"{PlayMetricsExportType.API_BASE}/{api_path}"
        params = {'fbt': self._firebase_jwt}
        if getattr(self, '_access_key', None):
            params['access_key'] = self._access_key

        logger.info(f"API download: {export_type} via {url[:80]}...")

        try:
            import requests as req
            resp = self._api_session.get(url, params=params, timeout=60, allow_redirects=True)

            if resp.status_code == 200 and resp.content and len(resp.content) > 10:
                # Save with canonical name + timestamp
                canonical = self.CANONICAL_NAMES.get(export_type, export_type)
                from datetime import datetime as dt
                timestamp = dt.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{canonical}_{timestamp}.csv"
                filepath = os.path.join(self.download_dir, filename)

                with open(filepath, 'wb') as f:
                    f.write(resp.content)

                size_kb = len(resp.content) / 1024
                logger.info(f"API download OK: {filename} ({size_kb:.1f} KB)")

                # Prune old versions
                self._prune_history(Path(self.download_dir), canonical)
                return filepath
            else:
                logger.warning(f"API download failed: HTTP {resp.status_code} ({len(resp.content)} bytes)")
                return None

        except Exception as e:
            logger.warning(f"API download error: {e}")
            return None

    # =========================================================
    #  NAVIGATION
    # =========================================================

    def _navigate_to_programs(self) -> bool:
        """Navigate to the Programs list page."""
        logger.info("Navigating to Programs...")
        try:
            # Direct URL navigation (confirmed pattern)
            programs_url = f"{self.base_url}/program-admin/programs"
            self.driver.get(programs_url)
            time.sleep(self.page_load_wait)
            logger.info(f"Navigated to Programs: {programs_url}")
            return True

        except Exception as e:
            logger.error(f"Failed to navigate to Programs: {e}")
            return False

    def _navigate_to_program(self, program_name: str = None) -> bool:
        """
        Navigate into a specific program (e.g., '2026 Fall Core').

        Uses direct URL if program_id is configured (preferred),
        otherwise navigates via Programs list and clicks the program card.

        Args:
            program_name: Program name to click into (defaults to config)
        """
        program_name = program_name or self.program_name

        # Strategy 1: Direct URL with program_id (preferred — confirmed pattern)
        # URL format: /program-admin/programs/{id}/details
        if self.program_id:
            program_url = (
                f"{self.base_url}/program-admin/programs/"
                f"{self.program_id}/details"
            )
            logger.info(f"Navigating directly to program: {program_url}")
            self.driver.get(program_url)
            time.sleep(self.page_load_wait)

            # Verify we landed on the program page
            current_url = self.driver.current_url
            if str(self.program_id) in current_url:
                logger.info(f"Opened program: {program_name} (ID: {self.program_id})")
                return True
            else:
                logger.warning(
                    f"Direct navigation may have failed. "
                    f"Expected program ID {self.program_id} in URL, got: {current_url}"
                )
                # Fall through to Strategy 2

        # Strategy 2: Navigate via Programs list and click the program card
        logger.info(f"Navigating to program via list: {program_name}")
        if not self._navigate_to_programs():
            return False

        # Click on the program card — PM uses Vue base-card components
        program_selectors = [
            (By.XPATH, f'//h5[contains(text(), "{program_name}")]'),
            (By.XPATH, f'//*[contains(@class, "base-header-text")][contains(text(), "{program_name}")]'),
            (By.XPATH, f'//a[contains(text(), "{program_name}")]'),
            (By.XPATH, f'//*[contains(text(), "{program_name}")]'),
        ]

        if self.interactor.try_multiple_selectors(
            program_selectors, "click", timeout=10
        ):
            time.sleep(self.page_load_wait)

            # Verify navigation happened (Vue Router may take a moment)
            time.sleep(2)
            current_url = self.driver.current_url
            if "/details" in current_url or "/programs/" in current_url:
                logger.info(f"Opened program: {program_name}")
                return True

        logger.error(f"Could not navigate to program: {program_name}")
        self._take_screenshot("pm_program_not_found")
        return False

    def _click_more_actions(self) -> bool:
        """Click the 'More Actions' dropdown button on program detail page."""
        logger.info("Looking for More Actions button...")

        # Confirmed DOM: <span data-v-fbbb3f3c="">More Actions</span>
        # The span is inside a button/link that triggers a Bulma dropdown
        more_actions_selectors = [
            (By.XPATH, '//span[text()="More Actions"]'),
            (By.XPATH, '//span[contains(text(), "More Actions")]'),
            (By.XPATH, '//span[contains(text(), "More Actions")]/..'),
            (By.XPATH, '//button[.//span[contains(text(), "More Actions")]]'),
            (By.XPATH, '//*[contains(text(), "More Actions")]'),
        ]

        if self.interactor.try_multiple_selectors(
            more_actions_selectors, "click", timeout=10
        ):
            time.sleep(1.5)  # wait for Bulma dropdown to render
            logger.info("Clicked More Actions")
            return True

        logger.error("Could not find More Actions button")
        self._take_screenshot("pm_more_actions_not_found")
        return False

    def _click_export_option(self, option_text: str) -> bool:
        """
        Click a specific export option from the More Actions dropdown.

        The dropdown uses Bulma dropdown-content with role="menu".
        Each item is: div.has-link[role="menuitem"] > a.has-text-link > "text"

        Args:
            option_text: Exact text of the menu item
                         (e.g., 'Export Responses', 'Export Volunteer Info')
        """
        logger.info(f"Looking for export option: {option_text}")

        # Confirmed DOM structure:
        # <div class="has-link" role="menuitem">
        #   <a class="has-text-link">... Export Responses</a>
        # </div>
        option_selectors = [
            (By.XPATH,
             f'//div[@role="menuitem"]//a[contains(text(), "{option_text}")]'),
            (By.XPATH,
             f'//*[@role="menu"]//a[contains(text(), "{option_text}")]'),
            (By.XPATH,
             f'//div[contains(@class, "dropdown-content")]'
             f'//a[contains(text(), "{option_text}")]'),
            (By.XPATH, f'//a[contains(text(), "{option_text}")]'),
        ]

        for by, selector in option_selectors:
            try:
                element = WebDriverWait(self.driver, 8).until(
                    EC.element_to_be_clickable((by, selector))
                )
                # Discover API URL from the element's href before clicking
                href = element.get_attribute('href') or ''
                if 'api.playmetrics.com' in href:
                    from urllib.parse import urlparse
                    segments = [s for s in urlparse(href).path.split('/') if s]
                    if segments:
                        api_file = segments[-1]
                        logger.info(f"*** DISCOVERED API PATH: {api_file} ***")
                        logger.info(f"    Add to API_PATHS: \"{api_file.replace('.csv', '')}\": \"{api_file}\"")
                element.click()
                logger.info(f"Clicked: {option_text}")
                return True
            except (TimeoutException, Exception):
                continue

        logger.error(f"Could not find export option: {option_text}")
        self._take_screenshot(f"pm_export_{option_text.replace(' ', '_')}_not_found")
        return False

    def _click_download_csv(self) -> bool:
        """
        Handle the export intermediary page if one appears.

        Some exports (Export Responses, Export Coaching Requests) show an
        intermediary page with a download button after clicking the menu item.
        Others (Export Volunteer Info) download directly via an API href.

        This method checks if an intermediary page appeared and clicks
        the download button if so. If no intermediary page is found
        (direct download already started), returns True immediately.

        Confirmed intermediary page element:
          <a class="button is-primary" target="_blank"
             href="https://api.playmetrics.com/...export.csv?...">
             Download as .CSV
          </a>

        Since target="_blank" opens a new tab (complicates Selenium),
        we extract the href and navigate to it directly instead.

        Returns:
            True if download was triggered or no intermediary page found
        """
        logger.info("Checking for export intermediary page...")

        # Wait briefly for page transition
        time.sleep(2)

        # Check if the current page has a "Download as .CSV" button
        download_selectors = [
            (By.XPATH,
             '//a[contains(@class, "is-primary")]'
             '[contains(text(), "Download")]'),
            (By.XPATH, '//a[contains(text(), "Download as .CSV")]'),
            (By.XPATH, '//a[contains(text(), "Download as")]'),
            (By.CSS_SELECTOR, 'a.button.is-primary[href*=".csv"]'),
            (By.CSS_SELECTOR, 'a[href*="export.csv"]'),
            (By.CSS_SELECTOR, 'a[href*="api.playmetrics.com"][class*="primary"]'),
        ]

        # Try to find the element and extract its href
        for by, selector in download_selectors:
            try:
                element = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((by, selector))
                )
                href = element.get_attribute('href')
                if href and ('api.playmetrics.com' in href or '.csv' in href):
                    # Log the discovered API path for future direct downloads
                    if 'api.playmetrics.com' in href:
                        from urllib.parse import urlparse
                        parsed = urlparse(href)
                        full_path = parsed.path.lstrip('/')
                        segments = [s for s in parsed.path.split('/') if s]
                        if segments:
                            api_file = segments[-1]
                            logger.info(f"*** DISCOVERED API PATH: {api_file} ***")
                            logger.info(f"    Full path: {full_path}")
                    # Navigate directly to the href instead of clicking
                    # (avoids target="_blank" new tab issue)
                    logger.info("Found intermediary page — downloading via direct URL")
                    self.driver.get(href)
                    return True
            except TimeoutException:
                continue
            except Exception:
                continue

        # No intermediary page found — download may have started directly
        # (e.g., Export Volunteer Info has a direct API href on the menu item)
        logger.info("No intermediary page detected — download may be direct")
        return True

    # =========================================================
    #  DOWNLOAD HELPERS
    # =========================================================

    def _wait_for_download(self, export_type: str,
                           timeout: int = None) -> Optional[str]:
        """
        Wait for a CSV download to complete, then rename to standard format.

        Watches the download directory for new files matching the raw
        download patterns, renames to {canonical_name}_{timestamp}.csv,
        removes any Chrome (n) duplicates, and prunes old versions.

        Args:
            export_type: PlayMetricsExportType constant
            timeout: Max seconds to wait

        Returns:
            Path to renamed file, or None
        """
        timeout = timeout or self.download_timeout
        download_dir = Path(self.download_dir)
        patterns = self.RAW_DOWNLOAD_PATTERNS.get(export_type, ["*.csv"])

        # Record existing files before download
        existing = set()
        for pattern in patterns:
            existing.update(str(f) for f in download_dir.glob(pattern))
        # Also track all CSVs to catch unexpected filenames
        all_existing_csvs = set(str(f) for f in download_dir.glob("*.csv"))

        logger.info(f"Waiting for download (timeout={timeout}s)...")

        start = time.time()
        new_file = None
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
                        new_file = f
                        break
                if new_file:
                    break

            # Fallback: check for any new CSV
            if not new_file:
                for f in download_dir.glob("*.csv"):
                    if str(f) not in all_existing_csvs:
                        new_file = f
                        break

            if new_file:
                break

            time.sleep(1)

        if not new_file:
            all_files = [f.name for f in download_dir.iterdir() if f.is_file()]
            logger.warning(
                f"Download timed out. Files in {download_dir}: {all_files}"
            )
            return None

        logger.info(f"Download complete: {new_file.name}")

        # Rename to standardized name with timestamp
        renamed = self._rename_and_archive(new_file, export_type)
        return renamed

    def _rename_and_archive(self, raw_file: Path,
                            export_type: str) -> str:
        """
        Rename a raw download to standardized format and manage history.

        Renames: whatever_pm_named_it.csv → {canonical}_{YYYYMMDD_HHMMSS}.csv
        Removes any Chrome "(n)" duplicate files.
        Prunes history to keep only MAX_HISTORY versions.

        Args:
            raw_file: Path to the raw downloaded file
            export_type: PlayMetricsExportType constant

        Returns:
            Path to the renamed file
        """
        download_dir = Path(self.download_dir)
        canonical = self.CANONICAL_NAMES.get(export_type, "export")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"{canonical}_{timestamp}.csv"
        new_path = download_dir / new_name

        # Rename the downloaded file
        import shutil
        shutil.move(str(raw_file), str(new_path))
        logger.info(f"Renamed: {raw_file.name} → {new_name}")

        # Clean up any Chrome "(n)" duplicates for this export type
        self._cleanup_chrome_duplicates(download_dir, canonical)

        # Prune old versions
        self._prune_history(download_dir, canonical)

        return str(new_path)

    def _cleanup_chrome_duplicates(self, download_dir: Path,
                                    canonical: str):
        """
        Remove Chrome's automatic "(n)" duplicate files.

        Chrome creates files like "volunteers (1).csv" when the filename
        already exists. These are noise — remove them.
        """
        import re
        pattern = re.compile(
            rf'^{re.escape(canonical)}.*\(\d+\)\.csv$', re.IGNORECASE
        )
        for f in download_dir.iterdir():
            if f.is_file() and pattern.match(f.name):
                f.unlink()
                logger.info(f"Removed Chrome duplicate: {f.name}")

        # Also clean any raw downloads that match broader patterns
        # (files without our timestamp format)
        ts_pattern = re.compile(
            rf'^{re.escape(canonical)}_\d{{8}}_\d{{6}}\.csv$'
        )
        raw_patterns = self.RAW_DOWNLOAD_PATTERNS.get(
            # Find the export type for this canonical name
            next((k for k, v in self.CANONICAL_NAMES.items()
                  if v == canonical), ''),
            []
        )
        for rp in raw_patterns:
            for f in download_dir.glob(rp):
                if not ts_pattern.match(f.name):
                    f.unlink()
                    logger.info(f"Removed raw download: {f.name}")

    def _prune_history(self, download_dir: Path, canonical: str):
        """
        Keep only the MAX_HISTORY most recent versions of an export.

        Matches files named {canonical}_{YYYYMMDD_HHMMSS}.csv
        and removes the oldest beyond the limit.
        """
        import re
        ts_pattern = re.compile(
            rf'^{re.escape(canonical)}_(\d{{8}}_\d{{6}})\.csv$'
        )

        # Find all timestamped versions
        versions = []
        for f in download_dir.iterdir():
            if f.is_file():
                m = ts_pattern.match(f.name)
                if m:
                    versions.append(f)

        # Sort newest first
        versions.sort(key=lambda f: f.name, reverse=True)

        # Remove excess
        for old_file in versions[self.MAX_HISTORY:]:
            old_file.unlink()
            logger.info(f"Pruned old export: {old_file.name}")

        if len(versions) > self.MAX_HISTORY:
            logger.info(
                f"Kept {self.MAX_HISTORY} of {len(versions)} "
                f"versions for {canonical}"
            )

    def find_latest_export(self, export_type: str) -> Optional[str]:
        """
        Find the most recent timestamped export file for a given type.

        This is the method the Enrollment Summary Report should use
        to locate its input files.

        Args:
            export_type: PlayMetricsExportType constant

        Returns:
            Path to newest file, or None
        """
        download_dir = Path(self.download_dir)
        canonical = self.CANONICAL_NAMES.get(export_type, "")
        if not canonical:
            return None

        import re
        ts_pattern = re.compile(
            rf'^{re.escape(canonical)}_(\d{{8}}_\d{{6}})\.csv$'
        )

        candidates = [
            f for f in download_dir.iterdir()
            if f.is_file() and ts_pattern.match(f.name)
        ]

        if not candidates:
            return None

        latest = max(candidates, key=lambda f: f.name)
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

        # Try API download first (no UI navigation needed)
        api_result = self._try_api_download(PlayMetricsExportType.REGISTRATION_RESPONSES)
        if api_result:
            return api_result

        try:
            if not self._navigate_to_program():
                return None

            if not self._click_more_actions():
                return None

            # Click Export Responses (confirmed menu item text)
            if not self._click_export_option("Export Responses"):
                logger.error("Could not find Export Responses menu item")
                return None

            # Handle intermediary export page → Download as .CSV button
            if not self._click_download_csv():
                logger.error("Could not trigger CSV download")
                return None

            # Wait for download, rename, and archive
            filepath = self._wait_for_download(
                PlayMetricsExportType.REGISTRATION_RESPONSES,
                timeout=self.download_timeout
            )

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

    """
    Waitlist download method for playmetrics_download_manager.py
    ============================================================
 
    Hybrid approach: uses Selenium to navigate and open the export dialog,
    then extracts the direct API URL from the download button's href and
    downloads via requests — faster and more reliable than browser downloads.
 
    API URL pattern:
      https://api.playmetrics.com/program_admin/programs/{id}/waitlists.csv
        ?access_key=...&fbt={firebase_jwt}
 
    Output: waitlist_{timestamp}.csv in data/playmetrics/
    """
 
 
    def download_waitlist(self):
        """Download waitlist CSV from PlayMetrics via API URL extraction.
 
        Flow:
          1. Navigate to waitlist page
          2. Click "More Actions" dropdown
          3. Click "Export Waitlist Responses"
          4. Extract the API URL from the "Download as .CSV" button href
          5. Download CSV via requests (not browser)
        """
        logger.info("=== Downloading Waitlist ===")

        # Try API download first
        api_result = self._try_api_download("waitlist")
        if api_result:
            return api_result

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        import time
        import requests as req
 
        program_id = self.program_id  # 101848
        url = f"https://playmetrics.com/program-admin/programs/{program_id}/waitlist"
 
        logger.info(f"Navigating to waitlist page: {url}")
        self.driver.get(url)
        time.sleep(3)
 
        try:
            # Step 1: Click "More Actions" dropdown
            more_actions = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//span[contains(text(), 'More Actions')]"
                    "/ancestor::*[contains(@class, 'dropdown') or contains(@class, 'button')]"
                ))
            )
            more_actions.click()
            logger.info("Clicked 'More Actions'")
            time.sleep(1)
 
            # Step 2: Click "Export Waitlist Responses" from the dropdown menu
            export_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//div[@role='menuitem']//a[contains(@class, 'has-text-link')]"
                    "[contains(., 'Export Waitlist')]"
                ))
            )
            export_btn.click()
            logger.info("Clicked 'Export Waitlist Responses'")
            time.sleep(2)
 
            # Step 3: Extract the API URL from the download button
            download_btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//a[contains(@class, 'button') and contains(@class, 'is-primary')]"
                    "[contains(., 'Download') or contains(., '.CSV')]"
                ))
            )
            api_url = download_btn.get_attribute('href')
 
            if not api_url or 'api.playmetrics.com' not in api_url:
                logger.error(f"Unexpected download URL: {api_url}")
                # Fallback: click the button and wait for browser download
                before = set(os.listdir(self.download_dir))
                download_btn.click()
                downloaded = self._wait_for_download(before, timeout=30)
                if downloaded:
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    new_path = os.path.join(self.download_dir, f"waitlist_{timestamp}.csv")
                    os.rename(downloaded, new_path)
                    logger.info(f"Waitlist saved (browser fallback): {new_path}")
                    return new_path
                return None
 
            logger.info(f"Extracted API URL: {api_url[:80]}...")
 
            # Step 4: Download via requests using browser cookies
            cookies = {c['name']: c['value'] for c in self.driver.get_cookies()}
            user_agent = self.driver.execute_script("return navigator.userAgent")
 
            session = req.Session()
            session.cookies.update(cookies)
            session.headers.update({
                'User-Agent': user_agent,
                'Referer': 'https://playmetrics.com/',
            })
 
            resp = session.get(api_url, timeout=30, allow_redirects=True)
 
            if resp.status_code == 200 and resp.content:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                new_path = os.path.join(self.download_dir, f"waitlist_{timestamp}.csv")
                with open(new_path, 'wb') as f:
                    f.write(resp.content)
                logger.info(f"Waitlist saved (API): {new_path} ({len(resp.content)} bytes)")
                return new_path
            else:
                logger.error(f"API download failed: HTTP {resp.status_code}")
                return None
 
        except Exception as e:
            logger.error(f"Failed to download waitlist: {e}")
            import traceback
            traceback.print_exc()
            return None

    def download_volunteers(self) -> Optional[str]:
        """
        Download Export Volunteers CSV from Programs → [Program] → More Actions.

        Returns:
            Path to downloaded CSV, or None
        """
        logger.info("=== Downloading Volunteers ===")

        # Try API download first
        api_result = self._try_api_download(PlayMetricsExportType.VOLUNTEERS)
        if api_result:
            return api_result

        try:
            if not self._navigate_to_program():
                return None

            if not self._click_more_actions():
                return None

            # Click Export Volunteer Info (confirmed menu item text)
            # This export downloads directly via API href — no intermediary page.
            if not self._click_export_option("Export Volunteer Info"):
                logger.error("Could not find Export Volunteer Info menu item")
                return None

            # Wait for download, rename, and archive
            filepath = self._wait_for_download(
                PlayMetricsExportType.VOLUNTEERS,
                timeout=self.download_timeout
            )

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
        Download Coaching Requests CSV.

        Confirmed navigation path:
          Direct URL: /club-admin/leagues/{league_id}/Coaching%20Requests
          Then: More Actions → Export Coaching Requests

        Note: This is under /club-admin/leagues/, NOT /program-admin/programs/.

        Returns:
            Path to downloaded CSV, or None
        """
        logger.info("=== Downloading Coaching Requests ===")

        # Try API download first
        api_result = self._try_api_download(PlayMetricsExportType.COACHING_REQUESTS)
        if api_result:
            return api_result

        try:
            # Strategy 1: Direct URL with league_id (preferred — confirmed pattern)
            # URL: /club-admin/leagues/{league_id}/Coaching%20Requests
            if self.league_id:
                coaching_url = (
                    f"{self.base_url}/club-admin/leagues/"
                    f"{self.league_id}/Coaching%20Requests"
                )
                logger.info(f"Navigating directly to: {coaching_url}")
                self.driver.get(coaching_url)
                time.sleep(self.page_load_wait)
            else:
                # Strategy 2: Navigate via UI — Programs → Leagues → League
                logger.info("No league_id configured, navigating via UI...")
                if not self._navigate_to_programs():
                    return None

                # Click Leagues tab/link
                leagues_selectors = [
                    (By.XPATH, '//a[contains(text(), "Leagues")]'),
                    (By.XPATH, '//span[contains(text(), "Leagues")]'),
                    (By.XPATH, '//*[@role="tab"][contains(text(), "Leagues")]'),
                    (By.CSS_SELECTOR, 'a[href*="/leagues"]'),
                ]
                if self.interactor.try_multiple_selectors(
                    leagues_selectors, "click", timeout=10
                ):
                    time.sleep(self.page_load_wait)
                else:
                    self.driver.get(f"{self.base_url}/club-admin/leagues")
                    time.sleep(self.page_load_wait)

                # Click into the specific league
                if self.league_name:
                    league_selectors = [
                        (By.XPATH,
                         f'//h5[contains(text(), "{self.league_name}")]'),
                        (By.XPATH,
                         f'//*[contains(text(), "{self.league_name}")]'),
                    ]
                    self.interactor.try_multiple_selectors(
                        league_selectors, "click", timeout=8
                    )
                    time.sleep(self.page_load_wait)

                # Navigate to Coaching Requests tab
                coaching_tab_selectors = [
                    (By.XPATH, '//a[contains(text(), "Coaching Requests")]'),
                    (By.XPATH, '//span[contains(text(), "Coaching Requests")]'),
                    (By.XPATH,
                     '//*[@role="tab"][contains(text(), "Coaching")]'),
                ]
                self.interactor.try_multiple_selectors(
                    coaching_tab_selectors, "click", timeout=8
                )
                time.sleep(self.page_load_wait)

            # Click More Actions → Export Coaching Requests
            # Confirmed button: <button class="button is-primary is-outlined">
            #   <span>More Actions</span>
            # </button>
            if not self._click_more_actions():
                return None

            # Confirmed menu item: "Export Coaching Requests"
            if not self._click_export_option("Export Coaching Requests"):
                logger.error("Could not find Export Coaching Requests option")
                return None

            # Handle intermediary export page → Download as .CSV button
            if not self._click_download_csv():
                logger.error("Could not trigger CSV download")
                return None

            # Wait for download
            # Wait for download, rename, and archive
            filepath = self._wait_for_download(
                PlayMetricsExportType.COACHING_REQUESTS,
                timeout=self.download_timeout
            )

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

    def scrape_packages(self) -> Optional[str]:
        """
        Scrape the Packages tab to get current registration counts and capacity.

        Navigates to /program-admin/programs/{id}/packages and extracts:
          - Package name (division)
          - Active registrations
          - Max spots (capacity)
          - Waitlist count
          - Financial totals (paid, refunded, outstanding)

        Saves to packages_{YYYYMMDD_HHMMSS}.json in the download directory.
        This data feeds DIVISION_CONFIG.max_spots in the enrollment report.

        Confirmed DOM structure:
          div.package-card
            a.package-card__package-name → "06UB Boys"
            span.package-card__stat--main → active registrations (1st)
            span " of {n}" → max spots
            span.package-card__stat--main → waitlist count (2nd)

        Returns:
            Path to saved JSON, or None
        """
        logger.info("=== Scraping Packages ===")
        import json

        try:
            # Navigate to the Packages tab
            packages_url = (
                f"{self.base_url}/program-admin/programs/"
                f"{self.program_id}/packages"
            )
            logger.info(f"Navigating to: {packages_url}")
            self.driver.get(packages_url)
            time.sleep(self.page_load_wait)

            # Wait for package cards to render
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, '.package-card')
                    )
                )
            except TimeoutException:
                logger.error("Package cards did not load")
                self._take_screenshot("pm_packages_timeout")
                return None

            # Scrape all package cards via JavaScript
            # (more reliable than Selenium element iteration for Vue)
            scrape_js = """
            const cards = document.querySelectorAll('.package-card');
            const packages = [];
            cards.forEach(card => {
                const nameEl = card.querySelector('.package-card__package-name');
                const statBoxes = card.querySelectorAll(
                    '.package-card__stat-box--registration'
                );
                const finBoxes = card.querySelectorAll(
                    '.package-card__stat-box:not(.package-card__stat-box--registration)'
                );

                const name = nameEl ? nameEl.textContent.trim() : '';

                // Active registrations box
                let active = 0, maxSpots = 0;
                if (statBoxes.length > 0) {
                    const mainStat = statBoxes[0].querySelector(
                        '.package-card__stat--main'
                    );
                    active = mainStat ?
                        parseInt(mainStat.textContent.trim()) || 0 : 0;
                    // "of {n}" is in a sibling span
                    const ofText = statBoxes[0].textContent;
                    const ofMatch = ofText.match(/of\\s+(\\d+)/);
                    maxSpots = ofMatch ? parseInt(ofMatch[1]) : 0;
                }

                // Waitlist box
                let waitlist = 0;
                if (statBoxes.length > 1) {
                    const wlStat = statBoxes[1].querySelector(
                        '.package-card__stat--main'
                    );
                    waitlist = wlStat ?
                        parseInt(wlStat.textContent.trim()) || 0 : 0;
                }

                // Financial data
                const financials = {};
                finBoxes.forEach(box => {
                    const label = box.querySelector(
                        '.package-card__label'
                    );
                    if (label) {
                        const key = label.textContent.trim().toLowerCase();
                        const val = box.textContent
                            .replace(label.textContent, '')
                            .trim();
                        financials[key] = val;
                    }
                });

                if (name) {
                    packages.push({
                        name: name,
                        active_registrations: active,
                        max_spots: maxSpots,
                        waitlist: waitlist,
                        total: financials['total'] || '',
                        paid: financials['paid'] || '',
                        refunded: financials['refunded'] || '',
                        outstanding: financials['outstanding'] || ''
                    });
                }
            });
            return JSON.stringify(packages);
            """

            result_json = self.driver.execute_script(scrape_js)
            packages = json.loads(result_json) if result_json else []

            if not packages:
                logger.error("No packages scraped")
                self._take_screenshot("pm_packages_empty")
                return None

            logger.info(f"Scraped {len(packages)} packages")
            for pkg in packages:
                logger.info(
                    f"  {pkg['name']}: {pkg['active_registrations']}"
                    f"/{pkg['max_spots']} "
                    f"(waitlist: {pkg['waitlist']})"
                )

            # Save with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"packages_{timestamp}.json"
            filepath = Path(self.download_dir) / filename

            output = {
                "scraped_at": datetime.now().isoformat(),
                "program_id": self.program_id,
                "program_name": self.program_name,
                "total_packages": len(packages),
                "total_active": sum(
                    p['active_registrations'] for p in packages
                ),
                "packages": packages
            }

            with open(filepath, 'w') as f:
                json.dump(output, f, indent=2)

            logger.info(f"Packages saved: {filepath}")

            # Prune old versions
            self._prune_history(Path(self.download_dir), "packages")

            return str(filepath)

        except Exception as e:
            logger.error(f"Failed to scrape packages: {e}")
            self._take_screenshot("pm_packages_error")
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

        # 4. Packages (scraped, not downloaded)
        results["packages"] = self.scrape_packages()

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
        for export_type in self.CANONICAL_NAMES:
            filepath = self.find_latest_export(export_type)
            results[export_type] = filepath
        return results

    def get_download_summary(self) -> str:
        """Get a formatted summary of download status."""
        existing = self.check_existing_exports()

        lines = [
            "PlayMetrics Export Status",
            "=" * 50,
            f"Download directory: {self.download_dir}",
            f"Max history: {self.MAX_HISTORY} versions per export",
            "",
        ]

        for export_type, filepath in existing.items():
            canonical = self.CANONICAL_NAMES.get(export_type, export_type)
            if filepath:
                p = Path(filepath)
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                size_kb = p.stat().st_size / 1024

                # Count historical versions
                import re
                ts_pattern = re.compile(
                    rf'^{re.escape(canonical)}_\d{{8}}_\d{{6}}\.csv$'
                )
                version_count = sum(
                    1 for f in Path(self.download_dir).iterdir()
                    if f.is_file() and ts_pattern.match(f.name)
                )

                lines.append(
                    f"  {canonical}: {p.name} "
                    f"({size_kb:.0f} KB, {mtime:%Y-%m-%d %H:%M}) "
                    f"[{version_count} version(s)]"
                )
            else:
                lines.append(f"  {canonical}: NOT FOUND")

        return "\n".join(lines)
