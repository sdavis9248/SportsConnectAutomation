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
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from core.element_interactor import ElementInteractor

logger = logging.getLogger(__name__)

class RegistrationCancellationManager:
    """Manages registration cancellations in Sports Connect"""
    
    def __init__(self, driver, config=None, enrollment_details_file: str = None, already_logged_in: bool = True):
        """
        Initialize Registration Cancellation Manager
        
        Args:
            driver: Selenium WebDriver instance (from SportsConnectAutomation)
            config: Configuration manager instance
            enrollment_details_file: Path to Enrollment Details file (optional)
            already_logged_in: Whether we're already logged into Sports Connect (default True)
        """
        self.driver = driver
        self.config = config
        self.interactor = ElementInteractor(driver)
        self.wait = WebDriverWait(driver, 10)
        
        # Data storage
        self.enrollment_df = None
        self.enrollment_details_file = enrollment_details_file
        
        # Base URLs
        self.base_url = config.get('base_url', 'https://reporting.bluesombrero.com') if config else 'https://reporting.bluesombrero.com'
        self.org_id = config.get('organization_id', '14780') if config else '14780'
        
        # Track cancellations
        self.cancellation_results = []
        self.already_logged_in = already_logged_in  # We're using existing Sports Connect session
        
        # Store last refund details for email generation
        self.last_refund_details = None
    
    def load_enrollment_details(self, file_path: str = None) -> bool:
        """
        Load Enrollment Details data from Excel file
        
        Args:
            file_path: Path to Enrollment Details file (uses latest if not provided)
            
        Returns:
            True if successful
        """
        try:
            if file_path:
                self.enrollment_details_file = file_path
            elif not self.enrollment_details_file:
                # Find latest Enrollment Details file
                download_dir = self.config.get('download_dir', 'data/downloads') if self.config else 'data/downloads'
                self.enrollment_details_file = self._find_latest_enrollment_file(download_dir)
            
            logger.info(f"Loading Enrollment Details data from: {self.enrollment_details_file}")
            self.enrollment_df = pd.read_excel(self.enrollment_details_file)
            
            logger.info(f"Loaded {len(self.enrollment_df)} records")
            return True
            
        except Exception as e:
            logger.error(f"Error loading Enrollment Details data: {e}")
            return False
    
    def load_open_orders_data(self, file_path: str = None) -> bool:
        """
        Backward compatibility method - redirects to load_enrollment_details
        
        Args:
            file_path: Path to file (uses latest if not provided)
            
        Returns:
            True if successful
        """
        logger.info("load_open_orders_data called - redirecting to load_enrollment_details")
        return self.load_enrollment_details(file_path)
    
    def _find_latest_enrollment_file(self, download_dir: str) -> str:
        """Find the most recent Enrollment Details file"""
        pattern = os.path.join(download_dir, "enrollment_details*.xlsx")
        files = glob.glob(pattern)
        
        if not files:
            pattern = os.path.join(download_dir, "*enrollment*details*.xlsx")
            files = glob.glob(pattern)
        
        if not files:
            pattern = os.path.join(download_dir, "ReportWizard*.xlsx")
            files = glob.glob(pattern)
        
        if not files:
            raise FileNotFoundError(f"No Enrollment Details files found in {download_dir}")
        
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
        if self.enrollment_df is None:
            if not self.load_enrollment_details():
                return pd.DataFrame()
        
        mask = pd.Series([True] * len(self.enrollment_df))
        
        # Apply search criteria
        if 'email' in criteria:
            email_lower = criteria['email'].lower()
            mask &= (
                (self.enrollment_df['User Email'].str.lower() == email_lower) # |
                # (self.enrollment_df['Additional Email'].str.lower() == email_lower)
            )
        
        if 'first_name' in criteria:
            mask &= self.enrollment_df['Player First Name'].str.lower() == criteria['first_name'].lower()
        
        if 'last_name' in criteria:
            mask &= self.enrollment_df['Player Last Name'].str.lower() == criteria['last_name'].lower()
        
        if 'order_no' in criteria:
            mask &= self.enrollment_df['Order No'].astype(str) == str(criteria['order_no'])
        
        if 'program_name' in criteria:
            mask &= self.enrollment_df['Program Name'].str.contains(criteria['program_name'], case=False, na=False)
        
        if 'division_name' in criteria:
            mask &= self.enrollment_df['Division Name'].str.contains(criteria['division_name'], case=False, na=False)
        
        results = self.enrollment_df[mask]
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
                (By.ID, "dnn_ctr887180_OrdersBase_ctl00_SearchTextBox"),
                (By.CSS_SELECTOR, "#dnn_ctr887180_OrdersBase_ctl00_SearchTextBox"),
                (By.XPATH, '//*[@id="dnn_ctr887180_OrdersBase_ctl00_SearchTextBox"]'),
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
                (By.ID, "dnn_ctr887180_OrdersBase_ctl00_SearchLinkButton"),
                (By.CSS_SELECTOR, "#dnn_ctr887180_OrdersBase_ctl00_SearchLinkButton"),
                (By.XPATH, '//*[@id="dnn_ctr887180_OrdersBase_ctl00_SearchLinkButton"]'),
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
                (By.ID, "dnn_ctr887180_OrdersBase_ctl00_OrdersGrid_ctl00_ctl04_ManageOrderLink"),
                (By.CSS_SELECTOR, "#dnn_ctr887180_OrdersBase_ctl00_OrdersGrid_ctl00_ctl04_ManageOrderLink"),
                (By.XPATH, '//*[@id="dnn_ctr887180_OrdersBase_ctl00_OrdersGrid_ctl00_ctl04_ManageOrderLink"]')
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
    
    def find_and_click_player_cancel_button(self, player_info: Dict = None) -> bool:
        """
        Find the specific player in the order details and click their Cancel button
        
        Args:
            first_name: Player's first name
            last_name: Player's last name
            
        Returns:
            True if Cancel button was found and clicked
        """
        try:
            # Look for all player name elements (h2 tags with player names)
            player_elements = self.driver.find_elements(By.XPATH, "//h2[@class='no-margin' and @data-bind]")
            
            for player_elem in player_elements:
                player_text = player_elem.text.strip()

                first_name = player_info['player_info']['Player First Name']
                last_name = player_info['player_info']['Player Last Name']   
                
                # Check if this is our player
                if first_name in player_text and last_name in player_text:
                    logger.info(f"✓ Found player element: {player_text}")
                    
                    # Find the parent row container
                    # Go up to the tr element that contains this player
                    parent_tr = player_elem.find_element(By.XPATH, "./ancestor::tr[1]")
                    
                    # Look for the Cancel button in this row
                    cancel_selectors = [
                        # Visible Cancel button (when not synced to affinity)
                        ".//a[contains(@class, 'btn-tournament') and .//p[text()='Cancel']]",
                        # Alternative Cancel button selector
                        ".//a[contains(@href, 'cancelregistration')]",
                        # Any link with Cancel text
                        ".//a[contains(., 'Cancel')]"
                    ]
                    
                    for selector in cancel_selectors:
                        try:
                            cancel_button = parent_tr.find_element(By.XPATH, selector)
                            if cancel_button.is_displayed():
                                # Scroll to the button
                                self.driver.execute_script("arguments[0].scrollIntoView(true);", cancel_button)
                                time.sleep(0.5)
                                
                                # Log the cancel URL if available
                                cancel_url = cancel_button.get_attribute('href')
                                if cancel_url and cancel_url != '#':
                                    logger.info(f"Cancel URL: {cancel_url}")
                                
                                # Click the button
                                cancel_button.click()
                                logger.info("✓ Clicked Cancel button")
                                
                                # Wait for cancel order page to load
                                time.sleep(3)

                                # Click the Submit button on the cancel order page
                                if not self._click_cancel_submit_button():
                                    result["message"] = "Could not submit cancellation"
                                    return result
            
                                # Handle confirmation dialog if it appears
                                time.sleep(2)
            
                                result = self._handle_cancellation_confirmation(player_info)
                                
                                # Now look for and click the Submit button on the cancel order page
                                # if self._click_cancel_submit_button():
                                #     return True
                                # else:
                                #     logger.warning("Found Cancel button but could not submit cancellation")
                                #     return False

                        except:
                            continue
                    
                    # If we found the player but no visible Cancel button
                    logger.warning(f"Found player {first_name} {last_name} but Cancel button not available")
                    
                    # Check if the order is already cancelled/voided
                    row_text = parent_tr.text.lower()
                    if any(status in row_text for status in ['voided', 'cancelled', 'void']):
                        logger.info("Order appears to be already voided/cancelled")
                    
                    # Check if it's synced to affinity (which disables cancel)
                    if "This player has already been submitted to your state affiliation" in parent_tr.get_attribute('innerHTML'):
                        logger.info("Player is synced to affinity - cancellation not available")
                    
                    return False
            
            # Player not found
            logger.warning(f"Could not find player {first_name} {last_name} in order details")
            
            # List all players found for debugging
            logger.info("Players found on this order:")
            for i, elem in enumerate(player_elements):
                logger.info(f"  {i+1}. {elem.text.strip()}")
            
            return False
            
        except Exception as e:
            logger.error(f"Error finding player Cancel button: {e}")
            return False
    
    def _click_cancel_submit_button(self) -> bool:
        """
        Click the Submit button on the cancel order page
        
        Returns:
            True if Submit button was clicked successfully
        """
        try:
            logger.info("Looking for Submit button on cancel order page...")
            
            # Multiple selectors for the Submit button
            submit_selectors = [
                # Specific ID from the provided HTML
                (By.ID, "dnn_ctr887180_CancelRegistration_CancelRegitrationButton_lnkLink"),
                # Class-based selectors
                (By.XPATH, "//a[contains(@class, 'btn-tournament-orange') and contains(@class, 'btn-blue') and contains(., 'Submit')]"),
                # Text-based selectors
                (By.XPATH, "//a[.//span[contains(text(), 'Submit')]]"),
                (By.XPATH, "//a[contains(text(), 'Submit')]"),
                # Partial ID match (in case the ID changes slightly)
                (By.XPATH, "//a[contains(@id, 'CancelRegitration') and contains(@id, 'Button')]"),
                # Alternative with different spelling
                (By.XPATH, "//a[contains(@id, 'CancelRegistration') and contains(@id, 'Button')]")
            ]
            
            for by, selector in submit_selectors:
                try:
                    submit_button = self.driver.find_element(by, selector)
                    if submit_button.is_displayed():
                        # Scroll to the button
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
                        time.sleep(0.5)
                        
                        # Click the submit button
                        submit_button.click()
                        logger.info("✓ Clicked Submit button on cancel order page")
                        
                        # Wait for the action to complete
                        time.sleep(3)
                        
                        # Now handle the "player cancelled" popup
                        if self._click_back_to_order_button():
                            return True
                        else:
                            # Even if we can't find Back to Order, the cancellation might have succeeded
                            logger.warning("Could not find Back to Order button, but cancellation may have succeeded")
                            return True
                        
                except:
                    continue
            
            logger.error("Could not find Submit button on cancel order page")
            
            # Log page info for debugging
            current_url = self.driver.current_url
            logger.info(f"Current URL: {current_url}")
            
            # Check if we're on the cancel registration page
            if "cancelregistration" in current_url.lower():
                logger.info("Confirmed on cancel registration page")
                
                # Try to find any submit-like buttons
                all_buttons = self.driver.find_elements(By.TAG_NAME, "a")
                submit_like_buttons = [btn for btn in all_buttons if "submit" in btn.text.lower()]
                
                if submit_like_buttons:
                    logger.info(f"Found {len(submit_like_buttons)} submit-like buttons")
                    for btn in submit_like_buttons:
                        logger.info(f"  Button text: {btn.text}, ID: {btn.get_attribute('id')}")
                else:
                    logger.warning("No submit-like buttons found")
            
            return False
            
        except Exception as e:
            logger.error(f"Error clicking cancel submit button: {e}")
            return False
    
    def _click_back_to_order_button(self) -> bool:
        """
        Click the "Back to Order" button on the player cancelled popup
        
        Returns:
            True if button was clicked successfully
        """
        try:
            logger.info("Looking for 'Back to Order' button...")
            
            # Multiple selectors for the Back to Order button
            back_to_order_selectors = [
                # Specific ID from the provided HTML
                (By.ID, "dnn_ctr887180_CancelRegistration_BackToOrderHyperLink"),
                # Class and text based
                (By.XPATH, "//a[contains(@class, 'btn-tournament-orange') and contains(text(), 'Back to Order')]"),
                # Href based
                (By.XPATH, "//a[contains(@href, 'manageorder') and contains(text(), 'Back to Order')]"),
                # Partial ID match
                (By.XPATH, "//a[contains(@id, 'BackToOrderHyperLink')]"),
                # Text only
                (By.LINK_TEXT, "Back to Order"),
                (By.PARTIAL_LINK_TEXT, "Back to Order")
            ]
            
            # Wait a bit for the popup to appear
            time.sleep(2)
            
            for by, selector in back_to_order_selectors:
                try:
                    back_button = self.driver.find_element(by, selector)
                    if back_button.is_displayed():
                        # Log the URL it will navigate to
                        back_url = back_button.get_attribute('href')
                        if back_url:
                            logger.info(f"Back to Order URL: {back_url}")
                        
                        # Click the button
                        back_button.click()
                        logger.info("✓ Clicked 'Back to Order' button")
                        
                        # Wait for navigation
                        time.sleep(2)
                        
                        return True
                except:
                    continue
            
            # Check if we see cancellation success message even without the button
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            success_indicators = [
                "player cancelled",
                "successfully cancelled",
                "cancellation successful",
                "registration cancelled"
            ]
            
            for indicator in success_indicators:
                if indicator in page_text:
                    logger.info(f"Found success indicator: '{indicator}'")
                    logger.info("Cancellation appears successful even though Back to Order button not found")
                    return True
            
            logger.warning("Could not find 'Back to Order' button")
            return False
            
        except Exception as e:
            logger.error(f"Error clicking Back to Order button: {e}")
            return False
    
    def cancel_registration(self, order_no: str, player_info: Dict = None) -> Dict:
        """
        Cancel a registration for a specific order
        
        Args:
            order_no: Order number to cancel
            player_info: Optional player information for verification (should include Player First Name and Player Last Name)
            
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
            ## SHOULD ALREADY BE VERIFIED
            # Search for the order and click Manage
            # if not self.search_order_in_system(order_no):
            #     result["message"] = "Order not found or could not access order management"
            #     return result
            
            # Now we should be on the order details page
            # Wait for page to fully load
            time.sleep(3)
            
            # If player_info is provided and contains name, find specific player
            try:
                first_name = player_info['player_info']['Player First Name']
                last_name = player_info['player_info']['Player Last Name']

                logger.info(f"Looking for specific player: {first_name} {last_name}")

                # Use the find_and_click_player_cancel_button method
                if self.find_and_click_player_cancel_button(player_info):
                    # Handle the cancellation confirmation that follows
                    time.sleep(2)
                    result = self._handle_cancellation_confirmation(result)
                else:
                    result["message"] = f"Could not find or click Cancel button for {first_name} {last_name}"
                return result

            except (KeyError, TypeError):
                pass  # Fall back to general logic if specific player info is missing
            
            # Original logic for when no specific player is specified
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
            
            # Wait for cancel order page to load
            time.sleep(3)
            
            # Click the Submit button on the cancel order page
            if not self._click_cancel_submit_button():
                result["message"] = "Could not submit cancellation"
                return result
            
            # Handle confirmation dialog if it appears
            time.sleep(2)
            
            result = self._handle_cancellation_confirmation(result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error cancelling registration: {e}")
            result["message"] = f"Error: {str(e)}"
            return result
    
    def _handle_cancellation_confirmation(self, result: Dict) -> Dict:
        """
        Handle the cancellation confirmation dialog/page and proceed to refund
        
        Args:
            result: The result dictionary to update
            
        Returns:
            Updated result dictionary
        """
        try:
            # Since we now handle the "Back to Order" button in _click_cancel_submit_button,
            # this method just needs to verify the cancellation was successful
            
            # Check if we're back on the order page
            current_url = self.driver.current_url
            if "manageorder" in current_url.lower():
                logger.info("Successfully returned to order management page")
                
                # Now proceed to refund process
                if self._click_refund_button():
                    # We're now on the refund page, click Refund Options
                    if self._click_refund_options_button():
                        # Now we need to find the player and process the refund
                        if result.get("player_info"):
                            first_name = result["player_info"].get("Player First Name", "")
                            last_name = result["player_info"].get("Player Last Name", "")
                            if self._process_player_refund(first_name, last_name):
                                # Get the refund details from the stored last_refund_details
                                if self.last_refund_details and self.last_refund_details.get("success"):
                                    result["status"] = "success"
                                    result["message"] = "Registration cancelled and refund processed successfully"
                                    result["refund_details"] = self.last_refund_details
                                    logger.info(f"✓ Complete cancellation and refund successful")
                                    logger.info(f"  Refund amount: ${self.last_refund_details.get('refund_amount', 'N/A')}")
                                    logger.info(f"  Refund date: {self.last_refund_details.get('refund_date', 'N/A')}")
                                else:
                                    result["status"] = "partial"
                                    result["message"] = "Registration cancelled but refund status unclear"
                                return result
                            else:
                                result["status"] = "partial"
                                result["message"] = "Registration cancelled but refund processing failed"
                                return result
            
            # Check the page for cancellation confirmation
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            
            success_indicators = [
                "successfully voided",
                "successfully cancelled",
                "order has been voided",
                "order has been cancelled",
                "void successful",
                "cancellation successful",
                "player cancelled",
                "registration cancelled"
            ]
            
            # Also check for visual indicators that the player is cancelled
            cancelled_indicators = [
                "cancelled",
                "voided",
                "void"
            ]
            
            for indicator in success_indicators:
                if indicator in page_text:
                    logger.info(f"Cancellation confirmed: found '{indicator}'")
                    result["status"] = "success"
                    result["message"] = "Registration cancelled successfully"
                    return result
            
            # If we're back on the order page, check if the player shows as cancelled
            if "manageorder" in current_url.lower():
                # Look for cancelled status next to the player
                for indicator in cancelled_indicators:
                    if indicator in page_text:
                        result["status"] = "success"
                        result["message"] = "Registration appears to have been cancelled"
                        return result
            
            # If we can't confirm success but we went through the whole flow
            result["status"] = "uncertain"
            result["message"] = "Cancellation process completed but status unclear - manual verification recommended"
            
            return result
            
        except Exception as e:
            logger.error(f"Error handling cancellation confirmation: {e}")
            result["message"] = f"Error in confirmation: {str(e)}"
            return result
    
    def _click_refund_button(self) -> bool:
        """
        Click the Refund button on the order management page
        
        Returns:
            True if Refund button was clicked successfully
        """
        try:
            logger.info("Looking for Refund button on order management page...")
            
            # Multiple selectors for the Refund button
            refund_selectors = [
                # Specific ID from the provided HTML
                (By.ID, "dnn_ctr887180_ManageOrder_RefundPaymentLink"),
                # Href based
                (By.XPATH, "//a[contains(@href, 'refundpayment') and contains(text(), 'Refund')]"),
                # Class and text based
                (By.XPATH, "//a[contains(@class, 'btn-tournament-orange') and contains(text(), 'Refund')]"),
                # Text only
                (By.LINK_TEXT, "Refund"),
                (By.PARTIAL_LINK_TEXT, "Refund")
            ]
            
            # Wait a bit for the page to settle
            time.sleep(2)
            
            for by, selector in refund_selectors:
                try:
                    refund_button = self.driver.find_element(by, selector)
                    if refund_button.is_displayed():
                        # Scroll to the button
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", refund_button)
                        time.sleep(0.5)
                        
                        # Click the button
                        refund_button.click()
                        logger.info("✓ Clicked Refund button")
                        
                        # Wait for refund page to load
                        time.sleep(3)
                        
                        return True
                except:
                    continue
            
            logger.error("Could not find Refund button on order management page")
            return False
            
        except Exception as e:
            logger.error(f"Error clicking Refund button: {e}")
            return False
    
    def _click_refund_options_button(self) -> bool:
        """
        Click the Refund Options button on the refund page
        
        Returns:
            True if Refund Options button was clicked successfully
        """
        try:
            logger.info("Looking for Refund Options button...")
            
            # Multiple selectors for the Refund Options button
            refund_options_selectors = [
                # Specific ID pattern from the provided HTML
                (By.ID, "dnn_ctr887180_RefundPayments_RegistrationRefundOptionsControl_RefundVoidLinkButton_0"),
                # Partial ID match
                (By.XPATH, "//a[contains(@id, 'RefundVoidLinkButton')]"),
                # Text based
                (By.LINK_TEXT, "Refund Options"),
                (By.PARTIAL_LINK_TEXT, "Refund Options"),
                # Class and text based
                (By.XPATH, "//a[contains(@class, 'btn-tournament') and contains(text(), 'Refund Options')]")
            ]
            
            # Wait for the refund page to load
            time.sleep(2)
            
            for by, selector in refund_options_selectors:
                try:
                    refund_options_button = self.driver.find_element(by, selector)
                    if refund_options_button.is_displayed():
                        # Scroll to the button
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", refund_options_button)
                        time.sleep(0.5)
                        
                        # Click the button
                        refund_options_button.click()
                        logger.info("✓ Clicked Refund Options button")
                        
                        # Wait for refund options to appear
                        time.sleep(2)
                        
                        return True
                except:
                    continue
            
            logger.error("Could not find Refund Options button")
            return False
            
        except Exception as e:
            logger.error(f"Error clicking Refund Options button: {e}")
            return False
    
    def _process_player_refund(self, first_name: str, last_name: str) -> bool:
        """
        Process the refund for a specific player
    
        Args:
            first_name: Player's first name
            last_name: Player's last name
        
        Returns:
            True if refund was processed successfully
        """
        try:
            logger.info(f"Processing refund for {first_name} {last_name}...")
        
            # Find the player in the refund table
            # Look for player name spans - they have IDs like 'playerName_0', 'playerName_1', etc.
            player_name_elements = self.driver.find_elements(
                By.XPATH,
                "//table[contains(@class, 'sub-table')]//span[contains(@id, 'playerName')]"
            )
        
            player_found = False
            refund_input = None
        
            for player_elem in player_name_elements:
                player_text = player_elem.text.strip()
                if first_name in player_text and last_name in player_text:
                    logger.info(f"✓ Found player in refund table: {player_text}")
                    player_found = True
                
                    try:
                        # Go up to the table row - it's the nearest <tr> ancestor
                        row = player_elem.find_element(By.XPATH, "./ancestor::tr[1]")
                    
                        # Find the refund input field in the same row
                        # It has class 'CurrentRefundAmountRow' and an ID pattern like 'currentRefundAmountRow_1'
                        refund_input = row.find_element(
                            By.XPATH,
                            ".//input[contains(@class, 'CurrentRefundAmountRow')]"
                        )
                    
                        # Get the refundable amount from the same row
                        refundable_amount_elem = row.find_element(
                            By.XPATH,
                            ".//span[contains(@id, 'refundableAmount')]"
                        )
                        refundable_amount_text = refundable_amount_elem.text.strip()
                        refundable_amount = refundable_amount_text.replace('$', '').replace(',', '')
                    
                        logger.info(f"Refundable amount: {refundable_amount_text}")
                    
                        # Check if refund is available (amount > 0)
                        if float(refundable_amount) <= 0:
                            logger.warning(f"No refundable amount available for {first_name} {last_name} (amount: {refundable_amount_text})")
                        
                            # Check the hidden field for more info
                            try:
                                is_refundable = row.find_element(
                                    By.XPATH,
                                    ".//input[contains(@id, 'isRefundAvailableHidden')]"
                                ).get_attribute('value')
                                logger.info(f"Is refund available (hidden field): {is_refundable}")
                            
                                # Get the detail reason
                                detail = row.find_element(
                                    By.XPATH,
                                    ".//input[contains(@id, 'detailHidden')]"
                                ).get_attribute('value')
                                logger.info(f"Refund detail: {detail}")
                            
                                if detail == "Cancellation":
                                    logger.info("Player has already been cancelled - no refund available")
                            except:
                                pass
                        
                            return False
                    
                        # Clear the input and enter the refundable amount
                        refund_input.clear()
                        refund_input.send_keys(refundable_amount)
                        logger.info(f"✓ Entered refund amount: ${refundable_amount}")
                    
                        # Now submit the refund
                        if self._click_refund_submit_button():
                            logger.info("✓ Refund submitted successfully")
                            return True
                        else:
                            logger.error("Failed to submit refund")
                            return False
                        
                    except Exception as e:
                        logger.error(f"Error processing refund row: {e}")
                        # Log the row HTML for debugging
                        try:
                            logger.debug(f"Row HTML: {row.get_attribute('outerHTML')[:200]}...")
                        except:
                            pass
                        return False
        
            if not player_found:
                logger.error(f"Could not find player {first_name} {last_name} in refund table")
            
                # Log all players found for debugging
                logger.info("Players found in refund table:")
                for i, elem in enumerate(player_name_elements):
                    logger.info(f"  {i+1}. {elem.text.strip()}")
        
            return False
        
        except Exception as e:
            logger.error(f"Error processing player refund: {e}")
            return False
    
    def _click_refund_submit_button(self) -> bool:
        """
        Click the Submit button to complete the refund process
        
        Returns:
            True if Submit button was clicked successfully
        """
        try:
            logger.info("Looking for Submit button to complete refund...")
            
            # Multiple selectors for the Submit button
            submit_selectors = [
                # Specific ID from the provided HTML
                (By.ID, "dnn_ctr887180_RefundPayments_btnSubmitOrder_lnkLink"),
                # Partial ID match
                (By.XPATH, "//a[contains(@id, 'btnSubmitOrder')]"),
                # Class and text based
                (By.XPATH, "//a[contains(@class, 'btn-tournament-orange') and contains(text(), 'Submit')]"),
                # Text only
                (By.LINK_TEXT, "Submit"),
                (By.PARTIAL_LINK_TEXT, "Submit"),
                # Any submit button on the refund page
                (By.XPATH, "//a[contains(@href, 'javascript:WebForm_DoPostBackWithOptions') and contains(text(), 'Submit')]")
            ]
            
            # Wait a bit for any validation
            time.sleep(1)
            
            for by, selector in submit_selectors:
                try:
                    submit_button = self.driver.find_element(by, selector)
                    if submit_button.is_displayed():
                        # Scroll to the button
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
                        time.sleep(0.5)
                        
                        # Click the submit button
                        submit_button.click()
                        logger.info("✓ Clicked Submit button for refund")
                        
                        # Wait for the refund to process
                        time.sleep(3)
                        
                        # Check for success and extract details
                        refund_details = self._verify_refund_success()
                        return refund_details["success"]
                        
                except:
                    continue
            
            logger.error("Could not find Submit button for refund")
            return False
            
        except Exception as e:
            logger.error(f"Error clicking refund submit button: {e}")
            return False
    
    def _verify_refund_success(self) -> Dict[str, Any]:
        """
        Verify that the refund was processed successfully and extract refund details
        
        Returns:
            Dictionary with success status and refund details
        """
        try:
            # Wait for page to update
            time.sleep(3)
            
            # Initialize result
            refund_result = {
                "success": False,
                "refund_amount": None,
                "refund_date": None,
                "payment_method": None,
                "message": ""
            }
            
            # Check for success messages first
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            
            success_indicators = [
                "credit card completed"
            ]
            
            for indicator in success_indicators:
                if indicator in page_text:
                    logger.info(f"✓ Refund success confirmed: found '{indicator}'")
                    refund_result["success"] = True
                    break
            
            # Look for payment history table to find the refund entry
            try:
                # Find all payment rows - look for refund amounts (negative values in parentheses)
                payment_rows = self.driver.find_elements(
                    By.XPATH,
                    "//span[contains(@id, 'totalPaymentAmount') and contains(text(), '(')]"
                )
                
                if payment_rows:
                    # Get the most recent refund (should be the last one)
                    latest_refund = payment_rows[-1]
                    refund_amount_text = latest_refund.text.strip()
                    
                    # Extract the amount (remove parentheses and dollar sign)
                    refund_amount = refund_amount_text.replace('(', '').replace(')', '').replace('$', '').replace(',', '')
                    refund_result["refund_amount"] = refund_amount
                    logger.info(f"✓ Found refund amount: ${refund_amount}")
                    
                    # Get the row to find other details
                    refund_row = latest_refund.find_element(By.XPATH, "./ancestor::tr[1]")
                    
                    # Try to get refund date
                    try:
                        date_elem = refund_row.find_element(By.XPATH, ".//span[contains(@id, 'paymentDate')]")
                        refund_result["refund_date"] = date_elem.text.strip()
                        logger.info(f"Refund date: {refund_result['refund_date']}")
                    except:
                        pass
                    
                    # Try to get payment method
                    try:
                        method_elem = refund_row.find_element(By.XPATH, ".//span[contains(@id, 'paymentMethod')]")
                        refund_result["payment_method"] = method_elem.text.strip()
                        logger.info(f"Payment method: {refund_result['payment_method']}")
                    except:
                        pass
                    
                    # If we found a refund amount, consider it successful
                    if refund_result["refund_amount"]:
                        refund_result["success"] = True
                        refund_result["message"] = f"Refund of ${refund_amount} processed successfully"
                else:
                    # No refund entry found yet
                    logger.warning("No refund entry found in payment history")
                    refund_result["message"] = "Refund may still be processing"
                    
            except Exception as e:
                logger.debug(f"Error checking payment history: {e}")
            
            # Store refund details for later use (email generation)
            self.last_refund_details = refund_result
            
            # Log current page info
            current_url = self.driver.current_url
            logger.info(f"Current URL: {current_url}")
            
            if not refund_result["success"]:
                logger.warning("Could not confirm refund success")
                refund_result["message"] = "Refund status unclear - manual verification recommended"
            
            return refund_result
            
        except Exception as e:
            logger.error(f"Error verifying refund success: {e}")
            return {
                "success": False,
                "refund_amount": None,
                "refund_date": None,
                "payment_method": None,
                "message": f"Error: {str(e)}"
            }
    
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
    def create_from_automation(cls, automation_instance, enrollment_details_file: str = None):
        """
        Factory method to create RegistrationCancellationManager from SportsConnectAutomation
        
        Args:
            automation_instance: Instance of SportsConnectAutomation (already logged in)
            enrollment_details_file: Optional path to Enrollment Details file
            
        Returns:
            RegistrationCancellationManager instance
        """
        return cls(
            driver=automation_instance.driver,
            config=automation_instance.config,
            enrollment_details_file=enrollment_details_file,
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
        if self.enrollment_df is None:
            if not self.load_enrollment_details():
                print("Error: Could not load Enrollment Details data")
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
                mask = pd.to_datetime(self.enrollment_df['Order Date']) > recent_date
                search_results = self.enrollment_df[mask].head(20)
            
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