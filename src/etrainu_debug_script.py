#!/usr/bin/env python3
"""
Debug script for ETrainU live scraping
This will help us see exactly what's happening when we try to access the live site
"""

import sys
import os
import logging
import time
from pathlib import Path
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Add src to path (matching your existing project structure)
current_dir = Path(__file__).parent
src_dir = current_dir / 'src' if (current_dir / 'src').exists() else current_dir

if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,  # Very detailed logging
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'etrainu_debug_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def debug_etrainu_live():
    """Debug the ETrainU live scraping process step by step"""
    
    try:
        # Import required modules
        from core.config import ConfigManager
        from automation.sports_connect import SportsConnectAutomation
        from selenium.webdriver.common.by import By
        from bs4 import BeautifulSoup  # for scraping
        import json  # JSON saving
        
        print("="*60)
        print("ETRAINU LIVE SCRAPING DEBUG")
        print("="*60)
        
        # Load configuration
        config = ConfigManager()
        config.load_config()
        
        print(f"✓ Configuration loaded")
        print(f"  Organization ID: {config.get('organization_id', 'Not set')}")
        print(f"  Base URL: {config.get('base_url', 'Not set')}")
        
        # Initialize automation
        print("\n1. Initializing Sports Connect automation...")
        automation = SportsConnectAutomation(config)
        automation.initialize()
        print("✓ Automation initialized")
        
        # Login to Sports Connect
        print("\n2. Logging into Sports Connect...")
        if not automation.login():
            print("✗ Sports Connect login failed!")
            return False
        print("✓ Sports Connect login successful")
        print(f"  Current URL: {automation.driver.current_url}")
        
        # Try to create ETrainU manager
        print("\n3. Creating ETrainU manager...")
        try:
            from automation.etrainu_manager import ETrainUManager
            
            etrainu_manager = ETrainUManager(
                driver=automation.driver,
                config=config,
                already_logged_in=True
            )
            print("✓ ETrainU manager created")
            print(f"  Base URL: {etrainu_manager.base_url}")
            
        except ImportError as e:
            print(f"✗ Failed to import ETrainU manager: {e}")
            print("  Make sure etrainu_manager.py is in the automation/ directory")
            return False
        
        # Try to navigate to ETrainU
        print("\n4. Navigating to ETrainU...")
        success = etrainu_manager.navigate_to_etrainu()

        print(f"  Navigation result: {success}")
        print(f"  Current URL: {automation.driver.current_url}")
        print(f"  Page title: {automation.driver.title}")

        # === NEW: go to Training Event ===
        print("  Navigating to Training Event...")
        wait = WebDriverWait(automation.driver, 20)
        # If a loader overlay is present on this site, wait for it to disappear
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
                automation.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
                link.click()
                wait.until(EC.url_contains("event=event.assessment.view"))
                print(f"  ✓ Clicked Training Event via selector: {sel}")
                clicked = True
                break
            except TimeoutException:
                continue
            except Exception as e:
                print(f"  (click failed on {sel}: {e})")

        if not clicked:
            # Direct navigation as a reliable fallback
            base = "https://ayso.learn-usa.etrainu.com"
            automation.driver.get(f"{base}/training/index.cfm?event=event.assessment.view")
            wait.until(EC.url_contains("event=event.assessment.view"))
            print("  ✓ Loaded Training Event via direct URL")

        # === NEW: Remove Region 58 filter ===
        print("  Removing Region 58 filter...")
        try:
            # Wait a moment for the page to fully load
            time.sleep(2)
    
            # Look for the Region 58 chip filter
            region_chip_selectors = [
                '#partnershipAccounts-chip-TsxWTaOUarr1mOqszBcxduq6F2UgW2Iv .btn-clear',  # Specific chip close button
                'div[data-value*="Region 58"] .btn-clear',                                    # Generic Region 58 chip close button
                '.chip:contains("Region 58") .btn-clear',                                     # CSS pseudo-selector (if supported)
                'div.chip .btn-clear'                                                         # Any chip close button
            ]
    
            # Try different approaches to find and click the close button
            filter_removed = False
    
            # Method 1: Try specific selectors
            for selector in region_chip_selectors:
                try:
                    if ':contains(' in selector:
                        # For contains selector, use XPath instead
                        close_button = automation.driver.find_element(By.XPATH, "//div[@class='chip'][contains(text(), 'Region 58')]//a[@class='btn btn-clear']")
                    else:
                        close_button = automation.driver.find_element(By.CSS_SELECTOR, selector)
            
                    # Make sure the button is visible and clickable
                    automation.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", close_button)
                    time.sleep(0.5)
            
                    # Try clicking
                    close_button.click()
                    print("  ✓ Removed Region 58 filter via selector")
                    filter_removed = True
                    break
            
                except Exception as e:
                    print(f"  (selector {selector} failed: {e})")
                    continue
    
            # Method 2: If specific selectors failed, try finding by text content
            if not filter_removed:
                try:
                    # Find the chip containing "Region 58" text
                    region_chip = automation.driver.find_element(By.XPATH, "//div[contains(@class, 'chip') and contains(text(), 'Region 58')]")
            
                    # Find the close button within that chip
                    close_button = region_chip.find_element(By.CSS_SELECTOR, ".btn-clear")
            
                    # Click it
                    automation.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", close_button)
                    time.sleep(0.5)
                    close_button.click()
                    print("  ✓ Removed Region 58 filter via XPath text search")
                    filter_removed = True
            
                except Exception as e:
                    print(f"  (XPath text search failed: {e})")
    
            # Method 3: Last resort - find all chips and look for Region 58
            if not filter_removed:
                try:
                    chips = automation.driver.find_elements(By.CSS_SELECTOR, "div.chip")
                    print(f"  Found {len(chips)} filter chips")
            
                    for chip in chips:
                        chip_text = chip.text.strip()
                        print(f"    Chip text: '{chip_text}'")
                
                        if "Region 58" in chip_text:
                            close_button = chip.find_element(By.CSS_SELECTOR, ".btn-clear")
                            automation.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", close_button)
                            time.sleep(0.5)
                            close_button.click()
                            print("  ✓ Removed Region 58 filter by iterating through chips")
                            filter_removed = True
                            break
                    
                except Exception as e:
                    print(f"  (chip iteration failed: {e})")
    
            if not filter_removed:
                print("  ✗ Could not find or remove Region 58 filter")
                print("    This might be okay if the filter isn't present")
            else:
                # Wait for the page to update after removing the filter
                time.sleep(2)
                print("  ✓ Region 58 filter removal complete")

        except Exception as e:
            print(f"  ✗ Error during filter removal: {e}")

        # Update the current URL after filter removal
        print(f"  Current URL after filter removal: {automation.driver.current_url}")

        # === NEW: Change view to list ===
        print("  Changing view to list...")
        try:
            # Wait a moment for the page to update after filter removal
            time.sleep(1)
    
            # Look for the list view button with material-icons list
            list_view_selectors = [
                'i.material-icons[text()="list"]',                    # Direct material icon
                'button i.material-icons:contains("list")',          # Button containing list icon
                'a i.material-icons:contains("list")',               # Link containing list icon
                '.material-icons',                                    # Any material icon (fallback)
                '[title*="list"]',                                    # Element with list in title
                '[aria-label*="list"]'                               # Element with list in aria-label
            ]
    
            # Method 1: Try to find by XPath (most reliable for text content)
            list_clicked = False
            try:
                # Find the material-icons element that contains "list" text
                list_icon = automation.driver.find_element(By.XPATH, "//i[@class='material-icons' and text()='list']")
        
                # The clickable element might be the parent (button/link)
                clickable_parent = list_icon.find_element(By.XPATH, "./..")  # Parent element
        
                # Scroll to and click
                automation.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", clickable_parent)
                time.sleep(0.5)
                clickable_parent.click()
                print("  ✓ Switched to list view via XPath")
                list_clicked = True
        
            except Exception as e:
                print(f"  (XPath list icon search failed: {e})")
    
            # Method 2: Try finding all material-icons and look for "list" text
            if not list_clicked:
                try:
                    material_icons = automation.driver.find_elements(By.CSS_SELECTOR, "i.material-icons")
                    print(f"  Found {len(material_icons)} material icons")
            
                    for icon in material_icons:
                        icon_text = icon.text.strip()
                        print(f"    Icon text: '{icon_text}'")
                
                        if icon_text == "list":
                            # Try clicking the icon itself first
                            try:
                                automation.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", icon)
                                time.sleep(0.5)
                                icon.click()
                                print("  ✓ Switched to list view by clicking icon directly")
                                list_clicked = True
                                break
                            except:
                                # If icon click fails, try clicking its parent
                                try:
                                    parent = icon.find_element(By.XPATH, "./..")
                                    automation.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", parent)
                                    time.sleep(0.5)
                                    parent.click()
                                    print("  ✓ Switched to list view by clicking icon parent")
                                    list_clicked = True
                                    break
                                except Exception as e:
                                    print(f"    (failed to click icon or parent: {e})")
                                    continue
                            
                except Exception as e:
                    print(f"  (material icons iteration failed: {e})")
    
            # Method 3: Try looking for view toggle buttons
            if not list_clicked:
                try:
                    # Common patterns for view toggle buttons
                    view_toggle_selectors = [
                        '[data-view="list"]',
                        '[data-toggle="list"]',
                        'button[title*="List"]',
                        'button[title*="list"]',
                        '.view-toggle .list',
                        '.view-switcher .list'
                    ]
            
                    for selector in view_toggle_selectors:
                        try:
                            toggle_button = automation.driver.find_element(By.CSS_SELECTOR, selector)
                            automation.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", toggle_button)
                            time.sleep(0.5)
                            toggle_button.click()
                            print(f"  ✓ Switched to list view via selector: {selector}")
                            list_clicked = True
                            break
                        except:
                            continue
                    
                except Exception as e:
                    print(f"  (view toggle search failed: {e})")
    
            # Method 4: JavaScript approach as last resort
            if not list_clicked:
                try:
                    # Try to find and click using JavaScript
                    js_code = """
                    var listIcon = Array.from(document.querySelectorAll('i.material-icons')).find(el => el.textContent.trim() === 'list');
                    if (listIcon) {
                        var clickTarget = listIcon.closest('button') || listIcon.closest('a') || listIcon;
                        clickTarget.click();
                        return true;
                    }
                    return false;
                    """
            
                    result = automation.driver.execute_script(js_code)
                    if result:
                        print("  ✓ Switched to list view via JavaScript")
                        list_clicked = True
                    else:
                        print("  JavaScript didn't find list icon")
                
                except Exception as e:
                    print(f"  (JavaScript approach failed: {e})")
    
            if not list_clicked:
                print("  ✗ Could not find or click list view button")
                print("    The page might already be in list view or use different elements")
            else:
                # Wait for the view to change
                time.sleep(2)
                print("  ✓ List view change complete")

        except Exception as e:
            print(f"  ✗ Error during view change: {e}")

        # Update the current URL after view change
        print(f"  Current URL after view change: {automation.driver.current_url}")

        # === NEW: Scrape events from list view ===
        print("  Scraping events from the page...")
        try:
            # Wait for events to load
            time.sleep(2)
    
            # Get the page source and parse with BeautifulSoup
            page_source = automation.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
    
            # Find all event containers
            event_containers = soup.find_all('div', class_='event')
            print(f"  Found {len(event_containers)} event containers")
    
            scraped_events = []
    
            for i, event_container in enumerate(event_containers, 1):
                try:
                    print(f"  Processing event {i}...")
            
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
            
                    # Extract session information (date, time, location)
                    sessions = []
                    session_containers = event_container.find_all('div', class_='session')
            
                    for session in session_containers:
                        session_data = {}
                
                        # Find date/time (with calendar icon)
                        calendar_elements = session.find_all('i', string='calendar_today')
                        for cal_icon in calendar_elements:
                            # Get the text in the same column as the calendar icon
                            column = cal_icon.find_parent('div', class_='column')
                            if column:
                                datetime_text = column.get_text(strip=True).replace('calendar_today', '').strip()
                                session_data['datetime'] = datetime_text
                
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
            
                    # Extract contact information
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
            
                    # Extract enrollment button info
                    enroll_info = {}
                    enroll_button = event_container.find('button', class_='enrol-button')
                    if enroll_button:
                        enroll_info['data_event'] = enroll_button.get('data-event', '')
                        enroll_info['data_session'] = enroll_button.get('data-session', '')
                        enroll_info['button_text'] = enroll_button.text.strip()
            
                    # Determine course type
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
            
                    # Create event dictionary
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
                        'source_url': automation.driver.current_url
                    }
            
                    scraped_events.append(event_data)
            
                    print(f"    ✓ Event: {title}")
                    print(f"      Type: {course_type}")
                    print(f"      Region: {region}")
                    print(f"      Sessions: {len(sessions)}")
                    print(f"      Contact: {contact.get('name', 'N/A')}")
            
                except Exception as e:
                    print(f"    ✗ Error processing event {i}: {e}")
                    continue
    
            print(f"  ✓ Successfully scraped {len(scraped_events)} events")
    
            # Save the scraped events to a JSON file for inspection
            if scraped_events:
                events_file = f"scraped_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(events_file, 'w', encoding='utf-8') as f:
                    json.dump(scraped_events, f, indent=2, ensure_ascii=False, default=str)
                print(f"  ✓ Saved scraped events to: {events_file}")
        
                # Show a summary of event types found
                event_types = {}
                for event in scraped_events:
                    event_type = event['course_type']
                    event_types[event_type] = event_types.get(event_type, 0) + 1
        
                print("  Event types found:")
                for event_type, count in event_types.items():
                    print(f"    - {event_type}: {count}")
    
        except Exception as e:
            print(f"  ✗ Error during event scraping: {e}")
            import traceback
            traceback.print_exc()

        print(f"  Training Event URL: {automation.driver.current_url}")
        print(f"  Training Event title: {automation.driver.title}")
        # === END NEW ===

        # Save current page source for inspection
        page_source = automation.driver.page_source
        debug_file = f"etrainu_page_source_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(page_source)
        print(f"  Page source saved to: {debug_file}")

        # Look for training-related content
        print("\n5. Analyzing page content...")
        content_lower = page_source.lower()

        training_indicators = {
            'etrainu': 'etrainu' in content_lower,
            'training': 'training' in content_lower,
            'course': 'course' in content_lower,
            'enroll': 'enroll' in content_lower,
            'certification': 'certification' in content_lower,
            'event': 'event' in content_lower,
            'session': 'session' in content_lower,
            'ayso training': 'ayso training' in content_lower
        }

        for indicator, found in training_indicators.items():
            status = "✓" if found else "✗"
            print(f"  {status} Found '{indicator}': {found}")

        
        # Try to scrape events regardless
        print("\n6. Attempting to scrape events...")
        try:
            events = etrainu_manager.scrape_live_events()
            print(f"  Events scraped: {len(events)}")
            
            if events:
                print("  Sample event titles:")
                for i, event in enumerate(events[:3]):
                    print(f"    {i+1}. {event.get('title', 'No title')}")
            else:
                print("  No events found - this indicates the page structure is different")
                
                # Let's look for any div elements that might contain events
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(page_source, 'html.parser')
                
                # Look for common training page elements
                possible_elements = [
                    soup.find_all('div', class_=lambda x: x and 'event' in x.lower()),
                    soup.find_all('div', class_=lambda x: x and 'course' in x.lower()),
                    soup.find_all('div', class_=lambda x: x and 'training' in x.lower()),
                    soup.find_all('tr'),  # Table rows (might be course listings)
                    soup.find_all('div', class_=lambda x: x and 'session' in x.lower()),
                ]
                
                print("  Analyzing page structure for possible course elements...")
                for i, elements in enumerate(possible_elements):
                    if elements:
                        print(f"    Found {len(elements)} elements of type {i}")
                        if elements:
                            sample_text = elements[0].get_text()[:100] + "..." if len(elements[0].get_text()) > 100 else elements[0].get_text()
                            print(f"    Sample: {sample_text}")
                
        except Exception as e:
            print(f"  ✗ Error during scraping: {e}")
        
        # Try alternative approach - check if we need to navigate to a specific training page
        print("\n7. Looking for training/course links on current page...")
        try:
            from selenium.webdriver.common.by import By
            
            # Look for links that might lead to training
            training_links = automation.driver.find_elements(By.XPATH, "//a[contains(@href, 'training') or contains(@href, 'course') or contains(@href, 'etrainu') or contains(text(), 'Training') or contains(text(), 'Course')]")
            
            if training_links:
                print(f"  Found {len(training_links)} potential training links:")
                for i, link in enumerate(training_links[:5]):  # Show first 5
                    try:
                        href = link.get_attribute('href')
                        text = link.text.strip()
                        print(f"    {i+1}. Text: '{text}' | URL: {href}")
                    except:
                        pass
                        
                # Try clicking the first training link
                if len(training_links) > 0:
                    print("\n8. Trying to click first training link...")
                    try:
                        first_link = training_links[0]
                        first_link.click()
                        time.sleep(3)
                        
                        print(f"  After click - URL: {automation.driver.current_url}")
                        print(f"  After click - Title: {automation.driver.title}")
                        
                        # Try scraping again
                        events = etrainu_manager.scrape_live_events()
                        print(f"  Events after navigation: {len(events)}")
                        
                    except Exception as e:
                        print(f"  ✗ Error clicking link: {e}")
            else:
                print("  No training-related links found")
                
        except Exception as e:
            print(f"  ✗ Error looking for links: {e}")
        
        print("\n" + "="*60)
        print("DEBUG COMPLETE")
        print("="*60)
        print(f"Check the log file and {debug_file} for detailed information")
        
        return True
        
    except Exception as e:
        print(f"✗ Debug script failed: {e}")
        logger.exception("Debug script error")
        return False
    
    finally:
        # Cleanup
        try:
            if 'automation' in locals():
                automation.cleanup()
        except:
            pass

if __name__ == "__main__":
    debug_etrainu_live()
