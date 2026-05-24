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

    # Discovered API URL pattern (volunteers confirmed):
    # https://api.playmetrics.com/program_admin/programs/{program_id}/{export}.csv
    #   ?access_key={base64_key}&fbt={firebase_jwt}
    # The fbt token is a Firebase JWT from the authenticated session.
    # This could enable direct downloads without UI navigation.
    API_BASE = "https://api.playmetrics.com/program_admin/programs"


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

        if self.interactor.try_multiple_selectors(
            option_selectors, "click", timeout=8
        ):
            logger.info(f"Clicked: {option_text}")
            return True

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
