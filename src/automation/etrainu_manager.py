"""
ETrainU Manager for Sports Connect Automation
Uses Sports Connect SSO authentication just like Sports Affinity integration
"""
import logging
import time
import os
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from core.element_interactor import ElementInteractor

logger = logging.getLogger(__name__)

class ETrainUManager:
    """Handles ETrainU operations using Sports Connect SSO authentication"""
    
    def __init__(self, driver, config=None, already_logged_in=False):
        """
        Initialize ETrainU Manager
        
        Args:
            driver: Selenium WebDriver instance (from SportsConnectAutomation)
            config: Configuration manager instance
            already_logged_in: Whether we're already logged into Sports Connect (default True)
        """
        self.driver = driver
        self.config = config
        self.interactor = ElementInteractor(driver)
        self.wait = WebDriverWait(driver, 10)
        self.download_delay = config.get('download_delay', 5) if config else 5
        self.organization_id = config.get('organization_id') if config else None
        self.already_logged_in = already_logged_in
        
        # ETrainU specific configuration
        self.base_url = self._get_etrainu_url()
        self.main_page_handle = None
        self.main_page_url = None
        
        # Storage for scraped events
        self.events = []
        
        # Region filter from config
        etrainu_config = config.get('etrainu_config', {}) if config else {}
        self.region_filter = etrainu_config.get('region_filter', 'Region 58')
    
    def _get_etrainu_url(self):
        """Get ETrainU URL using the correct AYSO BlueShomrero format"""
        # Base URL from the JavaScript you found
        base_url = 'https://ayso.bluesombrero.com/Default.aspx'
        
        # Get volunteer ID from config if available
        etrainu_config = self.config.get('etrainu_config', {}) if self.config else {}
        volunteer_id = etrainu_config.get('volunteer_id', '0')  # Default to '0' if not specified

        
        # Build query string parameters as shown in the JavaScript
        query_params = {
            'tabid': '960474',
            'userid': '0', 
            'USYSState': '',
            'volunteerid': str(volunteer_id),
            'isUSYSeTrainU': 'False'
        }
        
        # Build the full URL
        query_string = '&'.join([f"{key}={value}" for key, value in query_params.items()])
        full_url = f"{base_url}?{query_string}"
        
        logger.debug(f"ETrainU URL: {full_url}")
        return full_url
    
    def navigate_to_etrainu(self) -> bool:
        """Navigate to ETrainU using existing Sports Connect login session"""
        logger.info("Navigating to ETrainU using Sports Connect SSO...")
        
        try:
            if self.already_logged_in:
                logger.info("Using existing Sports Connect login session for ETrainU")
                
                # Use the correct AYSO BlueShomrero URL format
                etrainu_url = self._get_etrainu_url()
                logger.info(f"Navigating to: {etrainu_url}")
                
                self.driver.get(etrainu_url)
                
                # Wait for page to load and handle potential redirects
                time.sleep(5)  # Give more time for the redirect chain
                
                # Check current URL to see where we ended up
                current_url = self.driver.current_url
                logger.info(f"Current URL after navigation: {current_url}")
                
                # Look for ETrainU indicators in the page
                # etrainu_indicators = [
                #     # ETrainU specific elements
                #     (By.XPATH, '//title[contains(text(), "ETrainU")]'),
                #     (By.XPATH, '//title[contains(text(), "Training")]'),
                #     (By.XPATH, '//div[contains(@class, "etrainu")]'),
                #     (By.XPATH, '//img[contains(@alt, "ETrainU")]'),
                #     (By.XPATH, '//h1[contains(text(), "Training")]'),
                #     (By.XPATH, '//div[contains(@class, "event")]'),
                #     # AYSO training page elements
                #     (By.XPATH, '//h1[contains(text(), "AYSO Training")]'),
                #     (By.XPATH, '//div[contains(text(), "Course")]'),
                #     (By.XPATH, '//button[contains(@class, "enrol")]'),
                #     (By.XPATH, '//div[contains(@class, "training")]'),
                #     # Generic training/course elements
                #     (By.XPATH, '//div[contains(text(), "Enroll")]'),
                #     (By.XPATH, '//table[contains(@class, "course")]'),
                #     (By.XPATH, '//div[contains(@class, "session")]')
                # ]
                
                # # Wait for ETrainU page to load
                # etrainu_loaded = False
                # page_source = self.driver.page_source.lower()
                
                # # First check URL patterns
                # if any(pattern in current_url.lower() for pattern in ['etrainu', 'training', 'course']):
                #     etrainu_loaded = True
                #     logger.info("ETrainU detected via URL pattern")
                
                # # Then check page content
                # if not etrainu_loaded:
                #     content_indicators = ['etrainu', 'training course', 'enroll', 'certification', 'ayso training']
                #     if any(indicator in page_source for indicator in content_indicators):
                #         etrainu_loaded = True
                #         logger.info("ETrainU detected via page content")
                
                # # Finally check for specific elements
                # if not etrainu_loaded:
                #     for by, selector in etrainu_indicators:
                #         try:
                #             WebDriverWait(self.driver, 5).until(
                #                 EC.presence_of_element_located((by, selector))
                #             )
                #             etrainu_loaded = True
                #             logger.info(f"ETrainU detected via element: {selector}")
                #             break
                #         except TimeoutException:
                #             continue
                
                # if etrainu_loaded:
                #     # Store page info for navigation
                #     self.main_page_url = self.driver.current_url
                #     self.main_page_handle = self.driver.current_window_handle
                    
                #     logger.info("Successfully navigated to ETrainU training system")
                #     return True
                # else:
                #     logger.warning("Could not confirm ETrainU page loaded properly")
                #     logger.info(f"Current URL: {current_url}")
                #     logger.info("Page title: " + self.driver.title)
                    
                #     # Save page source for debugging
                #     try:
                #         debug_file = f"etrainu_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                #         with open(debug_file, 'w', encoding='utf-8') as f:
                #             f.write(self.driver.page_source)
                #         logger.info(f"Saved page source to {debug_file} for debugging")
                #     except Exception as e:
                #         logger.warning(f"Could not save debug file: {e}")
                    
                #     return False
                return True
            else:
                logger.error("Not logged into Sports Connect - cannot access ETrainU via SSO")
                return False
                
        except Exception as e:
            logger.error(f"Error navigating to ETrainU: {e}")
            return False
    
    def scrape_live_events(self, region_filter=None) -> List[Dict]:
        """Scrape events directly from the live ETrainU site"""
        logger.info("Scraping live events from ETrainU...")
        
        events = []
        
        try:
            # Apply region filter if needed
            if region_filter or self.region_filter:
                filter_to_use = region_filter or self.region_filter
                self._apply_region_filter(filter_to_use)
                time.sleep(2)
            
            # Get the current page source and parse
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Extract events using the same parsing logic from the scraper
            event_containers = soup.find_all('div', class_='event')
            logger.info(f"Found {len(event_containers)} event containers")
            
            for event_container in event_containers:
                event_data = self._extract_event_data(event_container)
                if event_data:
                    # Add live scraping metadata
                    event_data['scraped_live'] = True
                    event_data['scraped_at'] = datetime.now().isoformat()
                    event_data['source_url'] = self.driver.current_url
                    events.append(event_data)
            
            self.events = events
            logger.info(f"Successfully scraped {len(events)} live events from ETrainU")
            
            return events
            
        except Exception as e:
            logger.error(f"Error scraping live events from ETrainU: {e}")
            return []
    
    def _apply_region_filter(self, region_filter):
        """Apply region filter on ETrainU site"""
        try:
            logger.info(f"Applying region filter: {region_filter}")
            
            # Look for various region filter elements
            region_selectors = [
                (By.NAME, "region"),
                (By.ID, "region-filter"),
                (By.XPATH, "//select[contains(@class, 'region')]"),
                (By.XPATH, "//select[contains(@name, 'region')]")
            ]
            
            for by, selector in region_selectors:
                try:
                    region_element = self.driver.find_element(by, selector)
                    select = Select(region_element)
                    
                    # Try different ways to select the region
                    try:
                        select.select_by_visible_text(region_filter)
                        logger.info(f"Successfully applied region filter: {region_filter}")
                        return True
                    except:
                        # Try partial match
                        for option in select.options:
                            if region_filter.lower() in option.text.lower():
                                select.select_by_visible_text(option.text)
                                logger.info(f"Applied region filter (partial match): {option.text}")
                                return True
                    
                except NoSuchElementException:
                    continue
            
            # If no dropdown found, look for region links or buttons
            region_link_selectors = [
                (By.XPATH, f"//a[contains(text(), '{region_filter}')]"),
                (By.XPATH, f"//button[contains(text(), '{region_filter}')]"),
                (By.XPATH, f"//div[contains(text(), '{region_filter}')][@onclick or @click]")
            ]
            
            for by, selector in region_link_selectors:
                try:
                    region_element = self.driver.find_element(by, selector)
                    region_element.click()
                    logger.info(f"Clicked region filter link: {region_filter}")
                    return True
                except NoSuchElementException:
                    continue
            
            logger.warning(f"Could not find region filter for: {region_filter}")
            return False
            
        except Exception as e:
            logger.error(f"Error applying region filter: {e}")
            return False
    
    def _extract_event_data(self, event_container) -> Optional[Dict]:
        """Extract data from a single event container (reuse scraper logic)"""
        try:
            # Import the extraction logic from the scraper
            from automation.etrainu_scraper import ETrainUEventScraper
            
            # Create a temporary scraper instance just for the extraction method
            temp_scraper = ETrainUEventScraper()
            return temp_scraper._extract_event_data(event_container)
            
        except Exception as e:
            logger.error(f"Error extracting event data: {e}")
            return None
    
    def auto_enroll_volunteer(self, volunteer_info: Dict, event_data: Dict) -> Dict:
        """
        Automatically enroll a volunteer in a course on the live ETrainU site
        
        Args:
            volunteer_info: Dictionary with volunteer details (name, email, phone, etc.)
            event_data: Event/course information from scraped data
            
        Returns:
            Dictionary with enrollment result
        """
        logger.info(f"Auto-enrolling {volunteer_info.get('name', 'Unknown')} in {event_data.get('title', 'Unknown Course')}")
        
        try:
            # Get enrollment information from event data
            enroll_info = event_data.get('enroll_info', {})
            event_id = enroll_info.get('data_event', '')
            session_id = enroll_info.get('data_session', '')
            
            if not event_id:
                logger.error("Missing event ID for enrollment")
                return {'success': False, 'error': 'Missing event ID'}
            
            # Click the enrollment button
            enroll_button = self.driver.find_element(
                By.XPATH, 
                f"//button[@data-event='{event_id}' and @data-session='{session_id}']"
            )
            enroll_button.click()
            time.sleep(2)
            
            # Fill enrollment form
            success = self._fill_enrollment_form(volunteer_info)
            
            if success:
                # Submit the enrollment
                submit_selectors = [
                    (By.XPATH, "//input[@type='submit']"),
                    (By.XPATH, "//button[contains(text(), 'Enroll')]"),
                    (By.XPATH, "//button[contains(text(), 'Submit')]")
                ]
                
                submitted = self.interactor.try_multiple_selectors(submit_selectors, "click")
                
                if submitted:
                    time.sleep(3)
                    
                    # Check for success indicators
                    success_indicators = [
                        "successfully enrolled",
                        "enrollment complete",
                        "registration confirmed",
                        "thank you"
                    ]
                    
                    page_text = self.driver.page_source.lower()
                    enrollment_successful = any(indicator in page_text for indicator in success_indicators)
                    
                    if enrollment_successful:
                        logger.info(f"Successfully enrolled {volunteer_info.get('name', 'volunteer')}")
                        return {
                            'success': True,
                            'volunteer_name': volunteer_info.get('name'),
                            'course_title': event_data.get('title'),
                            'event_id': event_id,
                            'session_id': session_id,
                            'enrollment_timestamp': datetime.now().isoformat()
                        }
                    else:
                        return {'success': False, 'error': 'Enrollment submission may have failed'}
                else:
                    return {'success': False, 'error': 'Could not submit enrollment form'}
            else:
                return {'success': False, 'error': 'Could not fill enrollment form'}
                
        except NoSuchElementException as e:
            logger.error(f"Enrollment button or form element not found: {e}")
            return {'success': False, 'error': f'Element not found: {e}'}
        except Exception as e:
            logger.error(f"Auto-enrollment error: {e}")
            return {'success': False, 'error': str(e)}
    
    def _fill_enrollment_form(self, volunteer_info: Dict) -> bool:
        """Fill the enrollment form with volunteer information"""
        try:
            logger.info("Filling enrollment form...")
            
            # Common form field mappings
            field_mappings = [
                ('name', ['name', 'full_name', 'volunteer_name']),
                ('first_name', ['first_name', 'fname']),
                ('last_name', ['last_name', 'lname']),
                ('email', ['email', 'email_address']),
                ('phone', ['phone', 'telephone', 'cell_phone']),
                ('ayso_id', ['ayso_id', 'volunteer_id', 'member_id'])
            ]
            
            filled_fields = 0
            
            for volunteer_key, form_field_names in field_mappings:
                if volunteer_key in volunteer_info and volunteer_info[volunteer_key]:
                    value = volunteer_info[volunteer_key]
                    
                    # Try to find and fill the field
                    for field_name in form_field_names:
                        selectors_to_try = [
                            (By.NAME, field_name),
                            (By.ID, field_name),
                            (By.XPATH, f"//input[@placeholder='{field_name.replace('_', ' ').title()}']")
                        ]
                        
                        field_filled = False
                        for by, selector in selectors_to_try:
                            try:
                                field_element = self.driver.find_element(by, selector)
                                field_element.clear()
                                field_element.send_keys(value)
                                logger.debug(f"Filled {field_name} with {value}")
                                filled_fields += 1
                                field_filled = True
                                break
                            except NoSuchElementException:
                                continue
                        
                        if field_filled:
                            break
            
            logger.info(f"Successfully filled {filled_fields} form fields")
            return filled_fields > 0
            
        except Exception as e:
            logger.error(f"Error filling enrollment form: {e}")
            return False
    
    def save_events_to_json(self, filename=None) -> str:
        """Save scraped events to JSON file"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"etrainu_live_events_{timestamp}.json"
        
        # Use the scraper's save method
        from automation.etrainu_scraper import ETrainUEventScraper
        temp_scraper = ETrainUEventScraper()
        temp_scraper.events = self.events
        return temp_scraper.save_events_to_json(filename)
    
    def cleanup(self):
        """Clean up the ETrainU session"""
        try:
            # Navigate back to main page if we have it
            if self.main_page_handle and self.main_page_url:
                self.driver.switch_to.window(self.main_page_handle)
                # Could navigate back to Sports Connect if needed
                logger.info("ETrainU session cleanup complete")
        except Exception as e:
            logger.warning(f"Error during ETrainU cleanup: {e}")


# Factory method to create ETrainU manager from existing Sports Connect automation
def create_etrainu_manager(sports_connect_automation, config=None):
    """
    Factory method to create ETrainUManager from existing SportsConnectAutomation
    
    Args:
        sports_connect_automation: Already initialized and logged-in SportsConnectAutomation instance
        config: Configuration manager instance
        
    Returns:
        ETrainUManager instance ready to use
    """
    return ETrainUManager(
        driver=sports_connect_automation.driver,
        config=config or sports_connect_automation.config,
        already_logged_in=True
    )


# Integration example showing how to use with existing automation
def example_etrainu_integration(sports_connect_automation, config):
    """
    Example of how to integrate ETrainU with existing Sports Connect automation
    """
    logger.info("Starting ETrainU integration example...")
    
    # Create ETrainU manager using existing authentication
    etrainu_manager = create_etrainu_manager(sports_connect_automation, config)
    
    # Navigate to ETrainU
    if etrainu_manager.navigate_to_etrainu():
        
        # Scrape live events
        events = etrainu_manager.scrape_live_events()
        
        if events:
            # Save events
            events_file = etrainu_manager.save_events_to_json()
            logger.info(f"Saved {len(events)} events to {events_file}")
            
            # Now use the regular scraper for volunteer matching
            from automation.etrainu_scraper import ETrainUAutomationModule
            
            # Create combined module that uses both live and static data
            etrainu_module = ETrainUAutomationModule(sports_connect_automation, config)
            
            # Load volunteer data
            volunteer_files = {
                'compliance': 'data/2025 Volunteer Compliance.xlsx',
                'volunteer_details': 'data/Volunteer_Details 63.xlsx',
                'enrollment': 'data/Enrollment_Details.xlsx'
            }
            
            # Initialize with live events instead of HTML file
            etrainu_module.scraper.events = events  # Use live events directly
            etrainu_module.scraper.load_volunteer_data(volunteer_files)
            
            # Generate matches
            matches = etrainu_module.scraper.match_volunteers_to_courses()
            recommendations = etrainu_module.scraper.generate_enrollment_report(matches)
            
            # Optionally perform auto-enrollments
            # auto_enrollment_results = []
            # for volunteer, course_matches in matches.items():
            #     for match in course_matches[:1]:  # Only top match per volunteer
            #         result = etrainu_manager.auto_enroll_volunteer(
            #             volunteer_info={'name': volunteer, 'email': '...'},
            #             event_data=match['event']
            #         )
            #         auto_enrollment_results.append(result)
            
            logger.info(f"ETrainU integration complete: {len(matches)} volunteers matched")
            
        # Cleanup
        etrainu_manager.cleanup()
    
    return True