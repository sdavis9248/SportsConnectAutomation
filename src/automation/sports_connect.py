"""
Main Sports Connect automation class
Complete version with Sports Affinity, Waitlist Management, and Access integration
"""
import os
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from core.config import ConfigManager
from core.webdriver_manager import WebDriverManager
from core.element_interactor import ElementInteractor
from core.exceptions import LoginError, ReportExportError, DownloadError
from utilities.credentials import CredentialsManager
from automation.report_handlers import ReportType, ReportHandlers, ReportConfig, SiteType
from integrations.access_db import AccessDatabaseManager

logger = logging.getLogger(__name__)


class SportsConnectAutomation:
    """Main automation class for Sports Connect with full integration support"""
    
    def __init__(self, config: ConfigManager = None):
        """
        Initialize Sports Connect Automation
        
        Args:
            config: Configuration manager instance
        """
        self.config = config or ConfigManager()
        self.driver_manager = None
        self.driver = None
        self.interactor = None
        self.logged_in = False
        
        # Report configurations
        self.report_handlers = ReportHandlers()
        self.reports = self.report_handlers.get_report_configs(
            self.config.base_url,
            self.config.organization_id
        )
        
        # Download tracking
        self.downloaded_files = {}
        
        # Component managers
        self.access_manager = None
        self.waitlist_manager = None
    
    def __enter__(self):
        """Context manager entry"""
        self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.cleanup()
    
    def initialize(self):
        """Initialize WebDriver and components"""
        logger.info("Initializing Sports Connect Automation...")
        
        # Create WebDriver
        self.driver_manager = WebDriverManager(
            download_dir=str(Path(self.config.download_dir).absolute()),
            headless=self.config.headless_mode
        )
        self.driver = self.driver_manager.create_driver()
        self.driver.download_dir = self.config.download_dir  # Store for later use
        
        # Create element interactor
        self.interactor = ElementInteractor(
            self.driver,
            timeout=self.config.default_timeout
        )
        
        # Initialize Access manager if enabled
        if self.config.get('access_config', {}).get('enabled', True):
            self.access_manager = AccessDatabaseManager(self.config)
        
        logger.info("Initialization complete")
    
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up...")
        if self.driver_manager:
            self.driver_manager.quit()
        self.driver = None
        self.interactor = None
        self.logged_in = False
        self.access_manager = None
        self.waitlist_manager = None
    
    def login(self) -> bool:
        """Login to Sports Connect (shared login for both sites)"""
        logger.info("Logging into Sports Connect...")
        
        try:
            # Load credentials
            creds_manager = CredentialsManager()
            username, password = creds_manager.load_credentials(self.config.credentials_file)
            
            # Navigate to login page (use team detail report URL)
            login_url = self.reports[ReportType.TEAM_DETAIL].url
            logger.info(f"Navigating to: {login_url}")
            self.driver.get(login_url)
            
            # Wait for page to load
            time.sleep(3)
            
            # Enter username
            username_selectors = [
                (By.XPATH, '//*[@id="root"]/div/div/div[2]/div/div[3]/div/div[1]/section/section/input'),
                (By.CSS_SELECTOR, 'input[type="email"]'),
                (By.CSS_SELECTOR, 'input[type="text"]'),
                (By.XPATH, '//input[@placeholder="Email"]')
            ]
            
            if self.interactor.try_multiple_selectors(username_selectors, "send_keys", text=username):
                logger.info("Entered username")
            else:
                raise LoginError("Could not find username field")
            
            # Click continue button
            continue_selectors = [
                (By.XPATH, '//button[text()="Continue"]'),
                (By.XPATH, '//button[contains(text(), "Continue")]'),
                (By.CSS_SELECTOR, 'button[type="submit"]')
            ]
            
            if self.interactor.try_multiple_selectors(continue_selectors, "click"):
                logger.info("Clicked continue")
            else:
                raise LoginError("Could not find continue button")
            
            # Wait for password field
            time.sleep(2)
            
            # Enter password
            password_selectors = [
                (By.XPATH, '//*[@id="root"]/div/div/div[2]/div/div[3]/div/div[1]/section/form/section/input'),
                (By.CSS_SELECTOR, 'input[type="password"]'),
                (By.XPATH, '//input[@placeholder="Password"]')
            ]
            
            if self.interactor.try_multiple_selectors(password_selectors, "send_keys", text=password):
                logger.info("Entered password")
            else:
                raise LoginError("Could not find password field")
            
            # Click continue again
            if self.interactor.try_multiple_selectors(continue_selectors, "click"):
                logger.info("Clicked continue for password")
            else:
                raise LoginError("Could not find continue button after password")
            
            # Wait for login to complete
            time.sleep(self.config.download_delay)
            
            # Check if login was successful by looking for logout button or user menu
            login_success_indicators = [
                (By.XPATH, '//button[contains(text(), "Logout")]'),
                (By.XPATH, '//button[contains(text(), "Sign Out")]'),
                (By.CSS_SELECTOR, '[aria-label="User menu"]'),
                (By.XPATH, '//mat-icon[text()="account_circle"]')
            ]
            
            # Give more time for page to load
            time.sleep(3)
            
            # Check if we're still on login page
            current_url = self.driver.current_url
            if "login" in current_url.lower() or "signin" in current_url.lower():
                logger.warning("Still on login page, login may have failed")
                # Take screenshot for debugging
                self.driver_manager.take_screenshot("login_failed.png")
                raise LoginError("Login appears to have failed - still on login page")
            
            self.logged_in = True
            logger.info("Login successful")
            return True
            
        except Exception as e:
            logger.error(f"Login failed: {e}")
            # Take screenshot for debugging
            if self.driver_manager:
                self.driver_manager.take_screenshot("login_error.png")
            raise LoginError(f"Login failed: {e}")
    
    def export_report(self, report_type: ReportType) -> Optional[str]:
        """Export a specific report"""
        if not self.logged_in:
            logger.error("Not logged in")
            return None
        
        report_config = self.reports[report_type]
        logger.info(f"Exporting {report_config.name}...")
        
        try:
            # Check if this is a Sports Affinity report
            if report_config.site_type == SiteType.SPORTS_AFFINITY.value:
                return self._handle_sports_affinity_report(report_type)
            
            # Handle Sports Connect reports
            logger.info(f"Navigating to: {report_config.url}")
            self.driver.get(report_config.url)
            time.sleep(5)  # Allow page to load
            
            # Take screenshot for debugging
            self.driver_manager.take_screenshot(f"report_{report_type.name}_loaded.png")
            
            # Handle report-specific logic
            if report_type == ReportType.TEAM_DETAIL:
                self._handle_team_detail_report()
            elif report_type == ReportType.ENROLLMENT_SUMMARY:
                self._handle_enrollment_summary_report()
            elif report_type == ReportType.WAITLIST_MANAGEMENT:
                return self._handle_waitlist_management()
            
            # For regular reports, continue with export process
            if report_type != ReportType.WAITLIST_MANAGEMENT:
                # Click export button
                self._click_export_button(report_config)
                
                # Select Excel format
                self._select_excel_format()
                
                # Wait for download
                time.sleep(self.config.download_delay)
                
                # Find downloaded file
                downloaded_file = self._find_latest_download(report_config.export_filename_prefix)
                
                if downloaded_file:
                    logger.info(f"Successfully exported {report_config.name} to {downloaded_file}")
                    self.downloaded_files[report_type] = downloaded_file
                    
                    # Run Access macro if configured
                    if report_config.post_process_macro:
                        self._run_access_macro(report_config.post_process_macro)
                    
                    return downloaded_file
                else:
                    logger.error(f"Failed to download {report_config.name}")
                    return None
            
        except Exception as e:
            logger.error(f"Error exporting {report_config.name}: {e}")
            # Take screenshot for debugging
            self.driver_manager.take_screenshot(f"report_{report_type.name}_error.png")
            raise ReportExportError(f"Failed to export {report_config.name}: {e}")
    
    def _handle_sports_affinity_report(self, report_type: ReportType) -> Optional[str]:
        """Handle Sports Affinity report export using existing login session"""
        logger.info(f"Processing Sports Affinity report: {report_type.value}")
        
        # Lazy import to avoid circular import
        try:
            from automation.sports_affinity_manager import SportsAffinityManager
        except ImportError as e:
            logger.error(f"Failed to import SportsAffinityManager: {e}")
            return None
        
        # Create Sports Affinity manager with shared login session
        affinity_manager = SportsAffinityManager(self.driver, self.config, already_logged_in=True)
        
        # Navigate to Sports Affinity using existing session
        if not affinity_manager.navigate_to_sports_affinity():
            logger.error("Failed to navigate to Sports Affinity")
            return None
        
        try:
            # Export specific report
            if report_type == ReportType.ADMIN_CREDENTIALS:
                downloaded_file = affinity_manager.export_admin_credentials()
            elif report_type == ReportType.ADMIN_DETAILS:
                downloaded_file = affinity_manager.export_admin_details()
            elif report_type == ReportType.MEDICAL_FORMS:
                downloaded_file = self._handle_medical_forms_download()
            else:
                logger.error(f"Unknown Sports Affinity report type: {report_type}")
                return None
            
            if downloaded_file:
                logger.info(f"Successfully exported Sports Affinity report: {downloaded_file}")
                self.downloaded_files[report_type] = downloaded_file
                
                # Run Access macro if this is admin details report and auto-run is enabled
                if (report_type == ReportType.ADMIN_DETAILS and 
                    self.config.get('access_config', {}).get('auto_run_macros', True)):
                    self._run_access_macro('admin_detail')
            
            return downloaded_file
            
        except Exception as e:
            logger.error(f"Error exporting Sports Affinity report: {e}")
            return None
        finally:
            # Clean up Sports Affinity session
            affinity_manager.cleanup()
    
    def _handle_waitlist_management(self) -> Optional[str]:
        """Handle waitlist participant removal"""
        logger.info("Starting waitlist management...")
        
        # Lazy import to avoid circular import
        try:
            from automation.waitlist_manager import WaitlistManager
        except ImportError as e:
            logger.error(f"Failed to import WaitlistManager: {e}")
            return None
        
        # Get waitlist configuration
        waitlist_config = self.config.get('waitlist_config', {})
        order_numbers = waitlist_config.get('order_numbers_to_remove', [])
        
        if not order_numbers:
            logger.warning("No order numbers specified for waitlist removal")
            return None
        
        program_id = self.config.get('program_id')
        program_name = self.config.get('program_name', '2025 Fall Core')
        
        if not program_id:
            logger.error("Program ID not configured")
            return None
        
        # Create waitlist manager
        self.waitlist_manager = WaitlistManager(
            self.driver, 
            self.config.base_url, 
            self.config.organization_id,
            self.config
        )
        
        # Process divisions
        results = self.waitlist_manager.process_all_divisions(program_id, order_numbers, program_name)
        
        # Save results
        results_file = self.waitlist_manager.save_results(results, order_numbers, self.config.download_dir)
        
        # Log summary
        total_removed = sum(r['removed'] for r in results)
        successful_divisions = len([r for r in results if r['status'] == 'success'])
        
        logger.info(f"Waitlist management completed:")
        logger.info(f"  - Total participants removed: {total_removed}")
        logger.info(f"  - Successful divisions: {successful_divisions}/{len(results)}")
        logger.info(f"  - Results saved to: {results_file}")
        
        return results_file
    
    def _handle_medical_forms_download(self) -> Optional[str]:
        """Handle medical forms download process"""
        logger.info("Starting medical forms download...")
        
        # Lazy import to avoid circular import
        try:
            from automation.medical_forms_manager import MedicalFormsManager
        except ImportError as e:
            logger.error(f"Failed to import MedicalFormsManager: {e}")
            return None
        
        # Get medical forms configuration
        medical_config = self.config.get('medical_forms_config', {})
        divisions = medical_config.get('divisions', ['07UB'])  # Default to test division
        
        if not divisions:
            logger.warning("No divisions specified for medical forms download")
            return None
        
        # Create medical forms manager
        medical_manager = MedicalFormsManager(self.driver, self.config, already_logged_in=True)
        
        # Navigate to Sports Affinity
        if not medical_manager.navigate_to_sports_affinity():
            logger.error("Failed to navigate to Sports Affinity for medical forms")
            return None
        
        try:
            # Process all divisions
            results = medical_manager.process_all_divisions(divisions)
            
            # Save results summary
            from datetime import datetime
            import json
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = os.path.join(self.config.download_dir, f"medical_forms_results_{timestamp}.json")
            
            with open(results_file, "w") as f:
                json.dump(results, f, indent=2)
            
            # Log summary
            logger.info(f"Medical forms download completed:")
            logger.info(f"  - Total divisions processed: {results['successful_divisions']}/{results['total_divisions']}")
            logger.info(f"  - Total teams processed: {results['total_teams_processed']}")
            logger.info(f"  - Results saved to: {results_file}")
            
            return results_file
            
        except Exception as e:
            logger.error(f"Error in medical forms download: {e}")
            return None
        finally:
            # Clean up medical forms session
            medical_manager.cleanup()
    
    def _handle_team_detail_report(self):
        """Handle Team Detail report specific logic"""
        logger.info("Handling Team Detail report...")
        
        # Wait for and click on active element (Program dropdown)
        time.sleep(2)
        elem = self.driver.switch_to.active_element
        elem.click()
        
        # Select season
        season_selectors = [
            (By.XPATH, f'//mat-option[normalize-space()="{self.config.season}"]'),
            (By.XPATH, f'//span[contains(text(), "{self.config.season}")]'),
            (By.XPATH, f'//mat-option[contains(text(), "{self.config.season}")]')
        ]
        
        if self.interactor.try_multiple_selectors(season_selectors, "click"):
            logger.info(f"Selected season: {self.config.season}")
        else:
            logger.warning(f"Could not select season: {self.config.season}")
        
        # Click View Report button
        view_report_selectors = [
            (By.CSS_SELECTOR, "button.mat-focus-indicator.select-all.mat-flat-button.mat-button-base.mat-primary"),
            (By.XPATH, "//button[contains(@class, 'mat-primary') and contains(., 'View Report')]"),
            (By.XPATH, "//span[text()=' View Report ']/parent::button"),
            (By.CSS_SELECTOR, "#mat-dialog-0 button.mat-primary")
        ]
        
        if self.interactor.try_multiple_selectors(view_report_selectors, "click", timeout=80):
            logger.info("Clicked View Report")
        else:
            logger.warning("Could not click View Report button")
        
        # Wait for report to load
        time.sleep(20)
    
    def _handle_enrollment_summary_report(self):
        """Handle Enrollment Summary report specific logic"""
        logger.info("Handling Enrollment Summary report...")
        
        # Click season dropdown
        season_dropdown_selectors = [
            (By.XPATH, '//*[@id="mat-select-0"]/div/div[1]/span'),
            (By.CSS_SELECTOR, 'mat-select'),
            (By.XPATH, '//mat-select[1]')
        ]
        
        if self.interactor.try_multiple_selectors(season_dropdown_selectors, "click"):
            logger.info("Clicked season dropdown")
            time.sleep(1)
        
        # Select season
        season_selectors = [
            (By.XPATH, f'//mat-option[normalize-space()="{self.config.season}"]'),
            (By.XPATH, f'//span[contains(text(), "{self.config.season}")]')
        ]
        
        if self.interactor.try_multiple_selectors(season_selectors, "click"):
            logger.info(f"Selected season: {self.config.season}")
        
        # Click View Report
        view_button_selectors = [
            (By.XPATH, '//*[@id="mat-dialog-0"]/sc-static-report-condition-dialog/div/div[2]/div[2]/button[2]'),
            (By.XPATH, '//button[contains(., "View Report")]'),
            (By.CSS_SELECTOR, 'button.mat-primary')
        ]
        
        if self.interactor.try_multiple_selectors(view_button_selectors, "click"):
            logger.info("Clicked View Report")
        
        # Wait for report to load
        time.sleep(10)
    
    def _click_export_button(self, report_config: ReportConfig):
        """Click the export button for any report"""
        logger.info("Looking for export button...")
        
        # Try multiple selectors for robustness
        export_selectors = [
            (By.CSS_SELECTOR, "button.mat-focus-indicator.mat-menu-trigger.report-header-action.report-header-action__export"),
            (By.CSS_SELECTOR, "button[class*='report-header-action__export']"),
            (By.XPATH, "//button[contains(@class, 'report-header-action__export')]"),
            (By.XPATH, "//button[.//span[contains(text(), 'Export')]]"),
            (By.XPATH, "//button[.//mat-icon[text()='publish']]"),
            (By.CSS_SELECTOR, "button.report-header-action__export")
        ]
        
        if self.interactor.try_multiple_selectors(export_selectors, "click", timeout=report_config.wait_time):
            logger.info("Clicked export button")
        else:
            raise ReportExportError("Could not find export button")
    
    def _select_excel_format(self):
        """Select Excel format from export dropdown"""
        logger.info("Selecting Excel format...")
        
        # Wait for dropdown to appear
        time.sleep(1)
        
        # Try multiple selectors
        excel_selectors = [
            (By.CSS_SELECTOR, "#mat-menu-panel-0 button:nth-child(2)"),
            (By.XPATH, "//button[contains(text(), 'Excel')]"),
            (By.XPATH, "//button[contains(., 'Excel')]"),
            (By.XPATH, "//*[@id='mat-menu-panel-0']/div/div/button[2]"),
            (By.CSS_SELECTOR, "button.mat-menu-item:nth-of-type(2)")
        ]
        
        if self.interactor.try_multiple_selectors(excel_selectors, "click", timeout=10):
            logger.info("Selected Excel format")
        else:
            raise ReportExportError("Could not select Excel format")
    
    def _find_latest_download(self, prefix: str) -> Optional[str]:
        """Find the latest downloaded file matching prefix"""
        import glob
        
        # Wait a bit for download to start
        time.sleep(2)
        
        download_dir = Path(self.config.download_dir).absolute()
        
        # Check for partial downloads first
        for _ in range(30):  # Wait up to 30 seconds
            partial_files = list(download_dir.glob("*.crdownload"))
            if not partial_files:
                break
            time.sleep(1)
        
        # Look for files matching pattern
        patterns = [
            f"{prefix}*.xlsx",
            f"*{prefix}*.xlsx",
            f"{prefix}*.xls",
            "*.xlsx"  # Fallback to any Excel file
        ]
        
        for pattern in patterns:
            files = list(download_dir.glob(pattern))
            if files:
                # Return most recent file
                latest_file = max(files, key=lambda f: f.stat().st_mtime)
                logger.info(f"Found downloaded file: {latest_file}")
                return str(latest_file)
        
        # List all files in download directory for debugging
        all_files = list(download_dir.glob("*"))
        logger.warning(f"Files in download directory: {[f.name for f in all_files]}")
        
        return None
    
    def _run_access_macro(self, macro_type: str) -> bool:
        """Run Access macro using shared Access manager"""
        try:
            if not self.access_manager:
                logger.info("Access integration not initialized")
                return True
            
            access_config = self.config.get('access_config', {})
            
            if not access_config.get('auto_run_macros', True):
                logger.info("Access macro auto-run disabled")
                return True
            
            # Get macro name from config
            macro_name = access_config.get('macros', {}).get(macro_type)
            if not macro_name:
                logger.warning(f"No macro configured for {macro_type}")
                return False
            
            # Create backup if configured
            if access_config.get('backup_before_macro', False):
                backup_file = self.access_manager.backup_database()
                if backup_file:
                    logger.info(f"Database backup created: {backup_file}")
            
            # Run the macro
            success = self.access_manager.run_macro(macro_name)
            
            if success:
                logger.info(f"Access macro '{macro_name}' completed successfully")
            else:
                logger.error(f"Access macro '{macro_name}' failed")
            
            return success
            
        except Exception as e:
            logger.error(f"Error running Access macro: {e}")
            return False
    
    def export_all_reports(self) -> Dict[ReportType, Optional[str]]:
        """Export all enabled reports from both Sports Connect and Sports Affinity"""
        results = {}
        
        # Separate reports by site type
        sports_connect_reports = []
        sports_affinity_reports = []
        
        for report_type in ReportType:
            report_name = report_type.name.lower()
            if self.config.is_report_enabled(report_name):
                report_config = self.reports[report_type]
                if report_config.site_type == SiteType.SPORTS_CONNECT.value:
                    sports_connect_reports.append(report_type)
                elif report_config.site_type == SiteType.SPORTS_AFFINITY.value:
                    sports_affinity_reports.append(report_type)
        
        # Process Sports Connect reports first
        logger.info(f"Processing {len(sports_connect_reports)} Sports Connect reports")
        for report_type in sports_connect_reports:
            try:
                logger.info(f"Exporting {report_type.value}...")
                file_path = self.export_report(report_type)
                results[report_type] = file_path
                
                # Add delay between reports
                time.sleep(3)
                
            except Exception as e:
                logger.error(f"Failed to export {report_type.value}: {e}")
                results[report_type] = None
        
        # Process Sports Affinity reports using optimized batch processing
        if sports_affinity_reports:
            logger.info(f"Processing {len(sports_affinity_reports)} Sports Affinity reports")
            
            # Lazy import to avoid circular import
            try:
                from automation.sports_affinity_manager import SportsAffinityManager
            except ImportError as e:
                logger.error(f"Failed to import SportsAffinityManager: {e}")
                # Mark all Sports Affinity reports as failed
                for report_type in sports_affinity_reports:
                    results[report_type] = None
                return results
            
            # Create Sports Affinity manager once for all reports (reusing existing login)
            affinity_manager = SportsAffinityManager(self.driver, self.config, already_logged_in=True)
            
            # Navigate to Sports Affinity
            if affinity_manager.navigate_to_sports_affinity():
                # Handle medical forms separately as they require different processing
                medical_forms_idx = None
                for i, report_type in enumerate(sports_affinity_reports):
                    if report_type == ReportType.MEDICAL_FORMS:
                        medical_forms_idx = i
                        results[report_type] = self._handle_medical_forms_download()
                        break
                
                # Remove medical forms from the list for batch processing
                if medical_forms_idx is not None:
                    sports_affinity_reports.pop(medical_forms_idx)
                
                # Export other Sports Affinity reports in one session
                if sports_affinity_reports:
                    affinity_results = affinity_manager.export_all_reports()
                    
                    # Map results back to report types
                    for report_type in sports_affinity_reports:
                        if report_type == ReportType.ADMIN_CREDENTIALS:
                            results[report_type] = affinity_results.get('admin_credentials')
                        elif report_type == ReportType.ADMIN_DETAILS:
                            results[report_type] = affinity_results.get('admin_details')
                            
                            # Run Access macro if admin details was successful
                            if (results[report_type] and 
                                self.config.get('access_config', {}).get('auto_run_macros', True)):
                                self._run_access_macro('admin_detail')
                
                # Clean up Sports Affinity session
                affinity_manager.cleanup()
            else:
                # Mark all Sports Affinity reports as failed
                for report_type in sports_affinity_reports:
                    results[report_type] = None
        
        return results
    
    def run_single_report(self, report_name: str) -> Optional[str]:
        """Run a single report by name"""
        try:
            # Convert string to ReportType enum
            report_type = ReportType[report_name.upper()]
            
            # Initialize if needed
            if not self.driver:
                self.initialize()
            
            # Login if needed
            if not self.logged_in:
                self.login()
            
            # Export report
            return self.export_report(report_type)
            
        except KeyError:
            logger.error(f"Invalid report name: {report_name}")
            logger.info(f"Valid options: {', '.join(r.name for r in ReportType)}")
            return None
        except Exception as e:
            logger.error(f"Error running report {report_name}: {e}")
            return None
    
    def run_all_reports(self) -> bool:
        """Run all enabled reports"""
        try:
            # Initialize if needed
            if not self.driver:
                self.initialize()
            
            # Login
            if not self.login():
                return False
            
            # Export all reports
            results = self.export_all_reports()
            
            # Log summary
            successful = sum(1 for path in results.values() if path)
            total = len(results)
            logger.info(f"Successfully exported {successful}/{total} reports")
            
            return successful > 0
            
        except Exception as e:
            logger.error(f"Error in run_all_reports: {e}")
            return False
    
    def get_waitlist_summary(self) -> Optional[Dict]:
        """Get waitlist summary without removing participants"""
        if not self.logged_in:
            logger.error("Not logged in")
            return None
        
        # Lazy import to avoid circular import
        try:
            from automation.waitlist_manager import WaitlistManager
        except ImportError as e:
            logger.error(f"Failed to import WaitlistManager: {e}")
            return None
        
        program_id = self.config.get('program_id')
        program_name = self.config.get('program_name', '2025 Fall Core')
        
        if not program_id:
            logger.error("Program ID not configured")
            return None
        
        if not self.waitlist_manager:
            self.waitlist_manager = WaitlistManager(
                self.driver, 
                self.config.base_url, 
                self.config.organization_id,
                self.config
            )
        
        return self.waitlist_manager.get_waitlist_summary(program_id, program_name)
    
    def get_access_database_info(self) -> dict:
        """Get information about the Access database"""
        try:
            if not self.access_manager:
                self.access_manager = AccessDatabaseManager(self.config)
            return self.access_manager.get_database_info()
        except Exception as e:
            logger.error(f"Error getting Access database info: {e}")
            return {}
    
    def run_access_macro_on_demand(self, macro_name: str) -> bool:
        """Run a specific Access macro on demand"""
        try:
            if not self.access_manager:
                self.access_manager = AccessDatabaseManager(self.config)
            return self.access_manager.run_macro(macro_name)
        except Exception as e:
            logger.error(f"Error running Access macro {macro_name}: {e}")
            return False
    
    def list_available_reports(self) -> Dict[str, Dict]:
        """Get a list of all available reports with their details"""
        return self.report_handlers.list_all_reports()
    
    def validate_report_name(self, report_name: str) -> tuple:
        """Validate a report name"""
        return self.report_handlers.validate_report_name(report_name)