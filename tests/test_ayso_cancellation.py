"""
Test script for AYSO58 order cancellation workflow using Sports Connect login
Tests the navigation, search, and cancellation process with shared authentication
Updated to use enrollment details data instead of open orders
"""
import sys
import os
import time
import logging
from pathlib import Path

# Find the src directory and add it to path
current_dir = Path(__file__).parent
src_dir = current_dir.parent / 'src'

# If we're already in a subdirectory of src, go up until we find src
if 'src' in current_dir.parts:
    while current_dir.name != 'src' and current_dir.parent != current_dir:
        current_dir = current_dir.parent
    src_dir = current_dir

# Add src to Python path
sys.path.insert(0, str(src_dir))

# Now we can import from src
from core.config import ConfigManager
from automation.sports_connect import SportsConnectAutomation
from automation.registration_cancellation_manager import RegistrationCancellationManager
from utilities.logger import setup_logging

# Set up logging
logger = logging.getLogger(__name__)

class AYSO58OrderTester:
    """Test AYSO58 order management functionality using Sports Connect authentication"""
    
    def __init__(self, config_file: str = 'config/config.json'):
        """Initialize the tester with Sports Connect automation"""
        self.config = ConfigManager(config_file)
        self.config.load_config()
        self.automation = None
        self.cancellation_manager = None
        
    def setup_automation(self):
        """Set up Sports Connect automation and login"""
        logger.info("Setting up Sports Connect automation...")
        
        try:
            # Create automation instance
            self.automation = SportsConnectAutomation(self.config)
            self.automation.initialize()
            
            # Login to Sports Connect (shared session)
            logger.info("Logging into Sports Connect...")
            if not self.automation.login():
                logger.error("Failed to login to Sports Connect")
                return False
            
            logger.info("✓ Successfully logged into Sports Connect")
            
            # Create cancellation manager using the authenticated session
            self.cancellation_manager = RegistrationCancellationManager(
                driver=self.automation.driver,
                config=self.automation.config,
                enrollment_details_file=None,
                already_logged_in=True
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup automation: {e}")
            return False
    
    def test_navigation(self) -> bool:
        """Test navigation to AYSO58 order management page"""
        logger.info("\nTesting navigation to AYSO58 order management...")
        
        try:
            # Use the cancellation manager's navigation method
            if self.cancellation_manager.navigate_to_order_management():
                logger.info("✓ Successfully navigated to order management page")
                
                # Log current URL and title
                current_url = self.automation.driver.current_url
                title = self.automation.driver.title
                logger.info(f"Current URL: {current_url}")
                logger.info(f"Page title: {title}")
                
                return True
            else:
                logger.error("✗ Failed to navigate to order management page")
                return False
                
        except Exception as e:
            logger.error(f"Navigation test failed: {e}")
            return False
    
    def test_page_elements(self):
        """Test and identify page elements"""
        logger.info("\nTesting page elements...")
        driver = self.automation.driver
        
        try:
            # Look for search box - updated with actual selectors
            search_selectors = [
                ("ID", "dnn_ctr887180_OrdersBase_ctl00_SearchTextBox"),
                ("CSS", "input.order-search-box"),
                ("CSS", "input.searchTextBox"),
                ("CSS", "input[id*='SearchTextBox']"),
                ("CSS", "input[name*='SearchTextBox']"),
                ("XPATH", "//input[contains(@id, 'SearchTextBox')]"),
                ("XPATH", "//input[contains(@class, 'order-search-box')]")
            ]
            
            search_found = False
            for selector_type, selector in search_selectors:
                try:
                    from selenium.webdriver.common.by import By
                    if selector_type == "ID":
                        element = driver.find_element(By.ID, selector)
                    elif selector_type == "CSS":
                        element = driver.find_element(By.CSS_SELECTOR, selector)
                    else:
                        element = driver.find_element(By.XPATH, selector)
                    
                    logger.info(f"✓ Found search box with {selector_type}: {selector}")
                    logger.info(f"  Element ID: {element.get_attribute('id')}")
                    logger.info(f"  Element Name: {element.get_attribute('name')}")
                    logger.info(f"  Element Type: {element.get_attribute('type')}")
                    logger.info(f"  Element Classes: {element.get_attribute('class')}")
                    search_found = True
                    break
                except:
                    continue
            
            if not search_found:
                logger.warning("✗ Search box not found")
                # List all input elements for debugging
                logger.info("\nListing all input elements to help identify search box:")
                inputs = driver.find_elements(By.TAG_NAME, "input")
                for i, inp in enumerate(inputs[:15]):  # First 15 inputs
                    inp_id = inp.get_attribute('id')
                    inp_name = inp.get_attribute('name')
                    inp_class = inp.get_attribute('class')
                    inp_type = inp.get_attribute('type')
                    if 'search' in str(inp_id).lower() or 'search' in str(inp_name).lower() or 'search' in str(inp_class).lower():
                        logger.info(f"  Input {i}: id='{inp_id}', name='{inp_name}', class='{inp_class}', type='{inp_type}'")
            
            # Look for search button - update patterns based on actual HTML
            button_selectors = [
                ("ID", "dnn_ctr887180_OrdersBase_ctl00_SearchLinkButton"),
                ("CSS", "a.searchButton"),
                ("CSS", "a.btn-search"),
                ("CSS", "a[id*='SearchLinkButton']"),
                ("XPATH", "//a[contains(@id, 'SearchLinkButton')]"),
                ("XPATH", "//a[contains(@class, 'searchButton')]"),
                ("XPATH", "//a[text()='Search']"),
                ("CSS", "a.searchButton.btn-default")
            ]
            
            button_found = False
            for selector_type, selector in button_selectors:
                try:
                    if selector_type == "ID":
                        element = driver.find_element(By.ID, selector)
                    elif selector_type == "CSS":
                        element = driver.find_element(By.CSS_SELECTOR, selector)
                    else:
                        element = driver.find_element(By.XPATH, selector)
                    
                    logger.info(f"✓ Found search button with {selector_type}: {selector}")
                    logger.info(f"  Element Tag: {element.tag_name}")
                    logger.info(f"  Element Text: {element.text or element.get_attribute('value')}")
                    logger.info(f"  Element ID: {element.get_attribute('id')}")
                    button_found = True
                    break
                except:
                    continue
            
            if not button_found:
                logger.warning("✗ Search button not found")
                # List all links and buttons for debugging
                logger.info("\nListing potential search buttons:")
                links = driver.find_elements(By.TAG_NAME, "a")
                for link in links:
                    link_text = link.text
                    link_id = link.get_attribute('id')
                    if 'search' in str(link_text).lower() or 'search' in str(link_id).lower():
                        logger.info(f"  Link: text='{link_text}', id='{link_id}'")
                
                buttons = driver.find_elements(By.TAG_NAME, "input")
                for btn in buttons:
                    if btn.get_attribute('type') in ['button', 'submit']:
                        btn_value = btn.get_attribute('value')
                        btn_id = btn.get_attribute('id')
                        if 'search' in str(btn_value).lower() or 'search' in str(btn_id).lower():
                            logger.info(f"  Button: value='{btn_value}', id='{btn_id}'")
                
        except Exception as e:
            logger.error(f"Element test failed: {e}")
    
    def test_search_functionality(self, order_number: str = "123456789"):
        """Test the search functionality using cancellation manager"""
        logger.info(f"\nTesting search for order: {order_number}")
        
        try:
            # Use the cancellation manager's search method
            result = self.cancellation_manager.search_order_in_system(order_number)
            
            if result:
                logger.info(f"✓ Order search completed successfully")
                logger.info("  Manage button clicked - now on order details page")
            else:
                logger.info(f"ℹ Order {order_number} not found (expected for test order)")
                
                # Check page for any results
                page_text = self.automation.driver.find_element(By.TAG_NAME, "body").text
                if "no orders found" in page_text.lower():
                    logger.info("  Page shows 'no orders found' message")
                    
        except Exception as e:
            logger.error(f"Search test failed: {e}")
    
    def test_enrollment_details_search(self):
        """Test searching using Enrollment Details data"""
        logger.info("\nTesting Enrollment Details data search...")
        
        try:
            # Load Enrollment Details data
            if self.cancellation_manager.load_enrollment_details():
                logger.info("✓ Loaded Enrollment Details data")
                
                # Search for a recent order
                recent_orders = self.cancellation_manager.search_registrations(
                    program_name="2025 Fall Core"
                )
                
                if not recent_orders.empty:
                    logger.info(f"✓ Found {len(recent_orders)} orders for 2025 Fall Core")
                    
                    # Display first few orders
                    logger.info("\nFirst 5 orders:")
                    for idx, row in recent_orders.head(5).iterrows():
                        logger.info(f"  {row['Order No']}: {row['Player First Name']} {row['Player Last Name']} - {row['Division Name']}")
                else:
                    logger.info("ℹ No orders found for 2025 Fall Core")
                    
            else:
                logger.error("✗ Failed to load Enrollment Details data")
                
        except Exception as e:
            logger.error(f"Enrollment Details search test failed: {e}")
    
    def test_email_based_cancellation_workflow(self, email: str):
        """Test cancellation workflow by searching for email and allowing player selection"""
        logger.info(f"\nSearching for registrations with email: {email}")
        
        try:
            # Search for all registrations with this email
            registrations = self.cancellation_manager.search_registrations(email=email)
            
            if registrations.empty:
                logger.info(f"ℹ No registrations found for email: {email}")
                return
            
            # Display all found registrations
            logger.info(f"\n✓ Found {len(registrations)} registration(s) for {email}:")
            print("\nRegistrations found:")
            print("-" * 60)
            
            for idx, (_, row) in enumerate(registrations.iterrows()):
                print(f"\n{idx + 1}. {row['Player First Name']} {row['Player Last Name']}")
                print(f"   Division: {row['Division Name']}")
                print(f"   Program: {row['Program Name']}")
                print(f"   Order #: {row['Order No']}")
                print(f"   Amount: ${row['Order Amount']}")
                # print(f"   Date: {row['Order Date']}")
            
            # Ask user to select a player
            print("\n" + "-" * 60)
            selection = input("\nSelect a player number to test cancellation workflow (or 0 to cancel): ").strip()
            
            try:
                selection_idx = int(selection) - 1
                if selection == '0':
                    logger.info("Cancellation workflow test cancelled by user")
                    return
                
                if 0 <= selection_idx < len(registrations):
                    selected_row = registrations.iloc[selection_idx]
                    order_number = str(selected_row['Order No'])
                    player_first_name = selected_row['Player First Name']
                    player_last_name = selected_row['Player Last Name']
                    player_name = f"{player_first_name} {player_last_name}"
                    
                    logger.info(f"\n✓ Selected: {player_name} (Order: {order_number})")
                    
                    # Now run the cancellation workflow test with the selected order and player names
                    self.test_cancellation_workflow(order_number, player_first_name, player_last_name)
                else:
                    logger.error("Invalid selection - number out of range")
                    
            except ValueError:
                logger.error("Invalid selection - please enter a number")
                
        except Exception as e:
            logger.error(f"Email-based workflow test failed: {e}")
    
    def test_cancellation_workflow(self, order_number: str, player_first_name: str = None, player_last_name: str = None):
        """Test the cancellation workflow (without actually cancelling)"""
        logger.info(f"\nTesting cancellation workflow for order: {order_number}")
        if player_first_name and player_last_name:
            logger.info(f"Looking for specific player: {player_first_name} {player_last_name}")
        
        try:
            # First search in Enrollment Details data
            order_data = self.cancellation_manager.search_registrations(order_no=order_number,first_name=player_first_name,last_name=player_last_name)
            
            if not order_data.empty:
                logger.info("✓ Order found in Enrollment Details data:")
                row = order_data.iloc[0]
                
                # If no specific player provided, use the first one
                if not player_first_name:
                    player_first_name = row['Player First Name']
                    player_last_name = row['Player Last Name']
                
                logger.info(f"  Player: {player_first_name} {player_last_name}")
                logger.info(f"  Division: {row['Division Name']}")
                logger.info(f"  Amount: ${row['Order Amount']}")
                
                # Navigate to order management
                if self.cancellation_manager.navigate_to_order_management():
                    logger.info("✓ Navigated to order management")
                    
                    # Search for the order
                    if self.cancellation_manager.search_order_in_system(order_number):
                        logger.info("✓ Order found in system and Manage clicked")
                        logger.info("Now looking for the specific player on the order details page...")
                        
                        # Wait for page to load
                        time.sleep(3)

                        result = self.cancellation_manager.cancel_registration(
                            order_number,
                            {
                                'player_info': {
                                    'Player First Name': player_first_name,
                                    'Player Last Name': player_last_name
                                }
                            }
                        )

                        # Check if it worked
                        if result['status'] == 'success':
                            print("✓ Cancellation successful!")
    
                            # Access refund details if available
                            if 'refund_details' in result:
                                refund = result['refund_details']
                                print(f"  Refund amount: ${refund.get('refund_amount', 'N/A')}")
                                print(f"  Refund date: {refund.get('refund_date', 'N/A')}")
                                print(f"  Payment method: {refund.get('payment_method', 'N/A')}")
        
                        elif result['status'] == 'partial':
                            print("⚠ Partial success - cancellation done but refund may have failed")
                            print(f"  Details: {result['message']}")
    
                        elif result['status'] == 'uncertain':
                            print("? Status uncertain - manual verification recommended")
                            print(f"  Details: {result['message']}")
    
                        else:  # status == 'failed'
                            print("✗ Cancellation failed")
                            print(f"  Error: {result['message']}")
                        
                        # Find the specific player and their Cancel button
                        # if self.cancellation_manager.find_and_click_player_cancel_button(player_first_name, player_last_name):
                        #     logger.info("✓ Found player and clicked Cancel button")
                        #     logger.info("ℹ In production mode, this would proceed with cancellation")
                        #     logger.info("ℹ Test mode - stopping here to avoid actual cancellation")
                        # else:
                        #     logger.warning(f"Could not find Cancel button for {player_first_name} {player_last_name}")
                    else:
                        logger.info("ℹ Order not found in system")
                        
            else:
                logger.info(f"ℹ Order {order_number} not found in Enrollment Details data")
                
        except Exception as e:
            logger.error(f"Cancellation workflow test failed: {e}")
    
    def run_interactive_tests(self):
        """Run interactive tests"""
        print("\n" + "="*60)
        print("AYSO58 Order Management Test (Using Sports Connect Login)")
        print("="*60)
        
        while True:
            print("\nTest Options:")
            print("1. Test navigation to order management")
            print("2. Test page elements")
            print("3. Search for specific order")
            print("4. Search in Enrollment Details data")
            print("5. Test full cancellation workflow (search by email)")
            print("6. Take screenshot")
            print("0. Exit")
            
            choice = input("\nEnter choice (0-6): ").strip()
            
            if choice == '0':
                break
            elif choice == '1':
                self.test_navigation()
            elif choice == '2':
                if "tabid=813733" in self.automation.driver.current_url:
                    self.test_page_elements()
                else:
                    logger.warning("Navigate to order management page first (option 1)")
            elif choice == '3':
                order_no = input("Enter order number to search: ").strip()
                if order_no:
                    self.test_search_functionality(order_no)
            elif choice == '4':
                self.test_enrollment_details_search()
            elif choice == '5':
                email = input("Enter email address: ").strip()
                if email:
                    self.test_email_based_cancellation_workflow(email)
            elif choice == '6':
                screenshot_name = f"ayso_test_{int(time.time())}.png"
                self.automation.driver.save_screenshot(screenshot_name)
                logger.info(f"Screenshot saved: {screenshot_name}")
            else:
                print("Invalid choice")
    
    def cleanup(self):
        """Clean up resources"""
        if self.automation:
            self.automation.cleanup()
            logger.info("Automation cleaned up")


def main():
    """Run the tests"""
    # Set up logging
    setup_logging(log_level='INFO')
    
    tester = None
    
    try:
        # Create tester
        tester = AYSO58OrderTester()
        
        # Setup automation and login
        if not tester.setup_automation():
            logger.error("Failed to setup automation")
            return 1
        
        # Run tests
        print("\nRunning automated tests...")
        
        # Test navigation
        if tester.test_navigation():
            # Test page elements
            tester.test_page_elements()
            
            # Test Enrollment Details search
            tester.test_enrollment_details_search()
            
            # Interactive mode
            tester.run_interactive_tests()
        else:
            logger.error("Navigation test failed - cannot continue")
            
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        if tester:
            tester.cleanup()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())