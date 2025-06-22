"""
Sports Affinity management for Sports Connect Automation
Optimized version that reuses existing login and shared components
"""
import logging
import time
import os
from typing import List, Dict, Optional
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

class SportsAffinityManager:
    """Handles Sports Affinity operations - optimized version"""
    
    def __init__(self, driver, config=None, already_logged_in=False):
        """
        Initialize Sports Affinity Manager
        
        Args:
            driver: Selenium WebDriver instance
            config: Configuration manager instance
            already_logged_in: Whether we're already logged into the shared login system
        """
        self.driver = driver
        self.config = config
        # Create ElementInteractor here to avoid circular import
        from core.element_interactor import ElementInteractor
        self.interactor = ElementInteractor(driver)
        self.wait = WebDriverWait(driver, 10)
        self.download_delay = config.get('download_delay', 5) if config else 5
        self.organization_id = config.get('organization_id')
        self.main_page_handle = None
        self.already_logged_in = already_logged_in
        
        # Sports Affinity specific configuration
        self.base_url = f"https://core-api.bluesombrero.com/api/v1/Redirect/{self.organization_id}/affinity_login"
        self.region_value = config.get('sports_affinity_config', {}).get('region_value', 
            '58|cf44ab57-59e3-429b-8d5c-83d22ddd40e8|Region 58|67e9fdf7-f6d5-41cc-8f38-24bb8d38a4b9|7011394|') if config else '58|cf44ab57-59e3-429b-8d5c-83d22ddd40e8|Region 58|67e9fdf7-f6d5-41cc-8f38-24bb8d38a4b9|7011394|'
    
    def navigate_to_sports_affinity(self) -> bool:
        """Navigate to Sports Affinity using existing login session"""
        logger.info("Navigating to Sports Affinity...")
        
        try:
            if self.already_logged_in:
                # We're already logged in, just navigate to Sports Affinity
                logger.info("Using existing login session for Sports Affinity")
                self.driver.get(self.base_url)
                
                # Check if we need to click "Login with Email" button
                login_button_selectors = [
                    (By.ID, 'loginControl_btnSSOLogin'),
                    (By.XPATH, '//input[@value="Login with Email"]'),
                    (By.XPATH, '//button[contains(text(), "Login")]')
                ]
                
                # Try to click login button (might auto-redirect if already logged in)
                self.interactor.try_multiple_selectors(login_button_selectors, "click", timeout=3)
                
                # Wait for main page to load
                main_form_selectors = [
                    (By.XPATH, '//*[@id="main-content"]'),
                    (By.XPATH, '/html/body/form/nav/div[1]/div/a[2]/img'),
                    (By.ID, 'mainform')
                ]
                
                main_page_loaded = False
                for by, selector in main_form_selectors:
                    try:
                        WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((by, selector))
                        )
                        main_page_loaded = True
                        break
                    except:
                        continue
                
                if not main_page_loaded:
                    logger.warning("Sports Affinity main page may not have loaded properly")
                    return False
                
                # Store main page URL for navigation
                self.main_page_url = self.driver.current_url
                self.main_page_handle = self.driver.current_window_handle
                
                logger.info("Successfully navigated to Sports Affinity")
                return True
            else:
                logger.error("Not logged in - cannot navigate to Sports Affinity")
                return False
                
        except Exception as e:
            logger.error(f"Error navigating to Sports Affinity: {e}")
            return False
    
    def export_admin_credentials(self) -> Optional[str]:
        """Export Admin Credentials Dynamic report"""
        logger.info('Exporting Admin Credentials...')
        
        try:
            # Navigate to Additional Reports
            submenu_xpath = '//*[@id="mainform"]/nav/div[3]/div/div[1]/ul/li[4]/ul/li[10]/a'
            
            try:
                elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, submenu_xpath))
                )
                additional_reports_url = elem.get_attribute("href")
                self.driver.get(additional_reports_url)
            except:
                logger.error("Could not navigate to Additional Reports")
                return None
            
            # Select report type
            try:
                reporttype_elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, 'reporttype'))
                )
                select = Select(reporttype_elem)
                select.select_by_value('143')  # Admin Credentials | Dynamic Certificate Data
            except Exception as e:
                logger.error(f"Could not select report type: {e}")
                return None
            
            # Select region
            try:
                region_elem = self.driver.find_element(By.ID, 'Select6')
                select = Select(region_elem)
                select.select_by_value(self.region_value)
            except Exception as e:
                logger.error(f"Could not select region: {e}")
                return None
            
            # Generate report
            generate_button_selectors = [
                (By.XPATH, '//*[@id="Button2"]'),
                (By.ID, 'Button2'),
                (By.XPATH, '//input[@value="Generate Report"]')
            ]
            
            if not self.interactor.try_multiple_selectors(generate_button_selectors, "click"):
                logger.error("Could not find generate report button")
                return None
            
            # Switch to report window
            if not self._switch_to_report_window():
                return None
            
            # Export to Excel
            if not self._export_to_excel():
                return None
            
            # Switch back to main window
            self.driver.switch_to.window(self.main_page_handle)
            
            # Find downloaded file
            downloaded_file = self._find_latest_download("AdminCredentials")
            return downloaded_file
            
        except Exception as e:
            logger.error(f"Error exporting admin credentials: {e}")
            return None
    
    def export_admin_details(self) -> Optional[str]:
        """Export Admin Details All Fields report"""
        logger.info('Exporting Admin Details...')
        
        try:
            # Navigate to Admin Lookup
            submenu_xpath = '//*[@id="mainform"]/nav/div[3]/div/div[1]/ul/li[3]/ul/li[2]/a'
            
            try:
                elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, submenu_xpath))
                )
                admin_lookup_url = elem.get_attribute("href")
                self.driver.get(admin_lookup_url)
            except:
                logger.error("Could not navigate to Admin Lookup")
                return None
            
            # Click Search button to populate results
            search_button_selectors = [
                (By.XPATH, '//*[@id="main1011"]/div[2]/div[2]/div/div[4]/div[2]/div[2]/div/button[2]'),
                (By.XPATH, '//*[@id="main1011"]/table[3]/tbody/tr[2]/td/table/tbody/tr/td[4]/div/fieldset/table[2]/tbody/tr[2]/td[2]/input'),
                (By.XPATH, '//button[contains(text(), "Search")]'),
                (By.XPATH, '//input[@value="Search"]')
            ]
            
            if not self.interactor.try_multiple_selectors(search_button_selectors, "click"):
                logger.error("Could not find search button")
                return None
            
            # Wait for results to load
            time.sleep(2)
            
            # Select report type
            report_dropdown_selectors = [
                (By.XPATH, '//*[@id="PrintBtn"]/div/div[2]/select'),
                (By.XPATH, '//*[@id="PrintBtn"]/table/tbody/tr/td[2]/select')
            ]
            
            report_selected = False
            for by, selector in report_dropdown_selectors:
                try:
                    elem = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((by, selector))
                    )
                    select = Select(elem)
                    select.select_by_value('teamAdminDetail')
                    report_selected = True
                    break
                except:
                    continue
            
            if not report_selected:
                logger.error("Could not select admin detail report")
                return None
            
            # Generate report
            generate_button_selectors = [
                (By.XPATH, '//*[@id="PrintBtn"]/div/div[4]/button'),
                (By.XPATH, '//button[contains(text(), "Generate")]'),
                (By.XPATH, '//input[@value="Generate Report"]')
            ]
            
            if not self.interactor.try_multiple_selectors(generate_button_selectors, "click"):
                logger.error("Could not find generate report button")
                return None
            
            # Switch to report window
            if not self._switch_to_report_window():
                return None
            
            # Export to Excel
            if not self._export_to_excel():
                return None
            
            # Switch back to main window
            self.driver.switch_to.window(self.main_page_handle)
            
            # Find downloaded file
            downloaded_file = self._find_latest_download("AdminDetails")
            return downloaded_file
            
        except Exception as e:
            logger.error(f"Error exporting admin details: {e}")
            return None
    
    def _switch_to_report_window(self) -> bool:
        """Switch to report window"""
        try:
            # Wait for new window to open
            time.sleep(2)
            
            # Find report window
            for handle in self.driver.window_handles:
                if handle != self.main_page_handle:
                    self.driver.switch_to.window(handle)
                    logger.info("Switched to report window")
                    return True
            
            logger.error("Report window not found")
            return False
            
        except Exception as e:
            logger.error(f"Error switching to report window: {e}")
            return False
    
    def _export_to_excel(self) -> bool:
        """Export report to Excel format"""
        try:
            # Select Excel format
            format_elem = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, 'ctrlRptViewer_ctl01_ctl05_ctl00'))
            )
            select = Select(format_elem)
            select.select_by_value('EXCELOPENXML')
            
            # Click export button
            export_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="ctrlRptViewer_ctl01_ctl05_ctl01"]'))
            )
            export_button.click()
            
            # Wait for download to start
            time.sleep(self.download_delay)
            
            logger.info("Excel export completed")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting to Excel: {e}")
            return False
    
    def _find_latest_download(self, prefix: str) -> Optional[str]:
        """Find the latest downloaded file matching prefix"""
        try:
            import glob
            from pathlib import Path
            
            download_dir = Path(self.config.download_dir if self.config else "data/downloads").absolute()
            
            # Wait a bit for download to complete
            time.sleep(2)
            
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
            
            logger.warning(f"No downloaded file found for {prefix}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding downloaded file: {e}")
            return None
    
    def export_all_reports(self) -> Dict[str, Optional[str]]:
        """Export all Sports Affinity reports"""
        logger.info("Exporting all Sports Affinity reports")
        
        results = {}
        
        # Return to main page first
        if hasattr(self, 'main_page_url'):
            self.driver.get(self.main_page_url)
        
        # Export Admin Details
        try:
            admin_details_file = self.export_admin_details()
            results['admin_details'] = admin_details_file
            
            # Return to main page
            if hasattr(self, 'main_page_url'):
                self.driver.get(self.main_page_url)
                
        except Exception as e:
            logger.error(f"Failed to export admin details: {e}")
            results['admin_details'] = None
        
        # Export Admin Credentials
        try:
            admin_credentials_file = self.export_admin_credentials()
            results['admin_credentials'] = admin_credentials_file
            
        except Exception as e:
            logger.error(f"Failed to export admin credentials: {e}")
            results['admin_credentials'] = None
        
        # Log summary
        successful = sum(1 for path in results.values() if path)
        total = len(results)
        logger.info(f"Successfully exported {successful}/{total} Sports Affinity reports")
        
        return results
    
    def cleanup(self):
        """Clean up any resources"""
        # Close any additional windows that might be open
        try:
            if len(self.driver.window_handles) > 1:
                for handle in self.driver.window_handles:
                    if handle != self.main_page_handle:
                        self.driver.switch_to.window(handle)
                        self.driver.close()
                
                # Switch back to main window
                if self.main_page_handle:
                    self.driver.switch_to.window(self.main_page_handle)
                    
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")