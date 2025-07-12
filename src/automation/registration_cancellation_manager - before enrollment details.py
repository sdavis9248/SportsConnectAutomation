"""
Registration Cancellation Manager for Sports Connect Automation
Handles searching for and cancelling player registrations
"""
import os
import logging
import time
import pandas as pd
import glob
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from core.element_interactor import ElementInteractor

logger = logging.getLogger(__name__)

class RegistrationCancellationManager:
    """Manages registration cancellations in Sports Connect"""
    
    def __init__(self, driver, config=None, open_orders_file: str = None, already_logged_in: bool = True):
        """
        Initialize Registration Cancellation Manager
        
        Args:
            driver: Selenium WebDriver instance (from SportsConnectAutomation)
            config: Configuration manager instance
            open_orders_file: Path to Open Orders file (optional)
            already_logged_in: Whether we're already logged into Sports Connect (default True)
        """
        self.driver = driver
        self.config = config
        self.interactor = ElementInteractor(driver)
        self.wait = WebDriverWait(driver, 10)
        
        # Data storage
        self.open_orders_df = None
        self.open_orders_file = open_orders_file
        
        # Base URLs
        self.base_url = config.get('base_url', 'https://reporting.bluesombrero.com') if config else 'https://reporting.bluesombrero.com'
        self.org_id = config.get('organization_id', '14780') if config else '14780'
        
        # Track cancellations
        self.cancellation_results = []
        self.already_logged_in = already_logged_in  # We're using existing Sports Connect session
    
    def load_open_orders_data(self, file_path: str = None) -> bool:
        """
        Load Open Orders data from Excel file
        
        Args:
            file_path: Path to Open Orders file (uses latest if not provided)
            
        Returns:
            True if successful
        """
        try:
            if file_path:
                self.open_orders_file = file_path
            elif not self.open_orders_file:
                # Find latest Open Orders file
                download_dir = self.config.get('download_dir', 'data/downloads') if self.config else 'data/downloads'
                self.open_orders_file = self._find_latest_open_orders_file(download_dir)
            
            logger.info(f"Loading Open Orders data from: {self.open_orders_file}")
            self.open_orders_df = pd.read_excel(self.open_orders_file)
            
            logger.info(f"Loaded {len(self.open_orders_df)} records")
            return True
            
        except Exception as e:
            logger.error(f"Error loading Open Orders data: {e}")
            return False
    
    def _find_latest_open_orders_file(self, download_dir: str) -> str:
        """Find the most recent Open Orders file"""
        pattern = os.path.join(download_dir, "Open_Orders_Line_Item*.xlsx")
        files = glob.glob(pattern)
        
        if not files:
            pattern = os.path.join(download_dir, "*Open*Orders*.xlsx")
            files = glob.glob(pattern)
        
        if not files:
            raise FileNotFoundError(f"No Open Orders files found in {download_dir}")
        
        # Get the most recent file
        return max(files, key=os.path.getmtime)
    
    def search_registrations(self, **criteria) -> pd.DataFrame:
        """
        Search for registrations based on criteria
        
        Args:
            **criteria: Search criteria (email, first_name, last_name, order_no, etc.)
            
        Returns:
            DataFrame with matching registrations
        """
        if self.open_orders_df is None:
            if not self.load_open_orders_data():
                return pd.DataFrame()
        
        mask = pd.Series([True] * len(self.open_orders_df))
        
        # Apply search criteria
        if 'email' in criteria:
            email_lower = criteria['email'].lower()
            mask &= (
                (self.open_orders_df['User Email'].str.lower() == email_lower) |
                (self.open_orders_df['Additional Email'].str.lower() == email_lower)
            )
        
        if 'first_name' in criteria:
            mask &= self.open_orders_df['Player First Name'].str.lower() == criteria['first_name'].lower()
        
        if 'last_name' in criteria:
            mask &= self.open_orders_df['Player Last Name'].str.lower() == criteria['last_name'].lower()
        
        if 'order_no' in criteria:
            mask &= self.open_orders_df['Order No'].astype(str) == str(criteria['order_no'])
        
        if 'program_name' in criteria:
            mask &= self.open_orders_df['Program Name'].str.contains(criteria['program_name'], case=False, na=False)
        
        if 'division_name' in criteria:
            mask &= self.open_orders_df['Division Name'].str.contains(criteria['division_name'], case=False, na=False)
        
        results = self.open_orders_df[mask]
        logger.info(f"Found {len(results)} matching registrations")
        
        return results
    
    def navigate_to_order_management(self) -> bool:
        """Navigate to the AYSO58 order management page"""
        try:
            # Since we're already logged into Sports Connect/Blue Sombrero,
            # we should be able to navigate directly to the order management page
            url = "https://www.ayso58.org/Default.aspx?tabid=813733"
            logger.info(f"Navigating to AYSO58 order management: {url}")
            self.driver.get(url)
            
            # Wait for page to load
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(3)
            
            # Check if we're redirected to login (shouldn't happen with shared session)
            current_url = self.driver.current_url.lower()
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            
            if "login" in current_url or "sign in" in page_text:
                logger.warning("Unexpected login page - shared session may not be working")
                logger.info("This might happen if AYSO58 uses a different subdomain")
                return False
            
            # Verify we're on the order management page
            if "tabid=813733" not in self.driver.current_url:
                logger.warning("Not on order management page after navigation")
                return False
            
            logger.info("Successfully navigated to order management page")
            return True
            
        except Exception as e:
            logger.error(f"Error navigating to order management: {e}")
            return False
    
    def search_order_in_system(self, order_no: str) -> bool:
        """
        Search for an order in the AYSO58 system
        
        Args:
            order_no: Order number to search for
            
        Returns:
            True if order found and Manage button clicked
        """
        try:
            # Navigate to order management if not already there
            if "tabid=813733" not in self.driver.current_url:
                if not self.navigate_to_order_management():
                    return False
            
            # Find search input - common patterns for AYSO sites
            search_selectors = [
                (By.ID, "dnn_ctr2157_ViewBSAccount_Orders_txtSearch"),
                (By.CSS_SELECTOR, "input[id*='txtSearch']"),
                (By.CSS_SELECTOR, "input[id*='Orders_txtSearch']"),
                (By.XPATH, "//input[contains(@id, 'txtSearch')]"),
                (By.CSS_SELECTOR, "input[placeholder*='Search']"),
                (By.CSS_SELECTOR, "input[type='text'][id*='Search']")
            ]
            
            # Clear and enter order number
            search_input_found = False
            for by, selector in search_selectors:
                try:
                    search_input = self.driver.find_element(by, selector)
                    search_input.clear()
                    search_input.send_keys(str(order_no))
                    logger.info(f"Entered order number: {order_no}")
                    search_input_found = True
                    break
                except:
                    continue
            
            if not search_input_found:
                logger.error("Could not find search input")
                return False
            
            # Click search button
            search_button_selectors = [
                (By.ID, "dnn_ctr2157_ViewBSAccount_Orders_btnSearch"),
                (By.CSS_SELECTOR, "a[id*='btnSearch']"),
                (By.CSS_SELECTOR, "input[id*='btnSearch']"),
                (By.XPATH, "//a[contains(@id, 'btnSearch')]"),
                (By.XPATH, "//input[contains(@id, 'btnSearch')]"),
                (By.CSS_SELECTOR, "a.searchButton"),
                (By.XPATH, "//a[contains(text(), 'Search')]")
            ]
            
            search_clicked = False
            for by, selector in search_button_selectors:
                try:
                    search_btn = self.driver.find_element(by, selector)
                    search_btn.click()
                    logger.info("Clicked search button")
                    search_clicked = True
                    break
                except:
                    continue
            
            if not search_clicked:
                # Try pressing Enter in search field as fallback
                try:
                    from selenium.webdriver.common.keys import Keys
                    search_input.send_keys(Keys.RETURN)
                    logger.info("Pressed Enter to search")
                except:
                    logger.error("Could not submit search")
                    return False
            
            # Wait for results to load
            time.sleep(3)
            
            # Look for the Manage button in the results
            manage_button_selectors = [
                (By.XPATH, f"//tr[contains(., '{order_no}')]//a[contains(text(), 'Manage')]"),
                (By.XPATH, f"//tr[contains(., '{order_no}')]//input[@value='Manage']"),
                (By.XPATH, "//a[contains(@id, 'Manage') and contains(text(), 'Manage')]"),
                (By.XPATH, "//input[contains(@id, 'Manage') and @value='Manage']"),
                (By.CSS_SELECTOR, "a.manageButton"),
                (By.CSS_SELECTOR, "input[value='Manage']"),
                (By.XPATH, "//a[text()='Manage']")
            ]
            
            manage_clicked = False
            for by, selector in manage_button_selectors:
                try:
                    manage_btn = self.driver.find_element(by, selector)
                    manage_btn.click()
                    logger.info(f"Clicked Manage button for order {order_no}")
                    manage_clicked = True
                    break
                except:
                    continue
            
            if not manage_clicked:
                logger.warning(f"Could not find Manage button for order {order_no}")
                
                # Check if no results found
                no_results_indicators = [
                    "No orders found",
                    "No results",
                    "0 orders"
                ]
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                for indicator in no_results_indicators:
                    if indicator.lower() in page_text.lower():
                        logger.warning(f"Order {order_no} not found in system")
                        return False
                
                return False
            
            # Wait for order details page to load
            time.sleep(3)
            
            return True
            
        except Exception as e:
            logger.error(f"Error searching for order: {e}")
            return False
    
    def cancel_registration(self, order_no: str, player_info: Dict = None) -> Dict:
        """
        Cancel a registration for a specific order
        
        Args:
            order_no: Order number to cancel
            player_info: Optional player information for verification
            
        Returns:
            Dictionary with cancellation results
        """
        result = {
            "order_no": order_no,
            "status": "failed",
            "message": "",
            "player_info": player_info
        }
        
        try:
            # Search for the order and click Manage
            if not self.search_order_in_system(order_no):
                result["message"] = "Order not found or could not access order management"
                return result
            
            # Now we should be on the order details page
            # Wait for page to fully load
            time.sleep(3)
            
            # Look for cancellation/void/refund options on the order page
            cancel_selectors = [
                # Common patterns for AYSO order management
                (By.XPATH, "//a[contains(text(), 'Void Order')]"),
                (By.XPATH, "//input[@value='Void Order']"),
                (By.XPATH, "//a[contains(text(), 'Cancel Order')]"),
                (By.XPATH, "//input[@value='Cancel Order']"),
                (By.XPATH, "//a[contains(text(), 'Void')]"),
                (By.XPATH, "//input[@value='Void']"),
                (By.XPATH, "//a[contains(text(), 'Cancel')]"),
                (By.XPATH, "//input[@value='Cancel']"),
                (By.CSS_SELECTOR, "a[id*='VoidOrder']"),
                (By.CSS_SELECTOR, "input[id*='VoidOrder']"),
                (By.CSS_SELECTOR, "a.voidButton"),
                (By.CSS_SELECTOR, "input.voidButton")
            ]
            
            cancel_clicked = False
            for by, selector in cancel_selectors:
                try:
                    cancel_btn = self.driver.find_element(by, selector)
                    # Scroll to element
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", cancel_btn)
                    time.sleep(0.5)
                    cancel_btn.click()
                    logger.info("Clicked cancellation/void button")
                    cancel_clicked = True
                    break
                except:
                    continue
            
            if not cancel_clicked:
                # Check if order is already voided/cancelled
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                if any(status in page_text.lower() for status in ["voided", "cancelled", "void", "refunded"]):
                    result["message"] = "Order appears to be already voided/cancelled"
                else:
                    result["message"] = "Cancellation option not available for this order"
                return result
            
            # Handle confirmation dialog if it appears
            time.sleep(2)
            
            # Look for confirmation dialog/popup
            confirm_selectors = [
                # Common confirmation patterns
                (By.XPATH, "//input[@value='OK']"),
                (By.XPATH, "//input[@value='Yes']"),
                (By.XPATH, "//input[@value='Confirm']"),
                (By.XPATH, "//button[text()='OK']"),
                (By.XPATH, "//button[text()='Yes']"),
                (By.XPATH, "//button[text()='Confirm']"),
                (By.CSS_SELECTOR, "input[id*='btnOK']"),
                (By.CSS_SELECTOR, "input[id*='btnYes']"),
                (By.CSS_SELECTOR, "input[id*='btnConfirm']"),
                # Handle JavaScript alerts
                (By.XPATH, "//div[@class='modal-footer']//button[contains(text(), 'OK')]"),
                (By.XPATH, "//div[@class='modal-footer']//button[contains(text(), 'Yes')]")
            ]
            
            # First try to handle JavaScript alert
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                logger.info(f"Alert found: {alert_text}")
                alert.accept()
                logger.info("Alert accepted")
                time.sleep(2)
            except:
                # No JavaScript alert, look for HTML confirmation
                pass
            
            # Try HTML confirmation buttons
            for by, selector in confirm_selectors:
                try:
                    confirm_btn = self.driver.find_element(by, selector)
                    confirm_btn.click()
                    logger.info("Clicked confirmation button")
                    break
                except:
                    continue
            
            # Wait for operation to complete
            time.sleep(3)
            
            # Check if cancellation was successful
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            
            success_indicators = [
                "successfully voided",
                "successfully cancelled",
                "order has been voided",
                "order has been cancelled",
                "void successful",
                "cancellation successful",
                "order status: void",
                "order status: cancelled"
            ]
            
            for indicator in success_indicators:
                if indicator in page_text:
                    logger.info(f"Cancellation confirmed for order {order_no}")
                    result["status"] = "success"
                    result["message"] = "Registration cancelled successfully"
                    return result
            
            # If we can't confirm success, check order status
            if "void" in page_text or "cancel" in page_text:
                result["status"] = "success"
                result["message"] = "Order appears to have been voided/cancelled"
            else:
                result["message"] = "Cancellation status unclear - manual verification recommended"
            
            return result
            
        except Exception as e:
            logger.error(f"Error cancelling registration: {e}")
            result["message"] = f"Error: {str(e)}"
            return result
    
    def bulk_cancel_registrations(self, criteria: Dict = None, order_numbers: List[str] = None) -> List[Dict]:
        """
        Cancel multiple registrations based on criteria or order numbers
        
        Args:
            criteria: Search criteria to find registrations
            order_numbers: List of specific order numbers to cancel
            
        Returns:
            List of cancellation results
        """
        results = []
        
        # Get registrations to cancel
        if order_numbers:
            # Use provided order numbers
            registrations_to_cancel = []
            for order_no in order_numbers:
                reg_data = self.search_registrations(order_no=order_no)
                if not reg_data.empty:
                    registrations_to_cancel.append({
                        'order_no': order_no,
                        'player_info': reg_data.iloc[0].to_dict()
                    })
        elif criteria:
            # Search based on criteria
            matching_regs = self.search_registrations(**criteria)
            registrations_to_cancel = [
                {
                    'order_no': str(row['Order No']),
                    'player_info': row.to_dict()
                }
                for _, row in matching_regs.iterrows()
            ]
        else:
            logger.error("No criteria or order numbers provided")
            return results
        
        logger.info(f"Found {len(registrations_to_cancel)} registrations to cancel")
        
        # Confirm before proceeding
        if len(registrations_to_cancel) > 0:
            logger.warning(f"About to cancel {len(registrations_to_cancel)} registrations")
            # In production, you might want to add a confirmation prompt here
        
        # Process cancellations
        for reg in registrations_to_cancel:
            logger.info(f"Processing cancellation for order {reg['order_no']}")
            
            result = self.cancel_registration(
                reg['order_no'],
                reg.get('player_info')
            )
            
            results.append(result)
            self.cancellation_results.append(result)
            
            # Add delay between cancellations
            if len(registrations_to_cancel) > 1:
                time.sleep(2)
        
        # Summary
        successful = sum(1 for r in results if r['status'] == 'success')
        logger.info(f"Cancellation complete: {successful}/{len(results)} successful")
        
        return results
    
    @classmethod
    def create_from_automation(cls, automation_instance, open_orders_file: str = None):
        """
        Factory method to create RegistrationCancellationManager from SportsConnectAutomation
        
        Args:
            automation_instance: Instance of SportsConnectAutomation (already logged in)
            open_orders_file: Optional path to Open Orders file
            
        Returns:
            RegistrationCancellationManager instance
        """
        return cls(
            driver=automation_instance.driver,
            config=automation_instance.config,
            open_orders_file=open_orders_file,
            already_logged_in=True
        )
    
    def save_cancellation_report(self, results: List[Dict] = None) -> str:
        """
        Save cancellation results to a report file
        
        Args:
            results: Cancellation results (uses stored results if not provided)
            
        Returns:
            Path to report file
        """
        if results is None:
            results = self.cancellation_results
        
        if not results:
            logger.warning("No cancellation results to save")
            return None
        
        # Create report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_dir = self.config.get('download_dir', 'data/downloads') if self.config else 'data/downloads'
        report_path = os.path.join(download_dir, f"cancellation_report_{timestamp}.txt")
        
        with open(report_path, 'w') as f:
            f.write("Registration Cancellation Report\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Processed: {len(results)}\n")
            
            successful = [r for r in results if r['status'] == 'success']
            failed = [r for r in results if r['status'] != 'success']
            
            f.write(f"Successful: {len(successful)}\n")
            f.write(f"Failed: {len(failed)}\n\n")
            
            # Successful cancellations
            if successful:
                f.write("SUCCESSFUL CANCELLATIONS:\n")
                f.write("-" * 30 + "\n")
                for result in successful:
                    f.write(f"Order: {result['order_no']}\n")
                    if result.get('player_info'):
                        info = result['player_info']
                        f.write(f"  Player: {info.get('Player First Name', '')} {info.get('Player Last Name', '')}\n")
                        f.write(f"  Division: {info.get('Division Name', '')}\n")
                        f.write(f"  Program: {info.get('Program Name', '')}\n")
                    f.write(f"  Message: {result['message']}\n\n")
            
            # Failed cancellations
            if failed:
                f.write("\nFAILED CANCELLATIONS:\n")
                f.write("-" * 30 + "\n")
                for result in failed:
                    f.write(f"Order: {result['order_no']}\n")
                    if result.get('player_info'):
                        info = result['player_info']
                        f.write(f"  Player: {info.get('Player First Name', '')} {info.get('Player Last Name', '')}\n")
                    f.write(f"  Error: {result['message']}\n\n")
        
        logger.info(f"Cancellation report saved to: {report_path}")
        return report_path
    
    def interactive_cancellation(self) -> List[Dict]:
        """
        Interactive mode for finding and cancelling registrations
        """
        results = []
        
        print("\nRegistration Cancellation - Interactive Mode")
        print("=" * 50)
        
        # Load data if not already loaded
        if self.open_orders_df is None:
            if not self.load_open_orders_data():
                print("Error: Could not load Open Orders data")
                return results
        
        while True:
            print("\nSearch Options:")
            print("1. Search by email")
            print("2. Search by player name")
            print("3. Search by order number")
            print("4. Search by program/division")
            print("5. Show recent orders")
            print("0. Exit")
            
            choice = input("\nEnter choice (0-5): ").strip()
            
            if choice == '0':
                break
            
            search_results = pd.DataFrame()
            
            if choice == '1':
                email = input("Enter email address: ").strip()
                search_results = self.search_registrations(email=email)
                
            elif choice == '2':
                first = input("First name (or press Enter to skip): ").strip()
                last = input("Last name (or press Enter to skip): ").strip()
                criteria = {}
                if first:
                    criteria['first_name'] = first
                if last:
                    criteria['last_name'] = last
                search_results = self.search_registrations(**criteria)
                
            elif choice == '3':
                order_no = input("Enter order number: ").strip()
                search_results = self.search_registrations(order_no=order_no)
                
            elif choice == '4':
                program = input("Program name (or part of it): ").strip()
                division = input("Division (or press Enter for all): ").strip()
                criteria = {'program_name': program}
                if division:
                    criteria['division_name'] = division
                search_results = self.search_registrations(**criteria)
                
            elif choice == '5':
                # Show recent orders
                recent_date = pd.Timestamp.now() - pd.Timedelta(days=7)
                mask = pd.to_datetime(self.open_orders_df['Order Date']) > recent_date
                search_results = self.open_orders_df[mask].head(20)
            
            if search_results.empty:
                print("No results found")
                continue
            
            # Display results
            print(f"\nFound {len(search_results)} registration(s):")
            for idx, (_, row) in enumerate(search_results.iterrows()):
                print(f"\n{idx + 1}. Order: {row['Order No']}")
                print(f"   Player: {row['Player First Name']} {row['Player Last Name']}")
                print(f"   Division: {row['Division Name']}")
                print(f"   Program: {row['Program Name']}")
                print(f"   Email: {row['User Email']}")
                print(f"   Amount: ${row['Order Amount']:.2f}")
                print(f"   Status: {row['Order Payment Status']}")
            
            # Ask which to cancel
            if input("\nDo you want to cancel any of these? (y/n): ").lower() == 'y':
                selections = input("Enter numbers to cancel (comma-separated) or 'all': ").strip()
                
                orders_to_cancel = []
                if selections.lower() == 'all':
                    orders_to_cancel = [str(row['Order No']) for _, row in search_results.iterrows()]
                else:
                    try:
                        indices = [int(x.strip()) - 1 for x in selections.split(',')]
                        for idx in indices:
                            if 0 <= idx < len(search_results):
                                orders_to_cancel.append(str(search_results.iloc[idx]['Order No']))
                    except:
                        print("Invalid selection")
                        continue
                
                if orders_to_cancel:
                    print(f"\nAbout to cancel {len(orders_to_cancel)} registration(s)")
                    if input("Are you sure? (y/n): ").lower() == 'y':
                        cancel_results = self.bulk_cancel_registrations(order_numbers=orders_to_cancel)
                        results.extend(cancel_results)
                        
                        # Show summary
                        successful = sum(1 for r in cancel_results if r['status'] == 'success')
                        print(f"\nCancelled {successful}/{len(cancel_results)} registrations")
        
        return results