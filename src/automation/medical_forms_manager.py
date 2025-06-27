"""
Medical Forms Manager for Sports Connect Automation
Handles downloading and organizing player medical forms from Sports Affinity
"""
import os
import glob
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from core.element_interactor import ElementInteractor
from integrations.google_drive import GoogleDriveUploader

logger = logging.getLogger(__name__)

class MedicalFormsManager:
    """Manages medical form downloads from Sports Affinity"""
    
    def __init__(self, driver, config=None, already_logged_in=False):
        """
        Initialize Medical Forms Manager
        
        Args:
            driver: Selenium WebDriver instance
            config: Configuration manager instance
            already_logged_in: Whether we're already logged into Sports Affinity
        """
        self.driver = driver
        self.config = config
        self.interactor = ElementInteractor(driver)
        self.wait = WebDriverWait(driver, 10)
        self.already_logged_in = already_logged_in
        self.download_delay = config.get('download_delay', 10) if config else 10
        
        # Medical forms specific configuration
        self.base_url = 'https://ayso.sportsaffinity.com/foundation/login.aspx'
        self.main_page_handle = None
        self.main_page_url = None
        
        # Default division list
        self.default_divisions = [
            '06UB', '06UG', '07UB', '07UG', '08UB', '08UG', 
            '10UB', '10UG', '12UB', '12UG', '14UB', '14UG', 
            '16UB', '16UG', '19UB', '19UG'
        ]
        
        # Initialize Google Drive if configured
        self.drive_uploader = None
        if config and config.get('google_drive_config', {}).get('enabled', False):
            try:
                self.drive_uploader = GoogleDriveUploader()
            except Exception as e:
                logger.warning(f"Google Drive integration not available: {e}")
    
    def navigate_to_sports_affinity(self) -> bool:
        """Navigate to Sports Affinity using existing login session"""
        logger.info("Navigating to Sports Affinity for medical forms...")
        
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
                    (By.XPATH, '/html/body/form/nav/div[1]/div/a/img'),
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
    
    def get_medical_forms_for_division(self, division: str) -> Dict[str, Any]:
        """
        Get medical forms for a specific division
        
        Args:
            division: Division code (e.g., '07UB', '10UG')
            
        Returns:
            Dictionary with results for the division
        """
        logger.info(f"Processing medical forms for division: {division}")
        
        try:
            # Navigate to Team Lookup
            submenu_xpath = '//*[@id="mainform"]/nav/div[3]/div/div[1]/ul/li[2]/ul/li[1]/a'
            
            try:
                elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, submenu_xpath))
                )
                team_lookup_url = elem.get_attribute("href")
                self.driver.get(team_lookup_url)
            except:
                logger.error("Could not navigate to Team Lookup")
                return {"division": division, "teams_processed": 0, "status": "failed", "error": "Navigation failed"}
            
            # Select season (most recent)
            season_xpath = "/html/body/div[2]/div/div[2]/div/select"
            try:
                elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, season_xpath))
                )
                select = Select(elem)
                select.select_by_index(0)  # Most recent season
            except Exception as e:
                logger.error(f"Could not select season: {e}")
                return {"division": division, "teams_processed": 0, "status": "failed", "error": "Season selection failed"}
            
            # Select play type (Core)
            playtype_xpath = '//*[@id="Select2"]'
            try:
                elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, playtype_xpath))
                )
                select = Select(elem)
                select.select_by_index(4)  # Core play type
            except Exception as e:
                logger.error(f"Could not select play type: {e}")
                return {"division": division, "teams_processed": 0, "status": "failed", "error": "Play type selection failed"}
            
            # Select gender
            gender_xpath = '/html/body/div[3]/div/div[2]/div[2]/div[4]/select'
            try:
                elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, gender_xpath))
                )
                select = Select(elem)
                
                gender_char = division[3:4] if len(division) > 3 else "C"
                if gender_char == "G":
                    gender_index = 1
                elif gender_char == "B":
                    gender_index = 2
                else:
                    gender_index = 0  # Coed
                
                select.select_by_index(gender_index)
            except Exception as e:
                logger.error(f"Could not select gender: {e}")
                return {"division": division, "teams_processed": 0, "status": "failed", "error": "Gender selection failed"}
            
            # Select age group
            age_xpath = '/html/body/div[3]/div/div[2]/div[2]/div[3]/select'
            try:
                elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, age_xpath))
                )
                select = Select(elem)
                
                age_group = division[0:3]
                if age_group == "05U":
                    age_group = "SchoolYard"
                elif age_group == "04U":
                    age_group = "Playground"
                
                select.select_by_visible_text(age_group)
            except Exception as e:
                logger.error(f"Could not select age group: {e}")
                return {"division": division, "teams_processed": 0, "status": "failed", "error": "Age group selection failed"}
            
            # Click Search button
            search_button_xpath = '/html/body/div[3]/div/div[2]/div[2]/div[6]/div[2]/div/button[2]'
            search_button_selectors = [
                (By.XPATH, search_button_xpath),
                (By.XPATH, '//button[contains(text(), "Search")]'),
                (By.XPATH, '//input[@value="Search"]')
            ]
            
            if not self.interactor.try_multiple_selectors(search_button_selectors, "click"):
                logger.error("Could not find search button")
                return {"division": division, "teams_processed": 0, "status": "failed", "error": "Search button not found"}
            
            # Wait for results
            time.sleep(2)
            
            # Check if we have teams
            team_count = self._get_team_count()
            
            if team_count == 0:
                logger.warning(f"No teams found for division {division}")
                return {"division": division, "teams_processed": 0, "status": "no_teams", "error": "No teams found"}
            
            # Process teams
            processed_teams = self._process_teams_for_division(division, team_count)
            
            return {
                "division": division,
                "teams_processed": processed_teams,
                "status": "success" if processed_teams > 0 else "failed"
            }
            
        except Exception as e:
            logger.error(f"Error processing division {division}: {e}")
            return {"division": division, "teams_processed": 0, "status": "failed", "error": str(e)}
    
    def _get_team_count(self) -> int:
        """Get the number of teams found"""
        try:
            # Check if we're on a single team page
            if "https://ayso.sportsaffinity.com/reg/team/team" in self.driver.current_url:
                return 1
            
            # Count rows in results table
            rows = self.driver.find_elements(By.XPATH, '//*[@id="Table4"]/tbody/tr')
            return len(rows) - 1 if rows else 0
            
        except Exception as e:
            logger.error(f"Error counting teams: {e}")
            return 0
    
    def _process_teams_for_division(self, division: str, team_count: int) -> int:
        """Process all teams in a division"""
        processed_count = 0
        
        try:
            # Click on first team if multiple teams
            if team_count > 1:
                first_team_xpath = '/html/body/div[3]/div/table[3]/tbody/tr/td/table/tbody/tr[2]/td[3]/a'
                first_team_selectors = [
                    (By.XPATH, first_team_xpath),
                    (By.XPATH, '//table[@id="Table4"]//tr[2]//a'),
                    (By.XPATH, '//a[contains(@href, "/reg/team/team")]')
                ]
                
                if not self.interactor.try_multiple_selectors(first_team_selectors, "click"):
                    logger.error("Could not click on first team")
                    return 0
            
            # Process each team
            for team_index in range(1, team_count + 1):
                try:
                    team_result = self._process_single_team(division, team_index)
                    if team_result:
                        processed_count += 1
                    
                    # Navigate to next team if not the last one
                    if team_index < team_count:
                        if not self._navigate_to_next_team(team_index):
                            logger.warning(f"Could not navigate to next team after team {team_index}")
                            break
                            
                except Exception as e:
                    logger.error(f"Error processing team {team_index} in division {division}: {e}")
                    continue
            
            logger.info(f"Processed {processed_count}/{team_count} teams for division {division}")
            return processed_count
            
        except Exception as e:
            logger.error(f"Error processing teams for division {division}: {e}")
            return processed_count
    
    def _process_single_team(self, division: str, team_index: int) -> bool:
        """Process medical forms for a single team"""
        try:
            # Click on Team Roster tab
            roster_tab_xpath = "/html/body/div[3]/div/table[2]/tbody/tr[2]/td/table[1]/tbody/tr[1]/td[1]/table/tbody/tr/td/table/tbody/tr/td[15]/a"
            roster_tab_selectors = [
                (By.XPATH, roster_tab_xpath),
                (By.XPATH, '//a[contains(text(), "Team Roster")]'),
                (By.XPATH, '//td[15]//a')
            ]
            
            if not self.interactor.try_multiple_selectors(roster_tab_selectors, "click"):
                logger.error("Could not click Team Roster tab")
                return False
            
            # Click on Player Application Forms
            forms_button_xpath = '/html/body/div[3]/div/table[2]/tbody/tr[2]/td/table[2]/tbody/tr/td/form/table[3]/tbody/tr/td/input[10]'
            forms_button_selectors = [
                (By.XPATH, forms_button_xpath),
                (By.XPATH, '//input[@value="Player Application Forms"]'),
                (By.XPATH, '//input[contains(@value, "Application")]')
            ]
            
            if not self.interactor.try_multiple_selectors(forms_button_selectors, "click"):
                logger.error("Could not click Player Application Forms button")
                return False
            
            # Get team name
            team_name = self._get_team_name()
            
            # Handle the download window
            success = self._handle_medical_forms_download(division, team_name)
            
            return success
            
        except Exception as e:
            logger.error(f"Error processing single team: {e}")
            return False
    
    def _get_team_name(self) -> str:
        """Get the team name from the page"""
        try:
            team_name_selectors = [
                (By.CSS_SELECTOR, '#main1011 > table:nth-child(4) > tbody > tr:nth-child(2) > td > span.title'),
                (By.XPATH, '//span[@class="title"]'),
                (By.XPATH, '//span[contains(@class, "title")]')
            ]
            
            for by, selector in team_name_selectors:
                try:
                    element = self.driver.find_element(by, selector)
                    return element.text.strip()
                except:
                    continue
            
            return "Unknown Team"
            
        except Exception as e:
            logger.error(f"Error getting team name: {e}")
            return "Unknown Team"
    
    def _handle_medical_forms_download(self, division: str, team_name: str) -> bool:
        """Handle the medical forms download process"""
        try:
            # Switch to download window
            main_page = self.driver.current_window_handle
            
            # Wait for new window
            time.sleep(2)
            
            report_page = None
            for handle in self.driver.window_handles:
                if handle != main_page:
                    report_page = handle
                    break
            
            if not report_page:
                logger.error("No download window found")
                return False
            
            # Switch to report page and close it (this triggers download)
            self.driver.switch_to.window(report_page)
            time.sleep(self.download_delay)
            self.driver.close()
            
            # Switch back to main page
            self.driver.switch_to.window(main_page)
            
            # Process the downloaded file
            return self._process_downloaded_file(division, team_name)
            
        except Exception as e:
            logger.error(f"Error handling medical forms download: {e}")
            return False
    
    def _process_downloaded_file(self, division: str, team_name: str) -> bool:
        """Process the downloaded medical forms file"""
        try:
            # Get download directory from config
            download_dir = self.config.get('download_dir', 'data/downloads') if self.config else 'data/downloads'
            download_path = Path(download_dir).absolute()
            
            # Find the latest receipt file
            receipt_files = list(download_path.glob('receipt*.*'))
            
            if not receipt_files:
                logger.error("No receipt file found in downloads")
                return False
            
            # Get the most recent file
            latest_file = max(receipt_files, key=lambda f: f.stat().st_mtime)
            
            # Create destination directory
            medical_forms_config = self.config.get('medical_forms_config', {}) if self.config else {}
            dest_base = medical_forms_config.get('destination_dir', 'data/medical_forms')
            dest_dir = Path(dest_base) / division
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Create new filename
            dest_filename = f"{team_name} Medical Forms.pdf"
            dest_path = dest_dir / dest_filename
            
            # Move file
            latest_file.replace(dest_path)
            logger.info(f"Moved medical forms to: {dest_path}")
            
            # Upload to Google Drive if configured
            if self.drive_uploader and medical_forms_config.get('upload_to_drive', True):
                success = self._upload_to_google_drive(division, dest_path)
                if success:
                    logger.info(f"Uploaded {dest_filename} to Google Drive")
                else:
                    logger.warning(f"Failed to upload {dest_filename} to Google Drive")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing downloaded file: {e}")
            return False
    
    def _upload_to_google_drive(self, division: str, file_path: Path) -> bool:
        """Upload medical forms to Google Drive"""
        try:
            if not self.drive_uploader:
                return False
            
            # Get folder ID for division
            medical_forms_config = self.config.get('medical_forms_config', {}) if self.config else {}
            drive_folders = medical_forms_config.get('drive_folders', {})
            
            folder_id = drive_folders.get(division)
            if not folder_id:
                logger.warning(f"No Google Drive folder configured for division {division}")
                return False
            
            # Upload file
            file_id = self.drive_uploader.upload_file(str(file_path), folder_id)
            return file_id is not None
            
        except Exception as e:
            logger.error(f"Error uploading to Google Drive: {e}")
            return False
    
    def _navigate_to_next_team(self, current_team_index: int) -> bool:
        """Navigate to the next team"""
        try:
            if current_team_index == 1:
                # First navigation is different
                next_button_xpath = '/html/body/div[3]/div/table[2]/tbody/tr[1]/td/table/tbody/tr/td[4]/a'
            else:
                # Subsequent navigations
                next_button_xpath = '/html/body/div[3]/div/table[2]/tbody/tr[1]/td/table/tbody/tr/td[4]/a[2]'
            
            next_button_selectors = [
                (By.XPATH, next_button_xpath),
                (By.XPATH, '//a[contains(text(), "Next")]'),
                (By.XPATH, '//td[4]//a[last()]')
            ]
            
            return self.interactor.try_multiple_selectors(next_button_selectors, "click")
            
        except Exception as e:
            logger.error(f"Error navigating to next team: {e}")
            return False
    
    def process_all_divisions(self, divisions: List[str] = None) -> Dict[str, Any]:
        """
        Process medical forms for all specified divisions
        
        Args:
            divisions: List of division codes to process (uses default if None)
            
        Returns:
            Dictionary with results for all divisions
        """
        if divisions is None:
            divisions = self.config.get('medical_forms_config', {}).get('divisions', self.default_divisions) if self.config else self.default_divisions
        
        logger.info(f"Processing medical forms for {len(divisions)} divisions")
        
        results = {
            "total_divisions": len(divisions),
            "successful_divisions": 0,
            "total_teams_processed": 0,
            "division_results": []
        }
        
        for division in divisions:
            try:
                logger.info(f"Processing division: {division}")
                
                division_result = self.get_medical_forms_for_division(division)
                results["division_results"].append(division_result)
                
                if division_result["status"] == "success":
                    results["successful_divisions"] += 1
                    results["total_teams_processed"] += division_result["teams_processed"]
                
                # Return to main page between divisions
                if self.main_page_url:
                    self.driver.get(self.main_page_url)
                    time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error processing division {division}: {e}")
                results["division_results"].append({
                    "division": division,
                    "teams_processed": 0,
                    "status": "failed",
                    "error": str(e)
                })
        
        logger.info(f"Medical forms processing complete. Processed {results['total_teams_processed']} teams across {results['successful_divisions']}/{results['total_divisions']} divisions")
        
        return results
    
    def cleanup(self):
        """Clean up any resources"""
        try:
            # Close any additional windows that might be open
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
