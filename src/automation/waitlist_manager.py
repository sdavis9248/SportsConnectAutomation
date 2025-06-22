"""
Waitlist management for Sports Connect Automation
"""
import json
import time
import logging
import os
from typing import List, Dict, Optional
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from core.element_interactor import ElementInteractor

logger = logging.getLogger(__name__)

class WaitlistManager:
    """Handles waitlist participant removal operations"""
    
    def __init__(self, driver, base_url: str, org_id: str, config=None):
        """
        Initialize Waitlist Manager
        
        Args:
            driver: Selenium WebDriver instance
            base_url: Base URL for Sports Connect
            org_id: Organization ID
            config: Configuration manager instance
        """
        self.driver = driver
        self.base_url = base_url
        self.org_id = org_id
        self.config = config
        self.interactor = ElementInteractor(driver)
        self.wait = WebDriverWait(driver, 10)
        self.division_data = []
    
    def navigate_to_enrollment_summary(self, program_name: str = "2025 Fall Core"):
        """Navigate to the enrollment summary page and run the report"""
        logger.info("Navigating to enrollment summary for waitlist data")
        
        # Navigate to enrollment summary URL
        url = f"{self.base_url}/{self.org_id}/admin/program-enrollment-summary"
        self.driver.get(url)
        
        # Wait a bit to ensure page is fully loaded
        time.sleep(2)
        
        # First, click on the dropdown to open it
        logger.info("Opening program dropdown")
        dropdown_selectors = [
            (By.XPATH, '//div[@class="mat-select-value ng-tns-c245-4"]'),
            (By.XPATH, '//mat-select[@placeholder="Program"]'),
            (By.XPATH, '//mat-select[contains(@class, "mat-select")]'),
            (By.XPATH, '//div[contains(@class, "mat-select-value")]'),
            (By.XPATH, '//span[contains(text(), "Select All")]/parent::span/parent::div'),
            (By.XPATH, '//div[contains(@class, "mat-form-field")]//div[contains(@class, "mat-select-trigger")]')
        ]
        
        if not self.interactor.try_multiple_selectors(dropdown_selectors, "click"):
            raise Exception("Could not open program dropdown")
        
        logger.info("Dropdown opened successfully")
        time.sleep(1)  # Wait for dropdown to open
        
        # Now select the program option
        logger.info(f"Selecting program: {program_name}")
        program_selectors = [
            (By.XPATH, f'//mat-option[normalize-space()="{program_name}"]'),
            (By.XPATH, f'//mat-option[contains(text(), "{program_name}")]'),
            (By.XPATH, f'//span[normalize-space()="{program_name}"]'),
            (By.XPATH, f'//span[contains(text(), "{program_name}")]')
        ]
        
        if not self.interactor.try_multiple_selectors(program_selectors, "click"):
            # Log available options for debugging
            try:
                options = self.driver.find_elements(By.TAG_NAME, "mat-option")
                logger.info("Available options:")
                for opt in options:
                    if opt.text.strip():
                        logger.info(f"  - {opt.text.strip()}")
            except:
                pass
            raise Exception(f"Program '{program_name}' not found in dropdown")
        
        logger.info(f"Selected program: {program_name}")
        time.sleep(1)  # Wait for selection
        
        # Click the run report button
        logger.info("Clicking run report button")
        button_selectors = [
            (By.XPATH, '//span[text()=" View Report "]/parent::button'),
            (By.XPATH, '//span[contains(text(), "View Report")]/parent::button'),
            (By.XPATH, '//button[contains(., "View Report")]'),
            (By.XPATH, '//span[@class="mat-button-wrapper" and contains(text(), "View Report")]'),
            (By.XPATH, '//span[@class="mat-button-wrapper" and normalize-space()="View Report"]'),
            (By.XPATH, '//*[@id="mat-dialog-0"]/sc-static-report-condition-dialog/div/div[2]/div[2]/button[2]'),
            (By.XPATH, '//mat-dialog-container//button[contains(., "View Report")]')
        ]
        
        if not self.interactor.try_multiple_selectors(button_selectors, "click"):
            raise Exception("Could not find run report button")
        
        logger.info("Report button clicked successfully")
        
        # Wait for report to generate
        time.sleep(5)
    
    def fetch_division_data(self, program_id: str, program_name: str = "2025 Fall Core") -> List[Dict]:
        """Fetch division data using the API"""
        logger.info(f"Fetching division data for program {program_name}")
        
        # Navigate to enrollment summary page and run report
        self.navigate_to_enrollment_summary(program_name)
        
        # Execute JavaScript to fetch data
        script = """
        return new Promise((resolve) => {
            (async function() {
                const apiUrl = window.location.origin + '/proxy/reporting/api/v1/EnrollmentSummaryReport/programs';
                
                const endDate = new Date();
                const startDate = new Date();
                startDate.setFullYear(startDate.getFullYear() - 1);
                
                const formatDate = (date) => {
                    return `${date.getMonth() + 1}/${date.getDate()}/${date.getFullYear()}`;
                };
                
                const payload = {
                    programId: parseInt(arguments[0]),
                    startDate: formatDate(startDate),
                    endDate: formatDate(endDate),
                    programName: "",
                    divisionName: "",
                    divisionEnrollments: -1,
                    maximumEnrollments: -1,
                    tryoutEnrollments: -1,
                    waitlist: -1,
                    sortBy: "",
                    sortDirection: ""
                };
                
                try {
                    const response = await fetch(apiUrl, {
                        method: 'POST',
                        headers: {
                            'Accept': 'application/json',
                            'Content-Type': 'application/json'
                        },
                        credentials: 'include',
                        body: JSON.stringify(payload)
                    });
                    
                    const data = await response.json();
                    resolve(data.data[0].divisions);
                } catch (error) {
                    console.error('Error fetching divisions:', error);
                    resolve([]);
                }
            })(arguments[0]);
        });
        """
        
        # Execute script
        divisions = self.driver.execute_script(script, program_id)
        self.division_data = divisions
        
        logger.info(f"Found {len(divisions)} divisions")
        
        # Filter divisions with waitlists
        waitlist_divisions = [d for d in divisions if d.get('waitlist', 0) > 0]
        logger.info(f"Found {len(waitlist_divisions)} divisions with waitlists")
        
        return waitlist_divisions
    
    def navigate_to_waitlist(self, division_id: str, division_name: str):
        """Navigate to waitlist page for a specific division"""
        url = f"https://registration-setup.bluesombrero.com/registration-admin/{self.org_id}/{division_id}/waitlist"
        logger.info(f"Navigating to waitlist for {division_name}")
        self.driver.get(url)
        
        # Wait for waitlist table to load
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.mat-table, table[mat-table], datatable-body-row")))
            time.sleep(3)  # Additional wait for data to populate
        except:
            logger.warning("Waitlist table not found with expected selectors")
    
    def find_participants_by_order(self, order_numbers: List[str]) -> List[Dict]:
        """Find participants with specific order numbers"""
        logger.info(f"Searching for order numbers: {order_numbers}")
        
        participants_to_remove = []
        
        # Wait for the ngx-datatable to load
        time.sleep(3)
        
        # For ngx-datatable, we need to look for datatable-body-row elements
        try:
            # Find all data rows
            rows = self.driver.find_elements(By.CSS_SELECTOR, "datatable-body-row")
            logger.info(f"Found {len(rows)} rows in the waitlist table")
            
            if not rows:
                logger.warning("No rows found with CSS selector. Trying alternative selectors...")
                rows = self.driver.find_elements(By.TAG_NAME, "datatable-body-row")
            
            if not rows:
                logger.error("No rows found in waitlist table")
                return participants_to_remove
            
            for i, row in enumerate(rows):
                try:
                    # Get all cells in the row
                    cells = row.find_elements(By.CSS_SELECTOR, "datatable-body-cell")
                    
                    if not cells:
                        cells = row.find_elements(By.TAG_NAME, "datatable-body-cell")
                    
                    # Log first few rows to see structure for debugging
                    if i < 3 and cells:
                        cell_texts = []
                        for j, cell in enumerate(cells[:5]):  # First 5 columns
                            try:
                                label = cell.find_element(By.CSS_SELECTOR, ".datatable-body-cell-label")
                                text = label.text.strip()
                            except:
                                text = cell.text.strip()
                            if text:
                                cell_texts.append(f"Col{j}: {text}")
                        logger.debug(f"Row {i}: {' | '.join(cell_texts)}")
                    
                    # The order number should be in the second cell (index 1)
                    if len(cells) > 1:
                        try:
                            # Get the order number from the second cell
                            order_cell = cells[1]
                            try:
                                order_label = order_cell.find_element(By.CSS_SELECTOR, ".datatable-body-cell-label")
                                order_text = order_label.text.strip()
                            except:
                                order_text = order_cell.text.strip()
                            
                            # Check if this order number matches any we're looking for
                            if order_text in order_numbers:
                                logger.info(f"Found order number {order_text} in row {i}")
                                
                                # Find the checkbox in the first cell
                                checkbox_cell = cells[0]
                                checkbox = checkbox_cell.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                                participant_id = checkbox.get_attribute("value") or f"row_{i}"
                                
                                # Also get player name for logging
                                player_first = ""
                                player_last = ""
                                if len(cells) > 3:
                                    try:
                                        first_name_cell = cells[3]
                                        try:
                                            first_name_label = first_name_cell.find_element(By.CSS_SELECTOR, ".datatable-body-cell-label")
                                            player_first = first_name_label.text.strip()
                                        except:
                                            player_first = first_name_cell.text.strip()
                                    except:
                                        pass
                                
                                if len(cells) > 4:
                                    try:
                                        last_name_cell = cells[4]
                                        try:
                                            last_name_label = last_name_cell.find_element(By.CSS_SELECTOR, ".datatable-body-cell-label")
                                            player_last = last_name_label.text.strip()
                                        except:
                                            player_last = last_name_cell.text.strip()
                                    except:
                                        pass
                                
                                participant_info = {
                                    "id": participant_id,
                                    "order_number": order_text,
                                    "checkbox": checkbox,
                                    "row": row,
                                    "row_index": i,
                                    "player_name": f"{player_first} {player_last}".strip()
                                }
                                participants_to_remove.append(participant_info)
                                logger.info(f"Will remove: {participant_info['player_name']} (Order: {order_text}, ID: {participant_id})")
                                
                        except Exception as e:
                            logger.debug(f"Error checking order number in row {i}: {str(e)}")
                            
                except Exception as e:
                    logger.debug(f"Error processing row {i}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Error finding participants: {str(e)}")
            # Try to provide helpful debugging info
            try:
                page_title = self.driver.title
                logger.info(f"Current page title: {page_title}")
                
                # Look for any error messages
                error_elements = self.driver.find_elements(By.CSS_SELECTOR, ".error, .alert, .message")
                for elem in error_elements:
                    if elem.text.strip():
                        logger.warning(f"Possible error on page: {elem.text.strip()}")
            except:
                pass
        
        logger.info(f"Total participants found to remove: {len(participants_to_remove)}")
        
        # Log summary
        if participants_to_remove:
            logger.info("Summary of participants to remove:")
            for p in participants_to_remove:
                logger.info(f"  - {p['player_name']} (Order: {p['order_number']})")
        else:
            logger.warning("No participants found with the specified order numbers")
            logger.info(f"Looking for orders: {order_numbers}")
            logger.info("Make sure the order numbers are exact matches (including any leading zeros)")
        
        return participants_to_remove
    
    def remove_participants(self, participants: List[Dict], auto_confirm: bool = True) -> bool:
        """Remove selected participants"""
        if not participants:
            logger.info("No participants to remove")
            return False
            
        logger.info(f"Removing {len(participants)} participants")
        
        # Select checkboxes
        for participant in participants:
            try:
                checkbox = participant["checkbox"]
                if not checkbox.is_selected():
                    # Scroll to element
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", checkbox)
                    time.sleep(0.1)
                    checkbox.click()
                    time.sleep(0.1)
                    logger.info(f"Selected participant with order {participant['order_number']}")
            except Exception as e:
                logger.error(f"Error selecting checkbox for {participant['order_number']}: {str(e)}")
        
        # Find and click remove button
        try:
            remove_button = None
            
            # Try different selectors for the remove button
            remove_selectors = [
                (By.XPATH, "//button[contains(text(), 'Remove Participants')]"),
                (By.XPATH, "//button[contains(text(), 'Remove')]"),
                (By.XPATH, "//button[contains(@class, 'remove')]")
            ]
            
            for by, selector in remove_selectors:
                try:
                    remove_button = self.driver.find_element(by, selector)
                    if remove_button and "remove" in remove_button.text.lower():
                        break
                except:
                    continue
            
            if not remove_button:
                # Method 2: Any button containing "Remove"
                buttons = self.driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    if "remove" in btn.text.lower() and ("participant" in btn.text.lower() or len(btn.text.strip()) < 20):
                        remove_button = btn
                        break
                        
            if remove_button:
                # Scroll to button and ensure it's visible
                self.driver.execute_script("arguments[0].scrollIntoView(true);", remove_button)
                time.sleep(0.5)
                
                if remove_button.is_enabled():
                    remove_button.click()
                    logger.info("Clicked Remove Participants button")
                    
                    if auto_confirm:
                        # Wait for confirmation dialog
                        time.sleep(1.5)
                        
                        # Try to find and click confirm button
                        try:
                            confirm_selectors = [
                                (By.XPATH, "//button[contains(text(), 'Confirm')]"),
                                (By.XPATH, "//button[contains(text(), 'Yes')]"),
                                (By.XPATH, "//button[contains(text(), 'OK')]"),
                                (By.XPATH, "//button[contains(@class, 'confirm')]"),
                                (By.XPATH, "//mat-dialog-container//button[not(contains(text(), 'Cancel'))]")
                            ]
                            
                            confirmed = False
                            for by, selector in confirm_selectors:
                                try:
                                    confirm_button = self.driver.find_element(by, selector)
                                    confirm_button.click()
                                    logger.info("Removal confirmed")
                                    time.sleep(2)  # Wait for removal to complete
                                    confirmed = True
                                    break
                                except:
                                    continue
                            
                            if not confirmed:
                                logger.warning("Confirmation button not found - manual confirmation may be required")
                                return False
                            
                            return True
                                    
                        except Exception as e:
                            logger.error(f"Error confirming removal: {str(e)}")
                            return False
                else:
                    logger.error("Remove button is disabled")
                    return False
            else:
                logger.error("Remove button not found")
                return False
                
        except Exception as e:
            logger.error(f"Error in removal process: {str(e)}")
            return False
    
    def process_all_divisions(self, program_id: str, order_numbers: List[str], program_name: str = "2025 Fall Core") -> List[Dict]:
        """Process all divisions and remove participants with specified order numbers"""
        logger.info(f"Starting bulk removal for order numbers: {order_numbers}")
        
        # Get divisions with waitlists
        waitlist_divisions = self.fetch_division_data(program_id, program_name)
        
        results = []
        
        for division in waitlist_divisions:
            division_id = str(division['divisionId'])
            division_name = division['divisionName']
            waitlist_count = division['waitlist']
            
            logger.info(f"\nProcessing {division_name} (Waitlist: {waitlist_count})")
            
            try:
                # Navigate to waitlist
                self.navigate_to_waitlist(division_id, division_name)
                
                # Find participants
                participants = self.find_participants_by_order(order_numbers)
                
                if participants:
                    # Remove participants
                    success = self.remove_participants(participants, auto_confirm=True)
                    
                    results.append({
                        "division": division_name,
                        "division_id": division_id,
                        "removed": len(participants) if success else 0,
                        "status": "success" if success else "failed",
                        "details": [p['order_number'] for p in participants],
                        "participants": [{"name": p['player_name'], "order": p['order_number']} for p in participants]
                    })
                else:
                    results.append({
                        "division": division_name,
                        "division_id": division_id,
                        "removed": 0,
                        "status": "no_matches",
                        "details": [],
                        "participants": []
                    })
                    
            except Exception as e:
                logger.error(f"Error processing {division_name}: {str(e)}")
                results.append({
                    "division": division_name,
                    "division_id": division_id,
                    "removed": 0,
                    "status": "error",
                    "error": str(e),
                    "details": [],
                    "participants": []
                })
                
        return results
    
    def process_single_division(self, division_id: str, division_name: str, order_numbers: List[str]) -> Dict:
        """Process a single division for waitlist removal"""
        logger.info(f"Processing single division: {division_name}")
        
        try:
            # Navigate to waitlist
            self.navigate_to_waitlist(division_id, division_name)
            
            # Find participants
            participants = self.find_participants_by_order(order_numbers)
            
            if participants:
                # Remove participants
                success = self.remove_participants(participants, auto_confirm=True)
                
                return {
                    "division": division_name,
                    "division_id": division_id,
                    "removed": len(participants) if success else 0,
                    "status": "success" if success else "failed",
                    "details": [p['order_number'] for p in participants],
                    "participants": [{"name": p['player_name'], "order": p['order_number']} for p in participants]
                }
            else:
                return {
                    "division": division_name,
                    "division_id": division_id,
                    "removed": 0,
                    "status": "no_matches",
                    "details": [],
                    "participants": []
                }
                
        except Exception as e:
            logger.error(f"Error processing {division_name}: {str(e)}")
            return {
                "division": division_name,
                "division_id": division_id,
                "removed": 0,
                "status": "error",
                "error": str(e),
                "details": [],
                "participants": []
            }
    
    def save_results(self, results: List[Dict], order_numbers: List[str], download_dir: str = "data/downloads") -> str:
        """Save waitlist removal results to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = os.path.join(download_dir, f"waitlist_removal_{timestamp}.json")
        
        # Ensure directory exists
        os.makedirs(download_dir, exist_ok=True)
        
        total_removed = sum(r['removed'] for r in results)
        
        results_data = {
            "timestamp": timestamp,
            "order_numbers": order_numbers,
            "total_removed": total_removed,
            "divisions_processed": len(results),
            "successful_divisions": len([r for r in results if r['status'] == 'success']),
            "results": results
        }
        
        with open(results_file, "w") as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"Waitlist removal results saved to: {results_file}")
        return results_file
    
    def get_waitlist_summary(self, program_id: str, program_name: str = "2025 Fall Core") -> Dict:
        """Get summary of all waitlists without removing anyone"""
        logger.info("Getting waitlist summary")
        
        divisions = self.fetch_division_data(program_id, program_name)
        waitlist_divisions = [d for d in divisions if d.get('waitlist', 0) > 0]
        
        summary = {
            "program_name": program_name,
            "program_id": program_id,
            "total_divisions": len(divisions),
            "divisions_with_waitlists": len(waitlist_divisions),
            "total_waitlist_participants": sum(d['waitlist'] for d in waitlist_divisions),
            "divisions": waitlist_divisions
        }
        
        logger.info(f"Waitlist summary: {len(waitlist_divisions)} divisions with {summary['total_waitlist_participants']} total waitlist participants")
        
        return summary