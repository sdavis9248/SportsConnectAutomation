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
import re
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
                
                # Create WebDriverWait instance
                wait = WebDriverWait(self.driver, 30)
        
                try:
                    # Wait for redirect to ETrainU domain
                    wait.until(lambda driver: "etrainu.com" in driver.current_url)
                    logger.info("Successfully redirected to ETrainU")
                except TimeoutException:
                    logger.warning("Did not redirect to ETrainU domain, continuing anyway")
                
            else:
                logger.error("Not logged into Sports Connect - cannot access ETrainU via SSO")
                return False
 
            # === NEW: Navigate to Training Event page ===
            logger.info("Navigating to Training Event page...")
        
            # If a loader overlay is present, wait for it to disappear
            try:
                wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".loader-overlay")))
            except TimeoutException:
                pass  # continue anyway

            # Try clicking a visible link first; fall back to direct URL if needed
            clicked = False
            for sel in [
                'a[title="Training Event"][data-analytics="menuItem-Training Event"]',  # main nav
                'a[href*="event=event.assessment.view"]',                               # any link to page
            ]:
                try:
                    link = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
                    link.click()
                    wait.until(EC.url_contains("event=event.assessment.view"))
                    logger.info(f"Clicked Training Event via selector: {sel}")
                    clicked = True
                    break
                except TimeoutException:
                    continue
                except Exception as e:
                    logger.debug(f"Click failed on {sel}: {e}")

            if not clicked:
                # Direct navigation as a reliable fallback
                base = "https://ayso.learn-usa.etrainu.com"
                self.driver.get(f"{base}/training/index.cfm?event=event.assessment.view")
                wait.until(EC.url_contains("event=event.assessment.view"))
                logger.info("Loaded Training Event via direct URL")

            # === NEW: Remove Region 58 filter automatically ===
            self._remove_region_filter()

            # === Enable Search events by location ===
            self._enable_search_events_by_location()

            # === NEW: Change to list view automatically ===
            self._change_to_list_view()

            logger.info(f"ETrainU setup complete. Current URL: {self.driver.current_url}")
            return True

        except Exception as e:
            logger.error(f"Error navigating to ETrainU: {e}")
            return False
    
    def scrape_live_events(self, region_filter=None) -> List[Dict]:
        """Scrape events directly from the live ETrainU site (using debug script logic)"""
        logger.info("Scraping live events from ETrainU...")
        
        events = []
        
        try:
            # Wait for events to load
            time.sleep(2)
            
            # Get the page source and parse with BeautifulSoup
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Find all event containers (like debug script)
            event_containers = soup.find_all('div', class_='event')
            logger.info(f"Found {len(event_containers)} event containers")
            
            for i, event_container in enumerate(event_containers, 1):
                try:
                    logger.debug(f"Processing event {i}...")
                    
                    # Extract basic event info
                    event_id = event_container.get('id', '')
                    data_event_id = event_container.get('data-event-id', '')
                    
                    # Extract title
                    title_element = event_container.find('h3', class_='title')
                    title = title_element.text.strip() if title_element else 'Unknown Event'
                    
                    # Extract region
                    region = 'Not specified'
                    region_elements = event_container.find_all('div', class_='detail-content')
                    for elem in region_elements:
                        if elem.text.strip().startswith('Region'):
                            region = elem.text.strip()
                            break
                    
                    # Extract courses
                    courses = []
                    course_list = event_container.find('div', class_='course-list')
                    if course_list:
                        course_divs = course_list.find_all('div')
                        courses = [div.text.strip() for div in course_divs if div.text.strip()]
                    
                    # Extract session information (date, time, location) - like debug script
                    sessions = []
                    session_containers = event_container.find_all('div', class_='session')
                    
                    for session in session_containers:
                        session_data = {}
                        
                        # Find date/time (with calendar icon)
                    calendar_elements = session.find_all('i', string='calendar_today')
                    for cal_icon in calendar_elements:
                        column = cal_icon.find_parent('div', class_='column')
                        if column:
                            datetime_text = column.get_text(strip=True).replace('calendar_today', '').strip()
                            session_data['datetime'] = datetime_text

                            # Example: "10th Sep 2025 6:00pm -  9:00pm"
                            match = re.match(r"(\d+)[a-z]{2} (\w+) (\d{4}) (\d{1,2}:\d{2}[ap]m)\s*-\s*(\d{1,2}:\d{2}[ap]m)", datetime_text)
                            if match:
                                day, month, year, start_time_str, end_time_str = match.groups()

                                # Parse start datetime object
                                start_dt_str = f"{day} {month} {year} {start_time_str}"
                                start_dt = datetime.strptime(start_dt_str, "%d %b %Y %I:%M%p")

                                # Parse end time (assumes same day)
                                end_dt_str = f"{day} {month} {year} {end_time_str}"
                                end_dt = datetime.strptime(end_dt_str, "%d %b %Y %I:%M%p")

                                # Save parsed values
                                session_data['date'] = start_dt.date().isoformat()
                                session_data['day_of_week'] = start_dt.strftime("%A")
                                session_data['start_time'] = start_dt.strftime("%H:%M")
                                session_data['end_time'] = end_dt.strftime("%H:%M")
                            else:
                                print(f"Could not parse: {datetime_text}")
                        
                        # Find location (with location icon)
                        location_elements = session.find_all('i', string='location_on')
                        for loc_icon in location_elements:
                            # Get the text in the same column as the location icon
                            column = loc_icon.find_parent('div', class_='column')
                            if column:
                                location_text = column.get_text(strip=True).replace('location_on', '').strip()
                                session_data['location'] = location_text
                        
                        if session_data:
                            sessions.append(session_data)
                    
                    # Extract contact information - like debug script
                    contact = {}
                    contact_section = event_container.find('div', class_='contact-details')
                    if contact_section:
                        # Extract contact name
                        contact_span = contact_section.find('span')
                        if contact_span:
                            # Get the text content, excluding the icon links
                            contact_text = contact_span.get_text(separator=' ', strip=True)
                            # Remove "phone" and "email" text that comes from material icons
                            contact_name = contact_text.replace('phone', '').replace('email', '').strip()
                            # Take the first part before any remaining artifacts
                            contact_name_parts = contact_name.split()
                            if len(contact_name_parts) >= 2:
                                contact['name'] = ' '.join(contact_name_parts[:2])  # First and last name
                        
                        # Extract phone
                        phone_link = contact_section.find('a', href=lambda x: x and x.startswith('tel:'))
                        if phone_link:
                            contact['phone'] = phone_link.get('href').replace('tel:', '')
                        
                        # Extract email
                        email_link = contact_section.find('a', href=lambda x: x and x.startswith('mailto:'))
                        if email_link:
                            contact['email'] = email_link.get('href').replace('mailto:', '')
                    
                    # Extract enrollment button info - like debug script
                    enroll_info = {}
                    enroll_button = event_container.find('button', class_='enrol-button')
                    if enroll_button:
                        enroll_info['data_event'] = enroll_button.get('data-event', '')
                        enroll_info['data_session'] = enroll_button.get('data-session', '')
                        enroll_info['button_text'] = enroll_button.text.strip()
                    
                    # Determine course type - like debug script
                    course_type = 'Other'
                    title_lower = title.lower()
                    if 'area director' in title_lower:
                        course_type = 'Area Director Training'
                    elif 'coach' in title_lower:
                        if '6u' in title_lower or '8u' in title_lower:
                            course_type = '6U/8U Coach'
                        elif '10u' in title_lower:
                            course_type = '10U Coach'
                        elif '12u' in title_lower:
                            course_type = '12U Coach'
                        elif '14u' in title_lower or 'intermediate' in title_lower:
                            course_type = '14U/Intermediate Coach'
                        else:
                            course_type = 'Coach Certification'
                    elif 'referee' in title_lower:
                        if 'regional' in title_lower:
                            course_type = 'Regional Referee'
                        elif 'intermediate' in title_lower:
                            course_type = 'Intermediate Referee'
                        else:
                            course_type = 'Referee Certification'
                    
                    # Create event dictionary - like debug script
                    event_data = {
                        'event_id': event_id,
                        'data_event_id': data_event_id,
                        'title': title,
                        'course_type': course_type,
                        'region': region,
                        'courses': courses,
                        'sessions': sessions,
                        'contact': contact,
                        'enroll_info': enroll_info,
                        'scraped_live': True,
                        'scraped_at': datetime.now().isoformat(),
                        'source_url': self.driver.current_url
                    }
                    
                    events.append(event_data)
                    
                    logger.debug(f"Event: {title}")
                    logger.debug(f"  Type: {course_type}")
                    logger.debug(f"  Region: {region}")
                    logger.debug(f"  Sessions: {len(sessions)}")
                    logger.debug(f"  Contact: {contact.get('name', 'N/A')}")
                    
                except Exception as e:
                    logger.error(f"Error processing event {i}: {e}")
                    continue
            
            self.events = events
            logger.info(f"Successfully scraped {len(events)} live events from ETrainU")
            
            # Show summary like debug script
            if events:
                event_types = {}
                for event in events:
                    event_type = event['course_type']
                    event_types[event_type] = event_types.get(event_type, 0) + 1
                
                logger.info("Event types found:")
                for event_type, count in event_types.items():
                    logger.info(f"  - {event_type}: {count}")
            
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
 
    def _change_to_list_view(self):
        """Change view to list (like debug script)"""
        logger.info("Changing view to list...")
        try:
            # Wait a moment for the page to update after filter removal
            time.sleep(1)
        
            # Method 1: Try to find by XPath (most reliable for text content)
            list_clicked = False
            try:
                # Find the material-icons element that contains "list" text
                list_icon = self.driver.find_element(By.XPATH, "//i[@class='material-icons' and text()='list']")
            
                # The clickable element might be the parent (button/link)
                clickable_parent = list_icon.find_element(By.XPATH, "./..")  # Parent element
            
                # Scroll to and click
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", clickable_parent)
                time.sleep(0.5)
                clickable_parent.click()
                logger.info("Switched to list view via XPath")
                list_clicked = True
            
            except Exception as e:
                logger.debug(f"XPath list icon search failed: {e}")
        
            # Method 2: Try finding all material-icons and checking their text
            if not list_clicked:
                try:
                    material_icons = self.driver.find_elements(By.CSS_SELECTOR, '.material-icons')
                    logger.debug(f"Found {len(material_icons)} material icons")
                
                    for icon in material_icons:
                        if icon.text.strip() == "list":
                            # Found the list icon, try to click its parent
                            parent = icon.find_element(By.XPATH, "./..")
                            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", parent)
                            time.sleep(0.5)
                            parent.click()
                            logger.info("Switched to list view via material-icons iteration")
                            list_clicked = True
                            break
                        
                except Exception as e:
                    logger.debug(f"Material icons iteration failed: {e}")
        
            # Method 3: Try common view toggle selectors
            if not list_clicked:
                view_selectors = [
                    'button[title*="list"]',
                    'a[title*="list"]',
                    '.view-toggle button:last-child',  # Often list view is the second button
                    '.view-controls button:last-child',
                    '[data-view="list"]',
                    '.list-view-btn'
                ]
            
                for selector in view_selectors:
                    try:
                        element = self.driver.find_element(By.CSS_SELECTOR, selector)
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                        time.sleep(0.5)
                        element.click()
                        logger.info(f"Switched to list view via selector: {selector}")
                        list_clicked = True
                        break
                    except Exception as e:
                        logger.debug(f"Selector {selector} failed: {e}")
        
            if not list_clicked:
                logger.warning("Could not find or click list view button")
                logger.warning("The page might already be in list view or use different elements")
            else:
                # Wait for the view to change
                time.sleep(2)
                logger.info("List view change complete")

        except Exception as e:
            logger.error(f"Error during view change: {e}")

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
 
    def _remove_region_filter(self):
        """Remove Region 58 filter (like debug script)"""
        logger.info("Removing Region 58 filter...")
        try:
            # Wait a moment for the page to fully load
            time.sleep(2)

            # Look for the Region 58 chip filter
            region_chip_selectors = [
                '#partnershipAccounts-chip-TsxWTaOUarr1mOqszBcxduq6F2UgW2Iv .btn-clear',  # Specific chip close button
                'div[data-value*="Region 58"] .btn-clear',                                    # Generic Region 58 chip close button
                '.chip:contains("Region 58") .btn-clear',                                     # CSS pseudo-selector (if supported)
                '.filter-chip:contains("Region 58") .close-btn',                             # Alternative chip structure
                '.chip .btn-clear',                                                           # Any chip close button (for iteration)
            ]

            filter_removed = False
        
            # Try specific selectors first
            for selector in region_chip_selectors[:-1]:  # All except the last (generic) one
                try:
                    close_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", close_button)
                    time.sleep(0.5)
                    close_button.click()
                    logger.info("Removed Region 58 filter by specific selector")
                    filter_removed = True
                    break
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {e}")

            # If specific selectors fail, iterate through all chips
            if not filter_removed:
                try:
                    chips = self.driver.find_elements(By.CSS_SELECTOR, '.chip')
                    logger.info(f"Found {len(chips)} filter chips")
                
                    for chip in chips:
                        chip_text = chip.text.strip()
                        logger.debug(f"Chip text: '{chip_text}'")
            
                        if "Region 58" in chip_text:
                            close_button = chip.find_element(By.CSS_SELECTOR, ".btn-clear")
                            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", close_button)
                            time.sleep(0.5)
                            close_button.click()
                            logger.info("Removed Region 58 filter by iterating through chips")
                            filter_removed = True
                            break
                        
                except Exception as e:
                    logger.debug(f"Chip iteration failed: {e}")
        
            if not filter_removed:
                logger.info("Could not find Region 58 filter (might not be present)")
            else:
                # Wait for the page to update after removing the filter
                time.sleep(2)
                logger.info("Region 58 filter removal complete")

        except Exception as e:
            logger.error(f"Error during filter removal: {e}")

    def _enable_search_events_by_location(self):
        """Enable Search Events by Location"""
        logger.info("Enable Search Events by Location Filter...")
        try:
            # Wait a moment for the page to fully load
            time.sleep(2)

            # Look for the Region 58 chip filter
            geo_chip_selectors = [
                "//div[contains(@class, 'my-location')]/i[normalize-space()='gps_fixed']",
                "//div[contains(@class, 'my-location')]", # Specific chip confirm button
            ]

            filter_enabled = False
        
            # Try specific selectors first
            for selector in geo_chip_selectors[:-1]:  # All except the last (generic) one
                try:
                    enable_icon = self.driver.find_element(By.XPATH, selector)
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", enable_icon)
                    time.sleep(0.5)
                    enable_icon.click()
                    logger.info("Enable Search by Location filter by specific selector")
                    filter_enabled = True
                    break
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {e}")
        
            if not filter_enabled:
                logger.info("Could not find Location Search Enable filter (might not be present)")
            else:
                # Wait for the page to update after removing the filter
                time.sleep(2)
                logger.info("Location Search Enable filter complete")

        except Exception as e:
            logger.error(f"Error during filter enable: {e}")

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