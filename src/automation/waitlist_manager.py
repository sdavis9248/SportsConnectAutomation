"""
Waitlist management for Sports Connect Automation
Updated to handle ngx-datatable with virtual scrolling
"""
import json
import time
import logging
import os
from typing import List, Dict, Optional
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
        """Find participants with specific order numbers using full table scroll via JS"""
        logger.info(f"Searching for order numbers: {order_numbers}")
        participants_to_remove = []

        try:
            # Inject JS to extract all rows
            logger.info("Injecting JavaScript to extract all rows from ngx-datatable")

            all_rows = self.driver.execute_async_script("""
                var done = arguments[0];
                (async () => {
                    const datatableBody = document.querySelector('ngx-datatable .datatable-body');
                    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                    const seen = new Set();
                    const allData = [];

                    let attempts = 0;
                    const maxAttempts = 50;

                    while (attempts < maxAttempts) {
                        let rows = Array.from(document.querySelectorAll('ngx-datatable datatable-body-row'));
                        let newRows = 0;

                        for (const row of rows) {
                            const cells = Array.from(row.querySelectorAll('datatable-body-cell'));
                            const values = cells.map(cell => cell.innerText.trim());
                            const key = values.join('|');

                            if (!seen.has(key)) {
                                seen.add(key);
                                allData.push(values);
                                newRows++;
                            }
                        }

                        if (newRows === 0) {
                            attempts++;
                        } else {
                            attempts = 0;
                        }

                        datatableBody.scrollTop += 200;
                        await sleep(300);
                    }

                    done(allData);
                })();
            """)

            logger.info(f"Total rows scraped: {len(all_rows)}")

            for i, row_data in enumerate(all_rows):
                if len(row_data) < 5:
                    logger.debug(f"Skipping row {i} due to insufficient columns: {row_data}")
                    continue

                order_number = row_data[1]
                if order_number in order_numbers:
                    player_first = row_data[3] if len(row_data) > 3 else ""
                    player_last = row_data[4] if len(row_data) > 4 else ""

                    participant_info = {
                        "order_number": order_number,
                        "player_name": f"{player_first} {player_last}".strip(),
                        "row_data": row_data,
                        "row_index": i,
                    }
                    participants_to_remove.append(participant_info)
                    logger.info(f"Matched: {participant_info['player_name']} (Order: {order_number})")

            if not participants_to_remove:
                logger.warning("No matching order numbers found.")
            else:
                logger.info(f"Found {len(participants_to_remove)} matching rows.")

        except Exception as e:
            logger.error(f"Error during row extraction or parsing: {str(e)}")

        return participants_to_remove
    
    def remove_participants(self, participants: List[Dict], auto_confirm: bool = True) -> bool:
        """Remove selected participants"""
        if not participants:
            logger.info("No participants to remove")
            return False
            
        logger.info(f"Removing {len(participants)} participants")
        
        # Select checkboxes by finding the row with matching order number
        for participant in participants:
            try:
                order_number = participant['order_number']
                player_name = participant['player_name']
                
                # Use JavaScript to find and click the checkbox for this specific order number
                checkbox_clicked = self.driver.execute_script("""
                    const orderNumber = arguments[0];
                    const rows = document.querySelectorAll('ngx-datatable datatable-body-row');
                    
                    for (const row of rows) {
                        const cells = Array.from(row.querySelectorAll('datatable-body-cell'));
                        // Check if this row contains our order number (typically in second cell)
                        if (cells.length > 1 && cells[1].innerText.trim() === orderNumber) {
                            // Find the checkbox in the first cell
                            const checkbox = row.querySelector('input[type="checkbox"], mat-checkbox input');
                            if (checkbox) {
                                // Scroll to the row
                                row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                // Click the checkbox if not already selected
                                if (!checkbox.checked) {
                                    checkbox.click();
                                    return true;
                                }
                                return 'already_selected';
                            }
                        }
                    }
                    return false;
                """, order_number)
                
                if checkbox_clicked is True:
                    logger.info(f"Selected participant {player_name} (Order: {order_number})")
                    time.sleep(0.2)  # Small delay between selections
                elif checkbox_clicked == 'already_selected':
                    logger.info(f"Participant {player_name} (Order: {order_number}) already selected")
                else:
                    logger.warning(f"Could not find checkbox for participant {player_name} (Order: {order_number})")
            except Exception as e:
                logger.error(f"Error selecting checkbox for {participant['order_number']}: {str(e)}")
        
        # Find and click remove button
        try:
            remove_button = None
            
            # Try different selectors for the remove button
            remove_selectors = [
                (By.XPATH, "//button[span[contains(text(), 'Remove Participants')]]"),
                (By.XPATH, "//button[contains(text(), 'Remove Participants')]"),  # fallback
                (By.XPATH, "//button[contains(@class, 'remove')]"),               # fallback
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
                                (By.XPATH, "//button[span[contains(text(), 'Save') and contains(text(), 'Finish')]]"),
                                (By.XPATH, "//button[.//text()[contains(., 'Save') and contains(., 'Finish')]]"),  # alternative
                                (By.XPATH, "//button[contains(@class, 'tshq-button--arrow-right')]"),                                 
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