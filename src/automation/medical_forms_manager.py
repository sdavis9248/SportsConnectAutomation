"""
Medical Forms Manager for Sports Connect Automation
Handles downloading and organizing player medical forms from Sports Affinity
"""
import os
import glob
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from core.element_interactor import ElementInteractor
from integrations.google_drive import GoogleDriveUploader
from automation.coach_cache_manager import CoachCacheManager

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
        self.drive_folder_cache = {}
        if config and config.get('google_drive_config', {}).get('enabled', False):
            try:
                # Check if credentials file exists first
                creds_file = config.get('google_drive_config', {}).get('credentials_file', 'credentials.json')
                if not os.path.exists(creds_file):
                    logger.warning(f"Google Drive credentials file not found: {creds_file}")
                    logger.info("Skipping Google Drive integration. Run 'python -m integrations.google_drive' to set up.")
                else:
                    self.drive_uploader = GoogleDriveUploader(credentials_file=creds_file)
                    
                    # Check if service was created successfully
                    if hasattr(self.drive_uploader, 'service') and self.drive_uploader.service is not None:
                        logger.info("Google Drive service initialized successfully")
                        
                        # Pre-cache Google Drive folders if needed
                        if config.get('medical_forms_config', {}).get('auto_discover_folders', True):
                            try:
                                self._cache_google_drive_folders()
                            except Exception as cache_error:
                                logger.warning(f"Could not cache Google Drive folders: {cache_error}")
                                # Continue without caching - folders can still be found on-demand
                    else:
                        logger.warning("Google Drive service not initialized - check credentials")
                        
            except Exception as e:
                logger.warning(f"Google Drive integration not available: {e}")

        # Initialize coach cache manager
        self.coach_cache_manager = CoachCacheManager()
    
        # Check if we need to migrate from config
        if config:
            medical_config = config.get('medical_forms_config', {})
            if medical_config.get('coach_cache') and not medical_config.get('coach_cache_migrated'):
                logger.info("Migrating coach cache from config to separate file...")
                migrated = self.coach_cache_manager.migrate_from_config(config)
                logger.info(f"Migrated {migrated} coaches to separate cache file")
    
    def navigate_to_sports_affinity(self) -> bool:
        """Navigate to Sports Affinity using existing login session"""
        logger.info("Navigating to Sports Affinity for medical forms...")
    
        try:
            if self.already_logged_in:
                # We're already logged in, just navigate to Sports Affinity
                logger.info("Using existing login session for Sports Affinity")
                self.driver.get(self.base_url)
            
                # Wait a moment for page to load
                time.sleep(2)
            
                # Step 1: Click "Login with Email" button
                login_button_selectors = [
                    (By.ID, 'loginControl_btnSSOLogin'),
                    (By.XPATH, '//input[@value="Login with Email"]'),
                    (By.XPATH, '//button[contains(text(), "Login")]')
                ]
            
                login_clicked = self.interactor.try_multiple_selectors(login_button_selectors, "click", timeout=5)
                if login_clicked:
                    logger.info("Clicked 'Login with Email' button")
                    time.sleep(2)  # Wait for email to appear
                
                    # Step 2: Click on the prefilled email address
                    email_selectors = [
                        (By.CSS_SELECTOR, 'p.sc-cHGsZl.iuGFAR'),
                        (By.XPATH, '//p[contains(@class, "sc-cHGsZl") and contains(@class, "iuGFAR")]'),
                        (By.XPATH, '//p[contains(text(), "@")]'),  # Fallback to any p tag with @ symbol
                        (By.XPATH, '//p[contains(text(), "davisportal.com")]'),  # More specific fallback
                    ]
                
                    email_clicked = False
                    for by, selector in email_selectors:
                        try:
                            email_element = self.driver.find_element(by, selector)
                            if email_element and '@' in email_element.text:
                                logger.info(f"Found prefilled email: {email_element.text}")
                                email_element.click()
                                email_clicked = True
                                logger.info("Clicked on prefilled email address")
                                break
                        except:
                            continue
                
                    if not email_clicked:
                        logger.warning("Could not find or click prefilled email address")
                        # Try to proceed anyway as it might have auto-logged in
                
                    # Wait for login to complete
                    time.sleep(3)
                else:
                    logger.warning("Could not find 'Login with Email' button - might already be logged in")
            
                # Step 3: Wait for main page to load
                main_form_selectors = [
                    (By.XPATH, '/html/body/form/nav/div[1]/div/a/img'),
                    (By.XPATH, '/html/body/form/nav/div[1]/div/a[2]/img'),
                    (By.ID, 'mainform'),
                    (By.XPATH, '//form[@id="mainform"]'),
                    (By.XPATH, '//nav[contains(@class, "navbar")]'),  # Additional fallback
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
                    # Don't fail immediately - check if we can proceed anyway
                    current_url = self.driver.current_url
                    if "ayso.sportsaffinity.com" in current_url and current_url != self.base_url:
                        logger.info("Appears to be on Sports Affinity site, continuing...")
                        main_page_loaded = True
                    else:
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
            
            # Select season
            season_xpath = "/html/body/div[2]/div/div[2]/div/select"
            try:
                elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, season_xpath))
                )
                select = Select(elem)
                
                # Check if specific season is configured
                medical_season = self.config.get('medical_forms_config', {}).get('medical_forms_season') if self.config else None
                
                if medical_season:
                    # Try to select by visible text
                    try:
                        select.select_by_visible_text(medical_season)
                        logger.info(f"Selected configured season: {medical_season}")
                    except:
                        # If exact match fails, try partial match
                        options = select.options
                        season_found = False
                        for i, option in enumerate(options):
                            if medical_season.lower() in option.text.lower():
                                select.select_by_index(i)
                                logger.info(f"Selected season by partial match: {option.text}")
                                season_found = True
                                break
                        
                        if not season_found:
                            logger.warning(f"Could not find season '{medical_season}', using most recent")
                            select.select_by_index(0)
                else:
                    # No specific season configured, use most recent (index 0)
                    select.select_by_index(0)
                    logger.info("Selected most recent season (index 0)")
                    
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

            # Wait for roster to load
            time.sleep(2)

            # Get team name first
            team_name = self._get_team_name()
        
            # Capture head coach information
            head_coach_info = self._capture_head_coach_info(division, team_name)
            if head_coach_info:
                logger.info(f"Captured head coach info for {team_name}: {head_coach_info['name']}")

            # First, select all players checkbox
            select_all_selectors = [
                (By.ID, 'Select Player'),
                (By.NAME, 'allprint2'),
                (By.XPATH, '//input[@type="checkbox" and @name="allprint2"]'),
                (By.XPATH, '//input[@type="checkbox" and @id="Select Player"]'),
                (By.XPATH, '//input[@type="checkbox" and contains(@onclick, "rosAllPrint")]')
            ]
        
            if not self.interactor.try_multiple_selectors(select_all_selectors, "click"):
                logger.error("Could not click Select All Players checkbox")
                return False
        
            logger.info("Selected all players")
            time.sleep(0.5)  # Brief pause after selecting all
        
            # Next, click on the Print accordion header to expand options
            print_accordion_selectors = [
                (By.XPATH, '//div[contains(@class, "accordion-header") and contains(@class, "button-accordion-header")]//span[contains(text(), "Print")]'),
                (By.XPATH, '//div[contains(@class, "accordion-header")]//span[text()="Print"]'),
                (By.CSS_SELECTOR, 'div.accordion-header.button-accordion-header'),
                (By.XPATH, '//div[contains(@class, "accordion-header") and .//img[contains(@src, "print")]]')
            ]
        
            if not self.interactor.try_multiple_selectors(print_accordion_selectors, "click"):
                logger.error("Could not click Print accordion header")
                return False
        
            # Wait for accordion to expand
            time.sleep(1)
        
            # Now click on Player Application Forms within the expanded accordion
            forms_button_selectors = [
                (By.XPATH, '//input[@value="Player Application Forms"]'),
                (By.XPATH, '//button[contains(text(), "Player Application Forms")]'),
                (By.XPATH, '//a[contains(text(), "Player Application Forms")]'),
                (By.XPATH, '//div[contains(@class, "accordion-content")]//input[contains(@value, "Player Application")]'),
                (By.XPATH, '//div[contains(@class, "accordion-body")]//input[contains(@value, "Player Application")]'),
                (By.XPATH, '//*[contains(text(), "Player Application Forms")]')
            ]
        
            if not self.interactor.try_multiple_selectors(forms_button_selectors, "click"):
                logger.error("Could not click Player Application Forms button")
                return False
        
            # Handle the download window
            success = self._handle_medical_forms_download(division, team_name)
        
            return success
        
        except Exception as e:
            logger.error(f"Error processing single team: {e}")
            return False

    def _capture_head_coach_info(self, division: str, team_name: str) -> Optional[Dict[str, str]]:
        """Capture head coach information and cache it"""
        try:
            # Find the row containing "Head Coach"
            head_coach_row_selectors = [
                (By.XPATH, '//tr[td[contains(text(), "Head Coach")]]'),
                (By.XPATH, '//tr[td[@id[starts-with(., "row5_")] and contains(text(), "Head Coach")]]'),
                (By.XPATH, '//tr[.//td[text()="Head Coach"]]')
            ]
        
            for by, selector in head_coach_row_selectors:
                try:
                    row = self.driver.find_element(by, selector)
                    if row:
                        # Extract coach name from the row (typically in column 6)
                        coach_name_elem = row.find_element(By.XPATH, './/td[@id[starts-with(., "row6_")]]')
                        coach_name = coach_name_elem.text.strip() if coach_name_elem else "Unknown"
                    
                        # Get the onclick value from the row to get the admin ID
                        onclick_value = row.get_attribute('onclick')
                        admin_id = None
                        if onclick_value and 'rosAdminClick' in onclick_value:
                            # Extract ID from rosAdminClick('ID')
                            import re
                            match = re.search(r"rosAdminClick\('([^']+)'\)", onclick_value)
                            if match:
                                admin_id = match.group(1)
                    
                        # Click on the row to get coach details
                        row.click()
                        time.sleep(2)  # Wait for details to load
                    
                        # Look for email in the details page
                        email = self._extract_coach_email()
                    
                        if email:
                            # Cache the coach information
                            self._cache_coach_info(division, team_name, coach_name, email)
                        
                            # Navigate back to roster
                            self.driver.back()
                            time.sleep(1)
                        
                            # Re-click Team Roster tab
                            roster_tab_selectors = [
                                (By.XPATH, '//a[contains(text(), "Team Roster")]'),
                                (By.XPATH, '//td[15]//a')
                            ]
                            self.interactor.try_multiple_selectors(roster_tab_selectors, "click")
                            time.sleep(1)
                        
                            return {
                                'name': coach_name,
                                'email': email,
                                'admin_id': admin_id
                            }
                    
                        break
                    
                except Exception as e:
                    logger.debug(f"Could not find head coach with selector {selector}: {e}")
                    continue
        
            logger.warning(f"Could not capture head coach info for {team_name}")
            return None
        
        except Exception as e:
            logger.error(f"Error capturing head coach info: {e}")
            return None

    def _extract_coach_email(self) -> Optional[str]:
        """Extract email from coach details page"""
        try:
            # Look for email input field first (most reliable)
            email_input_selectors = [
                (By.ID, 'email'),
                (By.NAME, 'email'),
                (By.XPATH, '//input[@id="email"]'),
                (By.XPATH, '//input[@name="email"]'),
                (By.XPATH, '//input[@type="text" and @name="email"]'),
                (By.CSS_SELECTOR, 'input#email'),
                (By.CSS_SELECTOR, 'input[name="email"]')
            ]
        
            for by, selector in email_input_selectors:
                try:
                    elem = self.driver.find_element(by, selector)
                    email_value = elem.get_attribute('value')
                    if email_value and '@' in email_value:
                        return email_value.strip()
                except:
                    continue
        
            # Fallback to other methods if input field not found
            email_selectors = [
                (By.XPATH, '//a[contains(@href, "mailto:")]'),
                (By.XPATH, '//td[contains(text(), "@")]'),
                (By.XPATH, '//span[contains(text(), "@")]'),
                (By.XPATH, '//*[contains(@class, "email") and contains(text(), "@")]')
            ]
        
            for by, selector in email_selectors:
                try:
                    elem = self.driver.find_element(by, selector)
                    text = elem.text.strip()
                
                    # Extract email from text or href
                    if '@' in text:
                        # Simple email extraction
                        import re
                        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
                        if email_match:
                            return email_match.group(0)
                
                    # Check href for mailto
                    href = elem.get_attribute('href')
                    if href and 'mailto:' in href:
                        return href.replace('mailto:', '').strip()
                    
                except:
                    continue
        
            logger.warning("Could not find email on coach details page")
            return None
        
        except Exception as e:
            logger.error(f"Error extracting coach email: {e}")
            return None

    def _cache_coach_info(self, division: str, team_name: str, coach_name: str, email: str):
        """Cache coach information using the coach cache manager"""
        try:
            # Add coach to cache
            cache_key = self.coach_cache_manager.add_coach(
                division=division,
                team_name=team_name,
                coach_name=coach_name,
                coach_email=email,
                additional_info={
                    'source': 'medical_forms_download',
                    'captured_date': datetime.now().isoformat()
                }
            )
        
            logger.info(f"Cached coach info with key: {cache_key}")
        
        except Exception as e:
            logger.error(f"Error caching coach info: {e}")
    
    def _get_team_name(self) -> str:
        """Get the team name from the page"""
        try:
            # Wait a moment for the page to fully load
            time.sleep(1)
            
            team_name_selectors = [
                # Original selector from SportsAffinityMedicalForms.py
                (By.CSS_SELECTOR, '#main1011 > table:nth-child(4) > tbody > tr:nth-child(2) > td > span.title'),
                # Fallback selectors
                (By.CSS_SELECTOR, 'span.title'),
                (By.XPATH, '//span[@class="title"]'),
                (By.CSS_SELECTOR, '.title'),
                (By.XPATH, '//span[contains(@class, "title")]'),
                (By.CSS_SELECTOR, '#main1011 span.title'),
                (By.XPATH, '//*[@id="main1011"]//span[@class="title"]')
            ]
            
            for by, selector in team_name_selectors:
                try:
                    element = self.driver.find_element(by, selector)
                    team_name = element.text.strip()
                    if team_name:  # Only return if we got actual text
                        logger.debug(f"Found team name: {team_name}")
                        return team_name
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {str(e)}")
                    continue
            
            # If we still haven't found it, try to log the page source for debugging
            logger.warning("Could not find team name with standard selectors")
            
            # Try to find any span with class title for debugging
            try:
                all_titles = self.driver.find_elements(By.CSS_SELECTOR, 'span.title')
                if all_titles:
                    logger.info(f"Found {len(all_titles)} span.title elements")
                    for i, title in enumerate(all_titles):
                        logger.info(f"Title {i}: {title.text}")
                        if title.text.strip():
                            return title.text.strip()
            except:
                pass
            
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
        
            # Get season from config
            medical_forms_config = self.config.get('medical_forms_config', {}) if self.config else {}
            medical_forms_season = medical_forms_config.get('medical_forms_season', '')
        
            # Extract last 6 characters as season (e.g., "Fall24" from "2024 Fall24")
            if medical_forms_season and len(medical_forms_season) >= 6:
                season = medical_forms_season[-6:]
                logger.info(f"Using season '{season}' from config value '{medical_forms_season}'")
            else:
                # Fallback to current year and season
                from datetime import datetime
                current_month = datetime.now().month
                year = datetime.now().strftime("%y")
                season_name = "Fall" if current_month >= 6 else "Spring"
                season = f"{season_name}{year}"
                logger.warning(f"No valid season in config, using default: {season}")
        
            # Create destination directory with season
            dest_base = medical_forms_config.get('destination_dir', 'data/medical_forms')
            dest_dir = Path(dest_base) / season / division
            dest_dir.mkdir(parents=True, exist_ok=True)
        
            # Create new filename
            dest_filename = f"{team_name} Medical Forms.pdf"
            dest_path = dest_dir / dest_filename
        
            # Move file
            latest_file.replace(dest_path)
            logger.info(f"Moved medical forms to: {dest_path}")
        
            # Upload to Google Drive if configured
            if self.drive_uploader and medical_forms_config.get('upload_to_drive', True):
                success = self._upload_to_google_drive(division, dest_path, season)
                if success:
                    logger.info(f"Uploaded {dest_filename} to Google Drive")
                else:
                    logger.warning(f"Failed to upload {dest_filename} to Google Drive")
        
            return True
        
        except Exception as e:
            logger.error(f"Error processing downloaded file: {e}")
            return False
    
    def _cache_google_drive_folders(self):
        """Pre-cache all Google Drive folder IDs for divisions and update config"""
        try:
            if not self.drive_uploader:
                return
        
            logger.info("Caching Google Drive folder IDs for divisions...")
        
            # Get current config
            medical_forms_config = self.config.get('medical_forms_config', {}) if self.config else {}
            drive_folders = medical_forms_config.get('drive_folders', {})
        
            # Track if we found any new folders
            new_folders_found = False
        
            # Try to use the list_folders method if available
            try:
                if hasattr(self.drive_uploader, 'list_folders'):
                    # Use the new list_folders method
                    all_folders = self.drive_uploader.list_folders()
                else:
                    # Fall back to list_files and filter
                    all_files = self.drive_uploader.list_files()
                    all_folders = [f for f in all_files if f.get('mimeType') == 'application/vnd.google-apps.folder']
            
                # Match division names
                for folder in all_folders:
                    folder_name = folder.get('name', '')
                    folder_id = folder.get('id', '')
                
                    # Check if folder name matches any division pattern
                    if folder_name in self.default_divisions:
                        self.drive_folder_cache[folder_name] = folder_id
                        logger.debug(f"Cached folder ID for {folder_name}: {folder_id}")
                    
                        # Update config if this is a new folder or the ID has changed
                        if drive_folders.get(folder_name) != folder_id:
                            drive_folders[folder_name] = folder_id
                            new_folders_found = True
                            logger.info(f"Updated folder ID for {folder_name}: {folder_id}")
            
                logger.info(f"Cached {len(self.drive_folder_cache)} division folder IDs")
            
            except Exception as e:
                logger.debug(f"Could not use list methods: {e}")
            
                # Fallback to direct service access if available
                if hasattr(self.drive_uploader, 'service') and self.drive_uploader.service is not None:
                    logger.debug("Using direct service access for folder caching")
                    service = self.drive_uploader.service
                    query = "mimeType='application/vnd.google-apps.folder'"
                
                    page_token = None
                
                    while True:
                        try:
                            response = service.files().list(
                                q=query,
                                pageSize=100,
                                spaces='drive',
                                fields='nextPageToken, files(id, name)',
                                pageToken=page_token
                            ).execute()
                        
                            for file in response.get('files', []):
                                folder_name = file.get('name', '')
                                folder_id = file.get('id', '')
                            
                                # Check if folder name matches any division pattern
                                if folder_name in self.default_divisions:
                                    self.drive_folder_cache[folder_name] = folder_id
                                    logger.debug(f"Cached folder ID for {folder_name}: {folder_id}")
                                
                                    # Update config if this is a new folder or the ID has changed
                                    if drive_folders.get(folder_name) != folder_id:
                                        drive_folders[folder_name] = folder_id
                                        new_folders_found = True
                                        logger.info(f"Updated folder ID for {folder_name}: {folder_id}")
                        
                            page_token = response.get('nextPageToken', None)
                            if page_token is None:
                                break
                            
                        except Exception as e:
                            logger.error(f"Error caching Google Drive folders: {e}")
                            break
                
                    logger.info(f"Cached {len(self.drive_folder_cache)} division folder IDs")
        
            # Update config if we found new folders
            if new_folders_found and self.config:
                try:
                    # Update the config in memory
                    self.config.set('medical_forms_config.drive_folders', drive_folders)
                
                    # Save the updated config to file
                    if self.config.save_config():
                        logger.info("Updated config.json with discovered Google Drive folder IDs")
                    else:
                        logger.warning("Failed to save updated folder IDs to config.json")
                    
                except Exception as e:
                    logger.error(f"Error updating config with folder IDs: {e}")
        
            # Log which divisions were found
            if self.drive_folder_cache:
                logger.info(f"Found folders for divisions: {', '.join(sorted(self.drive_folder_cache.keys()))}")
        
            # Log which divisions are missing  
            missing_divisions = set(self.default_divisions) - set(self.drive_folder_cache.keys())
            if missing_divisions:
                logger.warning(f"No folders found for divisions: {', '.join(sorted(missing_divisions))}")
            
                # Show placeholder entries that need to be updated
                placeholders = [div for div in missing_divisions if drive_folders.get(div, '').startswith('folder_id_for_')]
                if placeholders:
                    logger.info(f"Divisions with placeholder IDs that need folders created: {', '.join(sorted(placeholders))}")
        
        except Exception as e:
            logger.error(f"Error in folder caching: {e}")
    
    def _find_google_drive_folder(self, division: str) -> Optional[str]:
        """Find Google Drive folder for division by searching"""
        try:
            if not self.drive_uploader:
                return None
            
            # Check if the drive uploader has a service attribute
            if not hasattr(self.drive_uploader, 'service') or self.drive_uploader.service is None:
                logger.warning("Google Drive service not initialized")
                return None
            
            # Search for folders in Google Drive
            service = self.drive_uploader.service
            
            # Query for folders only
            query = "mimeType='application/vnd.google-apps.folder'"
            
            folders = []
            page_token = None
            
            while True:
                try:
                    response = service.files().list(
                        q=query,
                        spaces='drive',
                        fields='nextPageToken, files(id, name)',
                        pageToken=page_token
                    ).execute()
                    
                    for file in response.get('files', []):
                        folders.append({
                            'name': file.get('name'),
                            'id': file.get('id')
                        })
                    
                    page_token = response.get('nextPageToken', None)
                    if page_token is None:
                        break
                        
                except Exception as e:
                    logger.error(f"Error searching Google Drive: {e}")
                    break
            
            # Find folder matching division name
            for folder in folders:
                if folder['name'] == division:
                    logger.info(f"Found Google Drive folder for {division}: {folder['id']}")
                    
                    # Optionally cache this in config for future use
                    if self.config:
                        medical_forms_config = self.config.get('medical_forms_config', {})
                        if 'drive_folders' not in medical_forms_config:
                            medical_forms_config['drive_folders'] = {}
                        medical_forms_config['drive_folders'][division] = folder['id']
                    
                    return folder['id']
            
            logger.warning(f"No folder named '{division}' found in Google Drive")
            return None
            
        except Exception as e:
            logger.error(f"Error finding Google Drive folder: {e}")
            return None
 
    def _upload_to_google_drive(self, division: str, file_path: Path, season: str = None) -> bool:
        """Upload medical forms to Google Drive"""
        try:
            if not self.drive_uploader:
                return False
        
            # Get folder ID for division
            medical_forms_config = self.config.get('medical_forms_config', {}) if self.config else {}
            drive_folders = medical_forms_config.get('drive_folders', {})
        
            # Try configured folder ID first
            folder_id = drive_folders.get(division)
        
            # Then try cache
            if not folder_id and division in self.drive_folder_cache:
                folder_id = self.drive_folder_cache[division]
                logger.info(f"Using cached folder ID for {division}")
        
            # Finally try searching - look for season/division structure
            if not folder_id:
                logger.info(f"No folder ID configured or cached for {division}, searching Google Drive...")
            
                # First, find or create season folder
                season_folder_id = None
                if season:
                    season_folder_id = self._find_or_create_season_folder(season)
            
                # Then find or create division folder within season folder
                folder_id = self._find_or_create_division_folder(division, season_folder_id)
            
                if not folder_id:
                    logger.warning(f"Could not find or create Google Drive folder for {division}")
                    return False
        
            # Upload file
            file_id = self.drive_uploader.upload_file(str(file_path), folder_id)
            return file_id is not None
        
        except Exception as e:
            logger.error(f"Error uploading to Google Drive: {e}")
            return False

    def _find_or_create_season_folder(self, season: str) -> Optional[str]:
        """Find or create a season folder in Google Drive"""
        try:
            if not self.drive_uploader or not hasattr(self.drive_uploader, 'service'):
                return None
        
            service = self.drive_uploader.service
        
            # Search for existing season folder
            query = f"name='{season}' and mimeType='application/vnd.google-apps.folder'"
            response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        
            folders = response.get('files', [])
            if folders:
                logger.info(f"Found existing season folder '{season}': {folders[0]['id']}")
                return folders[0]['id']
        
            # Create season folder if it doesn't exist
            logger.info(f"Creating new season folder: {season}")
            folder_metadata = {
                'name': season,
                'mimeType': 'application/vnd.google-apps.folder'
            }
        
            # If medical forms parent folder is configured, use it
            medical_forms_config = self.config.get('medical_forms_config', {}) if self.config else {}
            parent_folder_id = medical_forms_config.get('drive_parent_folder_id')
            if parent_folder_id:
                folder_metadata['parents'] = [parent_folder_id]
        
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            logger.info(f"Created season folder '{season}': {folder.get('id')}")
            return folder.get('id')
        
        except Exception as e:
            logger.error(f"Error finding/creating season folder: {e}")
            return None

    def _find_or_create_division_folder(self, division: str, parent_folder_id: str = None) -> Optional[str]:
        """Find or create a division folder in Google Drive"""
        try:
            if not self.drive_uploader or not hasattr(self.drive_uploader, 'service'):
                return None
        
            service = self.drive_uploader.service
        
            # Build query
            query_parts = [f"name='{division}'", "mimeType='application/vnd.google-apps.folder'"]
            if parent_folder_id:
                query_parts.append(f"'{parent_folder_id}' in parents")
        
            query = " and ".join(query_parts)
            response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        
            folders = response.get('files', [])
            if folders:
                logger.info(f"Found existing division folder '{division}': {folders[0]['id']}")
                # Cache it for future use
                self.drive_folder_cache[division] = folders[0]['id']
                return folders[0]['id']
        
            # Create division folder if it doesn't exist
            logger.info(f"Creating new division folder: {division}")
            folder_metadata = {
                'name': division,
                'mimeType': 'application/vnd.google-apps.folder'
            }
        
            if parent_folder_id:
                folder_metadata['parents'] = [parent_folder_id]
        
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            folder_id = folder.get('id')
            logger.info(f"Created division folder '{division}': {folder_id}")
        
            # Cache it for future use
            self.drive_folder_cache[division] = folder_id
            return folder_id
        
        except Exception as e:
            logger.error(f"Error finding/creating division folder: {e}")
            return None
    
    def _navigate_to_next_team(self, current_team_index: int) -> bool:
        """Navigate to the next team"""
        try:
            # if current_team_index == 1:
            #     # First navigation - use standard next link
            #     next_button_selectors = [
            #         (By.XPATH, '/html/body/div[3]/div/table[2]/tbody/tr[1]/td/table/tbody/tr/td[4]/a'),
            #         (By.XPATH, '//a[contains(text(), "Next")]'),
            #         (By.XPATH, '//td[4]//a[contains(text(), "Next")]')
            #     ]
            # else:
                # Subsequent navigations - use the arrow link
            next_button_selectors = [
                (By.CSS_SELECTOR, 'a.left-arrow[href*="record="]'),
                (By.XPATH, '//a[@class="left-arrow" and contains(@href, "record=")]'),
                (By.XPATH, f'//a[@class="left-arrow" and contains(@href, "record={current_team_index + 1}")]'),
                # Fallback to original selectors
                (By.XPATH, '/html/body/div[3]/div/table[2]/tbody/tr[1]/td/table/tbody/tr/td[4]/a[2]'),
                (By.XPATH, '//td[4]//a[last()]')
            ]
        
            clicked = self.interactor.try_multiple_selectors(next_button_selectors, "click")
        
            if clicked:
                logger.info(f"Navigated to team {current_team_index + 1}")
                # Wait for the page to load
                time.sleep(2)
                return True
            else:
                logger.warning(f"Could not navigate to next team from index {current_team_index}")
                return False
            
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
    
    def list_google_drive_folders(self) -> List[Dict[str, str]]:
        """List all Google Drive folders (useful for finding folder IDs)"""
        try:
            if not self.drive_uploader:
                logger.error("Google Drive uploader not initialized")
                return []
            
            logger.info("Listing all Google Drive folders...")
            
            # Use the list_folders method if available
            if hasattr(self.drive_uploader, 'list_folders'):
                all_folders = self.drive_uploader.list_folders()
            else:
                # Fallback to list_files and filter
                all_files = self.drive_uploader.list_files()
                all_folders = [f for f in all_files if f.get('mimeType') == 'application/vnd.google-apps.folder']
            
            # Format the results
            formatted_folders = []
            for folder in all_folders:
                folder_info = {
                    'name': folder.get('name', ''),
                    'id': folder.get('id', ''),
                    'parents': folder.get('parents', [])
                }
                formatted_folders.append(folder_info)
            
            # Sort by name
            formatted_folders.sort(key=lambda x: x['name'])
            
            logger.info(f"Found {len(formatted_folders)} folders in Google Drive")
            
            # Log division folders
            division_folders = [f for f in formatted_folders if f['name'] in self.default_divisions]
            if division_folders:
                logger.info("Division folders found:")
                for folder in division_folders:
                    logger.info(f"  - {folder['name']}: {folder['id']}")
            else:
                logger.warning("No division folders found in Google Drive")
                logger.info("You may need to create folders named: " + ", ".join(self.default_divisions))
            
            return formatted_folders
            
        except Exception as e:
            logger.error(f"Error listing folders: {e}")
            return []
    
    def setup_google_drive(self) -> bool:
        """
        Manually set up Google Drive integration
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Setting up Google Drive integration...")
            
            # Check for credentials file
            creds_file = 'credentials.json'
            if self.config:
                creds_file = self.config.get('google_drive_config', {}).get('credentials_file', 'credentials.json')
            
            if not os.path.exists(creds_file):
                logger.error(f"Google Drive credentials file not found: {creds_file}")
                logger.info("To set up Google Drive:")
                logger.info("1. Go to https://console.cloud.google.com/")
                logger.info("2. Create a project and enable Google Drive API")
                logger.info("3. Create OAuth 2.0 credentials")
                logger.info("4. Download the credentials as 'credentials.json'")
                logger.info("5. Run: python -m integrations.google_drive")
                return False
            
            # Try to create uploader
            self.drive_uploader = GoogleDriveUploader(credentials_file=creds_file)
            
            # Check if service was created
            if hasattr(self.drive_uploader, 'service') and self.drive_uploader.service is not None:
                logger.info("Google Drive service initialized successfully")
                
                # Try to list files as a test
                test_files = self.drive_uploader.list_files()
                logger.info(f"Google Drive connection test successful - found {len(test_files)} files")
                
                # Cache folders if configured
                if self.config and self.config.get('medical_forms_config', {}).get('auto_discover_folders', True):
                    self._cache_google_drive_folders()
                
                return True
            else:
                logger.error("Google Drive service not initialized")
                return False
                
        except Exception as e:
            logger.error(f"Error setting up Google Drive: {e}")
            return False
    
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