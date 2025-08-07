"""
Waitlist management for Sports Connect Automation
Updated to handle ngx-datatable with virtual scrolling
"""
import json
import time
import logging
import os
from typing import List, Any, Dict, Optional
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
            (By.XPATH, '//span[contains(@class, "mat-select-placeholder") and normalize-space()=""]'),
            (By.XPATH, '//span[@class="mat-select-placeholder ng-tns-c247-4 ng-star-inserted"]'),
            (By.XPATH, '//mat-option[.//span[contains(@class,"mat-option-text") and normalize-space()="Select All"]]'),
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
            
                # First, use the search box to filter to this order number
                logger.info(f"Searching for order number: {order_number}")
            
                # Find the search input
                search_selectors = [
                    (By.ID, "mat-input-0"),
                    (By.CSS_SELECTOR, "input[matinput]"),
                    (By.CSS_SELECTOR, "input.mat-input-element"),
                    (By.XPATH, "//input[@matinput]"),
                    (By.XPATH, "//input[contains(@class, 'mat-input-element')]")
                ]
            
                search_input = None
                for by, selector in search_selectors:
                    try:
                        search_input = self.driver.find_element(by, selector)
                        if search_input:
                            break
                    except:
                        continue
            
                if not search_input:
                    logger.error("Could not find search input")
                    continue
            
                # Clear the search box and enter the order number
                search_input.clear()
                search_input.send_keys(order_number)
            
                # Wait a moment for the table to filter
                time.sleep(1.5)
            
                # Now use JavaScript to find and click the checkbox for this specific order number
                checkbox_clicked = self.driver.execute_script("""
                    const orderNumber = arguments[0];
                    const rows = document.querySelectorAll('ngx-datatable datatable-body-row');
                
                    console.log('Looking for order number:', orderNumber);
                    console.log('Found', rows.length, 'rows after filtering');
                
                    for (const row of rows) {
                        const cells = Array.from(row.querySelectorAll('datatable-body-cell'));
                    
                        // The order number is in the second cell (index 1)
                        if (cells.length > 1) {
                            const orderCell = cells[1];
                            const cellText = orderCell.innerText.trim();
                        
                            console.log('Checking cell text:', cellText);
                        
                            if (cellText === orderNumber) {
                                console.log('Found matching order!');
                            
                                // Find the checkbox in the FIRST cell (index 0)
                                const checkboxCell = cells[0];
                                const checkbox = checkboxCell.querySelector('input[type="checkbox"]');
                            
                                if (checkbox) {
                                    // Scroll to the row
                                    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                
                                    // Click the checkbox if not already selected
                                    if (!checkbox.checked) {
                                        checkbox.click();
                                        console.log('Checkbox clicked');
                                        return true;
                                    }
                                    console.log('Checkbox already selected');
                                    return 'already_selected';
                                } else {
                                    console.log('Checkbox not found in first cell');
                                }
                            }
                        }
                    }
                
                    console.log('Order number not found in filtered results');
                    return false;
                """, order_number)
            
                if checkbox_clicked is True:
                    logger.info(f"Selected participant {player_name} (Order: {order_number})")
                elif checkbox_clicked == 'already_selected':
                    logger.info(f"Participant {player_name} (Order: {order_number}) already selected")
                else:
                    logger.warning(f"Could not find checkbox for participant {player_name} (Order: {order_number})")
                
                # Clear the search box for the next iteration
                search_input.clear()
                time.sleep(0.2)  # Small delay between selections
            
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
    def process_non_responders(self, program_id: str, days_no_response: int = 3, 
                              program_name: str = "2025 Fall Core") -> Dict[str, Any]:
        """
        Process removal of waitlist participants who haven't responded to confirmation requests
    
        Args:
            program_id: Program ID
            days_no_response: Number of days without response before removal
            program_name: Name of the program
        
        Returns:
            Dictionary with results
        """
        logger.info(f"Processing non-responders (no response for {days_no_response}+ days)")
    
        try:
            # Import the response tracker
            from automation.waitlist_persistence import WaitlistResponseTracker
        
            # Create tracker instance
            tracker = WaitlistResponseTracker()
        
            # Get list of pending responses
            pending = tracker.get_pending_responses()
        
            # Filter for those who haven't responded in X days
            non_responders = []
            for participant in pending:
                if participant['days_waiting'] >= days_no_response:
                    non_responders.append({
                        'order_number': participant['order_number'],
                        'player_name': participant['player_name'],
                        'division': participant['division'],
                        'email': participant['email'],
                        'days_waiting': participant['days_waiting'],
                        'notified_date': participant['notified_date']
                    })
        
            if not non_responders:
                logger.info(f"No participants have been waiting {days_no_response}+ days")
                return {
                    "total_non_responders": 0,
                    "processed": 0,
                    "results": []
                }
        
            logger.info(f"Found {len(non_responders)} participants who haven't responded in {days_no_response}+ days")
        
            # Log the non-responders
            for nr in non_responders:
                logger.info(f"  - {nr['player_name']} ({nr['division']}) - {nr['days_waiting']} days - Order: {nr['order_number']}")
        
            # Get confirmation before proceeding
            if self.config and self.config.get('waitlist_config', {}).get('auto_remove_non_responders', False):
                logger.info("Auto-removal enabled, proceeding with removal")
            else:
                # In interactive mode, would ask for confirmation here
                logger.warning("Manual confirmation required for non-responder removal")
        
            # Get divisions with waitlists
            waitlist_divisions = self.fetch_division_data(program_id, program_name)
        
            # Group non-responders by division
            by_division = {}
            for nr in non_responders:
                division = nr['division']
                if division not in by_division:
                    by_division[division] = []
                by_division[division].append(nr)
        
            # Process each division
            results = []
            total_removed = 0
        
            for division_name, division_participants in by_division.items():
                logger.info(f"\nProcessing {len(division_participants)} non-responders in {division_name}")
            
                # Find the division ID
                division_id = None
                for div in waitlist_divisions:
                    if div['divisionName'] == division_name:
                        division_id = str(div['divisionId'])
                        break
            
                if not division_id:
                    logger.warning(f"Could not find division ID for {division_name}")
                    continue
            
                # Navigate to waitlist for this division
                self.navigate_to_waitlist(division_id, division_name)
            
                # Convert to participant format expected by remove_participants
                participants_to_remove = [
                    {
                        'order_number': p['order_number'],
                        'player_name': p['player_name']
                    }
                    for p in division_participants
                ]
            
                # Remove participants
                success = self.remove_participants(participants_to_remove, auto_confirm=True)
            
                if success:
                    removed_count = len(participants_to_remove)
                    total_removed += removed_count
                
                    # Record the removal in the tracker
                    for p in division_participants:
                        tracker.record_response(p['order_number'], 'removed_no_response', 'system')
                
                    results.append({
                        "division": division_name,
                        "division_id": division_id,
                        "removed": removed_count,
                        "status": "success",
                        "participants": division_participants
                    })
                else:
                    results.append({
                        "division": division_name,
                        "division_id": division_id,
                        "removed": 0,
                        "status": "failed",
                        "participants": division_participants
                    })
        
            # Save results
            results_data = {
                "type": "non_responder_removal",
                "days_no_response": days_no_response,
                "total_non_responders": len(non_responders),
                "total_removed": total_removed,
                "timestamp": datetime.now().isoformat(),
                "results": results
            }
        
            # Save to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = os.path.join(
                self.config.download_dir if self.config else "data/downloads",
                f"non_responder_removal_{timestamp}.json"
            )
        
            with open(results_file, "w") as f:
                json.dump(results_data, f, indent=2)
        
            logger.info(f"\nNon-responder removal complete:")
            logger.info(f"  - Total non-responders: {len(non_responders)}")
            logger.info(f"  - Successfully removed: {total_removed}")
            logger.info(f"  - Results saved to: {results_file}")
        
            return results_data
        
        except Exception as e:
            logger.error(f"Error processing non-responders: {e}")
            return {
                "error": str(e),
                "total_non_responders": 0,
                "processed": 0,
                "results": []
            }

    def get_non_responder_summary(self, days_no_response: int = 3) -> Dict[str, Any]:
        """
        Get summary of participants who haven't responded without removing them
    
        Args:
            days_no_response: Number of days to consider as non-response
        
        Returns:
            Summary dictionary
        """
        try:
            from automation.waitlist_persistence import WaitlistResponseTracker
        
            tracker = WaitlistResponseTracker()
            pending = tracker.get_pending_responses()
        
            # Categorize by days waiting
            categories = {
                "0-2 days": [],
                "3-5 days": [],
                "6-10 days": [],
                "10+ days": []
            }
        
            non_responders = []
        
            for participant in pending:
                days = participant['days_waiting']
            
                if days >= days_no_response:
                    non_responders.append(participant)
            
                if days <= 2:
                    categories["0-2 days"].append(participant)
                elif days <= 5:
                    categories["3-5 days"].append(participant)
                elif days <= 10:
                    categories["6-10 days"].append(participant)
                else:
                    categories["10+ days"].append(participant)
        
            # Group by division
            by_division = {}
            for nr in non_responders:
                div = nr['division']
                if div not in by_division:
                    by_division[div] = []
                by_division[div].append(nr)
        
            summary = {
                "total_pending": len(pending),
                "non_responders": len(non_responders),
                "threshold_days": days_no_response,
                "by_days_waiting": {
                    category: len(participants) 
                    for category, participants in categories.items()
                },
                "non_responders_by_division": {
                    div: len(participants) 
                    for div, participants in by_division.items()
                },
                "oldest_pending": max(pending, key=lambda x: x['days_waiting']) if pending else None,
                "details": non_responders
            }
        
            return summary
        
        except Exception as e:
            logger.error(f"Error getting non-responder summary: {e}")
            return {
                "error": str(e),
                "total_pending": 0,
                "non_responders": 0
            }

    def create_non_responder_report(self, days_no_response: int = 3, 
                                   save_to_file: bool = True) -> str:
        """
        Create a detailed report of non-responders
    
        Args:
            days_no_response: Number of days to consider as non-response
            save_to_file: Whether to save report to file
        
        Returns:
            Report content as string
        """
        summary = self.get_non_responder_summary(days_no_response)
    
        report = []
        report.append("Waitlist Non-Responder Report")
        report.append("=" * 50)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Non-response threshold: {days_no_response} days\n")
    
        report.append("Summary:")
        report.append(f"  Total pending responses: {summary['total_pending']}")
        report.append(f"  Non-responders ({days_no_response}+ days): {summary['non_responders']}")
    
        if summary.get('by_days_waiting'):
            report.append("\nPending by Days Waiting:")
            for category, count in summary['by_days_waiting'].items():
                report.append(f"  {category}: {count}")
    
        if summary.get('non_responders_by_division'):
            report.append(f"\nNon-Responders by Division ({days_no_response}+ days):")
            for division, count in summary['non_responders_by_division'].items():
                report.append(f"  {division}: {count}")
    
        if summary.get('details'):
            report.append(f"\nDetailed Non-Responder List ({days_no_response}+ days):")
            report.append("-" * 50)
        
            # Sort by days waiting (oldest first)
            details = sorted(summary['details'], key=lambda x: x['days_waiting'], reverse=True)
        
            for participant in details:
                report.append(f"\nOrder: {participant['order_number']}")
                report.append(f"  Player: {participant['player_name']}")
                report.append(f"  Division: {participant['division']}")
                report.append(f"  Email: {participant['email']}")
                report.append(f"  Days waiting: {participant['days_waiting']}")
                report.append(f"  Notified: {participant['notified_date']}")
    
        report_text = "\n".join(report)
    
        if save_to_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = os.path.join(
                self.config.download_dir if self.config else "data/downloads",
                f"non_responder_report_{timestamp}.txt"
            )
        
            with open(report_file, "w") as f:
                f.write(report_text)
        
            logger.info(f"Report saved to: {report_file}")
    
        return report_text

    # Add these methods to the WaitlistManager class

    def remove_by_response_status(self, program_id: str, removal_criteria: Dict[str, Any],
                                 program_name: str = "2025 Fall Core") -> Dict[str, Any]:
        """
        Remove participants based on their response status
    
        Args:
            program_id: Program ID
            removal_criteria: Dictionary with criteria like:
                - days_no_response: Remove if no response for X days
                - remove_declined: Remove those who said 'no'
                - remove_no_response_only: Only remove non-responders
            program_name: Program name
        
        Returns:
            Results dictionary
        """
        days_no_response = removal_criteria.get('days_no_response', 3)
        remove_declined = removal_criteria.get('remove_declined', False)
        remove_no_response_only = removal_criteria.get('remove_no_response_only', True)
    
        logger.info(f"Removing participants based on response status")
        logger.info(f"  Days no response: {days_no_response}")
        logger.info(f"  Remove declined: {remove_declined}")
    
        all_results = {
            "non_responders": {},
            "declined": {},
            "total_removed": 0
        }
    
        # Process non-responders
        if remove_no_response_only or not remove_declined:
            non_responder_results = self.process_non_responders(
                program_id, days_no_response, program_name
            )
            all_results["non_responders"] = non_responder_results
            all_results["total_removed"] += non_responder_results.get("total_removed", 0)
    
        # Process declined responses if requested
        if remove_declined:
            # This would process those who explicitly said 'no'
            # Implementation would be similar to process_non_responders
            pass
    
        return all_results    
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