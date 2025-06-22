"""
Element Interactor for SportsConnectAutomation
Handles interactions with web elements including clicks, form filling, navigation, etc.
"""

import time
import logging
from typing import List, Dict, Any, Optional, Union, Tuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, ElementClickInterceptedException,
    ElementNotInteractableException, StaleElementReferenceException,
    WebDriverException
)
from selenium.webdriver.remote.webelement import WebElement
import random


class ElementInteractor:
    """
    Main class for interacting with web elements in sports automation
    """
    
    def __init__(self, driver: webdriver, timeout: int = 10, implicit_wait: int = 5):
        """
        Initialize the ElementInteractor
        
        Args:
            driver: Selenium WebDriver instance
            timeout: Default timeout for explicit waits
            implicit_wait: Implicit wait time for element finding
        """
        self.driver = driver
        self.timeout = timeout
        self.wait = WebDriverWait(driver, timeout)
        self.actions = ActionChains(driver)
        self.driver.implicitly_wait(implicit_wait)
        self.logger = self._setup_logger()
        
    def _setup_logger(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('ElementInteractor')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            
        return logger
    
    def try_multiple_selectors(self, selectors: List[Tuple[By, str]], action: str, 
                              timeout: int = None, **kwargs) -> bool:
        """
        Try multiple selectors until one succeeds
        
        Args:
            selectors: List of (By, selector) tuples to try
            action: Action to perform ('click', 'send_keys', 'text', etc.)
            timeout: Custom timeout for each attempt
            **kwargs: Additional arguments for the action
            
        Returns:
            True if any selector succeeded, False otherwise
        """
        for by, selector in selectors:
            try:
                element = self.wait_for_element((by, selector), "clickable", timeout or 5)
                if element:
                    if action == "click":
                        element.click()
                        self.logger.info(f"Successfully clicked using selector: {selector}")
                        return True
                    elif action == "send_keys":
                        text = kwargs.get('text', '')
                        element.send_keys(text)
                        self.logger.info(f"Successfully sent keys using selector: {selector}")
                        return True
                    elif action == "text":
                        text = element.text
                        self.logger.info(f"Successfully got text using selector: {selector}")
                        return text
                    elif action == "clear":
                        element.clear()
                        self.logger.info(f"Successfully cleared using selector: {selector}")
                        return True
                    else:
                        self.logger.warning(f"Unknown action: {action}")
                        
            except Exception as e:
                self.logger.debug(f"Selector {selector} failed: {e}")
                continue
        
        self.logger.warning(f"All selectors failed for action: {action}")
        return False
    
    def wait_for_element(self, locator: Tuple[str, str], condition: str = "clickable", timeout: int = None) -> Optional[WebElement]:
        """
        Wait for element with specified condition
        
        Args:
            locator: Tuple of (By type, selector)
            condition: Type of condition (clickable, visible, present)
            timeout: Custom timeout override
            
        Returns:
            WebElement if found, None otherwise
        """
        try:
            wait_time = timeout or self.timeout
            wait = WebDriverWait(self.driver, wait_time)
            
            conditions = {
                "clickable": EC.element_to_be_clickable(locator),
                "visible": EC.visibility_of_element_located(locator),
                "present": EC.presence_of_element_located(locator),
                "invisible": EC.invisibility_of_element_located(locator)
            }
            
            if condition in conditions:
                return wait.until(conditions[condition])
            else:
                self.logger.warning(f"Unknown condition: {condition}")
                return wait.until(EC.element_to_be_clickable(locator))
                
        except TimeoutException:
            self.logger.warning(f"Element not found with condition '{condition}': {locator}")
            return None
    
    def click_element(self, selector: str, by: By = By.CSS_SELECTOR, timeout: int = None, 
                     retry_attempts: int = 3, scroll_to: bool = True) -> bool:
        """
        Click an element with retry mechanism
        
        Args:
            selector: Element selector
            by: Selenium By type
            timeout: Custom timeout
            retry_attempts: Number of retry attempts
            scroll_to: Whether to scroll to element before clicking
            
        Returns:
            True if successful, False otherwise
        """
        for attempt in range(retry_attempts):
            try:
                element = self.wait_for_element((by, selector), "clickable", timeout)
                if not element:
                    return False
                
                if scroll_to:
                    self.scroll_to_element(element)
                    time.sleep(0.5)  # Brief pause after scrolling
                
                element.click()
                self.logger.info(f"Successfully clicked element: {selector}")
                return True
                
            except (ElementClickInterceptedException, ElementNotInteractableException) as e:
                self.logger.warning(f"Click intercepted on attempt {attempt + 1}: {str(e)}")
                if attempt < retry_attempts - 1:
                    time.sleep(1)
                    # Try clicking with JavaScript as fallback
                    try:
                        element = self.driver.find_element(by, selector)
                        self.driver.execute_script("arguments[0].click();", element)
                        self.logger.info(f"Successfully clicked with JavaScript: {selector}")
                        return True
                    except Exception:
                        continue
                        
            except StaleElementReferenceException:
                self.logger.warning(f"Stale element reference on attempt {attempt + 1}")
                if attempt < retry_attempts - 1:
                    time.sleep(1)
                    continue
                    
            except Exception as e:
                self.logger.error(f"Error clicking element on attempt {attempt + 1}: {str(e)}")
                if attempt < retry_attempts - 1:
                    time.sleep(1)
                    continue
        
        return False
    
    def double_click_element(self, selector: str, by: By = By.CSS_SELECTOR) -> bool:
        """
        Double click an element
        
        Args:
            selector: Element selector
            by: Selenium By type
            
        Returns:
            True if successful, False otherwise
        """
        try:
            element = self.wait_for_element((by, selector), "clickable")
            if element:
                self.actions.double_click(element).perform()
                self.logger.info(f"Successfully double-clicked element: {selector}")
                return True
        except Exception as e:
            self.logger.error(f"Error double-clicking element: {str(e)}")
        return False
    
    def right_click_element(self, selector: str, by: By = By.CSS_SELECTOR) -> bool:
        """
        Right click an element
        
        Args:
            selector: Element selector
            by: Selenium By type
            
        Returns:
            True if successful, False otherwise
        """
        try:
            element = self.wait_for_element((by, selector), "clickable")
            if element:
                self.actions.context_click(element).perform()
                self.logger.info(f"Successfully right-clicked element: {selector}")
                return True
        except Exception as e:
            self.logger.error(f"Error right-clicking element: {str(e)}")
        return False
    
    def hover_over_element(self, selector: str, by: By = By.CSS_SELECTOR, duration: float = 1.0) -> bool:
        """
        Hover over an element
        
        Args:
            selector: Element selector
            by: Selenium By type
            duration: How long to hover in seconds
            
        Returns:
            True if successful, False otherwise
        """
        try:
            element = self.wait_for_element((by, selector), "visible")
            if element:
                self.actions.move_to_element(element).perform()
                time.sleep(duration)
                self.logger.info(f"Successfully hovered over element: {selector}")
                return True
        except Exception as e:
            self.logger.error(f"Error hovering over element: {str(e)}")
        return False
    
    def fill_input_field(self, selector: str, text: str, by: By = By.CSS_SELECTOR, 
                        clear_first: bool = True, human_typing: bool = False) -> bool:
        """
        Fill an input field with text
        
        Args:
            selector: Element selector
            text: Text to input
            by: Selenium By type
            clear_first: Whether to clear field before typing
            human_typing: Whether to simulate human-like typing speed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            element = self.wait_for_element((by, selector), "clickable")
            if not element:
                return False
            
            self.scroll_to_element(element)
            element.click()  # Focus on the element
            
            if clear_first:
                element.clear()
                # Alternative clearing method for stubborn fields
                element.send_keys(Keys.CONTROL + "a")
                element.send_keys(Keys.DELETE)
            
            if human_typing:
                for char in text:
                    element.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.15))  # Random typing delay
            else:
                element.send_keys(text)
            
            self.logger.info(f"Successfully filled input field: {selector}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error filling input field: {str(e)}")
            return False
    
    def select_dropdown_option(self, selector: str, option_text: str = None, 
                              option_value: str = None, option_index: int = None,
                              by: By = By.CSS_SELECTOR) -> bool:
        """
        Select option from dropdown
        
        Args:
            selector: Dropdown selector
            option_text: Text of option to select
            option_value: Value of option to select
            option_index: Index of option to select
            by: Selenium By type
            
        Returns:
            True if successful, False otherwise
        """
        try:
            dropdown_element = self.wait_for_element((by, selector), "clickable")
            if not dropdown_element:
                return False
            
            select = Select(dropdown_element)
            
            if option_text:
                select.select_by_visible_text(option_text)
            elif option_value:
                select.select_by_value(option_value)
            elif option_index is not None:
                select.select_by_index(option_index)
            else:
                self.logger.error("No selection criteria provided for dropdown")
                return False
            
            self.logger.info(f"Successfully selected dropdown option: {selector}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error selecting dropdown option: {str(e)}")
            return False
    
    def check_checkbox(self, selector: str, check: bool = True, by: By = By.CSS_SELECTOR) -> bool:
        """
        Check or uncheck a checkbox
        
        Args:
            selector: Checkbox selector
            check: True to check, False to uncheck
            by: Selenium By type
            
        Returns:
            True if successful, False otherwise
        """
        try:
            element = self.wait_for_element((by, selector), "clickable")
            if not element:
                return False
            
            is_checked = element.is_selected()
            
            if (check and not is_checked) or (not check and is_checked):
                element.click()
                self.logger.info(f"Successfully {'checked' if check else 'unchecked'} checkbox: {selector}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error with checkbox: {str(e)}")
            return False
    
    def submit_form(self, form_selector: str, by: By = By.CSS_SELECTOR) -> bool:
        """
        Submit a form
        
        Args:
            form_selector: Form selector
            by: Selenium By type
            
        Returns:
            True if successful, False otherwise
        """
        try:
            form_element = self.wait_for_element((by, form_selector), "present")
            if form_element:
                form_element.submit()
                self.logger.info(f"Successfully submitted form: {form_selector}")
                return True
        except Exception as e:
            self.logger.error(f"Error submitting form: {str(e)}")
        return False
    
    def scroll_to_element(self, element: WebElement, alignment: str = "center") -> bool:
        """
        Scroll to a specific element
        
        Args:
            element: WebElement to scroll to
            alignment: Scroll alignment (top, center, bottom)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            alignment_options = {
                "top": "true",
                "center": "{block: 'center'}",
                "bottom": "false"
            }
            
            scroll_script = f"arguments[0].scrollIntoView({alignment_options.get(alignment, 'true')});"
            self.driver.execute_script(scroll_script, element)
            time.sleep(0.5)  # Brief pause after scrolling
            return True
            
        except Exception as e:
            self.logger.error(f"Error scrolling to element: {str(e)}")
            return False
    
    def scroll_page(self, direction: str = "down", pixels: int = None, pages: int = 1) -> bool:
        """
        Scroll the page
        
        Args:
            direction: Direction to scroll (up, down, left, right)
            pixels: Number of pixels to scroll (overrides pages)
            pages: Number of page heights to scroll
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if pixels:
                scroll_commands = {
                    "down": f"window.scrollBy(0, {pixels});",
                    "up": f"window.scrollBy(0, -{pixels});",
                    "left": f"window.scrollBy(-{pixels}, 0);",
                    "right": f"window.scrollBy({pixels}, 0);"
                }
            else:
                viewport_height = self.driver.execute_script("return window.innerHeight;")
                scroll_distance = viewport_height * pages
                
                scroll_commands = {
                    "down": f"window.scrollBy(0, {scroll_distance});",
                    "up": f"window.scrollBy(0, -{scroll_distance});",
                    "left": f"window.scrollBy(-{scroll_distance}, 0);",
                    "right": f"window.scrollBy({scroll_distance}, 0);"
                }
            
            if direction in scroll_commands:
                self.driver.execute_script(scroll_commands[direction])
                time.sleep(1)  # Wait for scroll animation
                return True
            else:
                self.logger.error(f"Invalid scroll direction: {direction}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error scrolling page: {str(e)}")
            return False
    
    def scroll_to_bottom(self, max_scrolls: int = 10, scroll_pause: float = 2.0) -> bool:
        """
        Scroll to the bottom of the page (useful for infinite scroll)
        
        Args:
            max_scrolls: Maximum number of scroll attempts
            scroll_pause: Pause between scrolls
            
        Returns:
            True if reached bottom, False otherwise
        """
        try:
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            
            for i in range(max_scrolls):
                # Scroll down to bottom
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(scroll_pause)
                
                # Calculate new scroll height
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                
                if new_height == last_height:
                    self.logger.info(f"Reached bottom of page after {i + 1} scrolls")
                    return True
                    
                last_height = new_height
            
            self.logger.warning(f"Max scrolls ({max_scrolls}) reached without finding bottom")
            return False
            
        except Exception as e:
            self.logger.error(f"Error scrolling to bottom: {str(e)}")
            return False
    
    def wait_for_page_load(self, timeout: int = None) -> bool:
        """
        Wait for page to fully load
        
        Args:
            timeout: Custom timeout
            
        Returns:
            True if page loaded, False if timeout
        """
        try:
            wait_time = timeout or self.timeout
            WebDriverWait(self.driver, wait_time).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            return True
        except TimeoutException:
            self.logger.warning("Page load timeout reached")
            return False
    
    def switch_to_frame(self, frame_selector: str, by: By = By.CSS_SELECTOR) -> bool:
        """
        Switch to iframe/frame
        
        Args:
            frame_selector: Frame selector
            by: Selenium By type
            
        Returns:
            True if successful, False otherwise
        """
        try:
            frame_element = self.wait_for_element((by, frame_selector), "present")
            if frame_element:
                self.driver.switch_to.frame(frame_element)
                self.logger.info(f"Successfully switched to frame: {frame_selector}")
                return True
        except Exception as e:
            self.logger.error(f"Error switching to frame: {str(e)}")
        return False
    
    def switch_to_default_content(self) -> bool:
        """
        Switch back to main content from frame
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.driver.switch_to.default_content()
            self.logger.info("Successfully switched to default content")
            return True
        except Exception as e:
            self.logger.error(f"Error switching to default content: {str(e)}")
            return False
    
    def handle_alert(self, action: str = "accept", text_to_send: str = None) -> Optional[str]:
        """
        Handle JavaScript alerts
        
        Args:
            action: Action to take (accept, dismiss)
            text_to_send: Text to send to prompt alerts
            
        Returns:
            Alert text if available, None otherwise
        """
        try:
            alert = WebDriverWait(self.driver, 5).until(EC.alert_is_present())
            alert_text = alert.text
            
            if text_to_send:
                alert.send_keys(text_to_send)
            
            if action == "accept":
                alert.accept()
            elif action == "dismiss":
                alert.dismiss()
            
            self.logger.info(f"Successfully handled alert with action: {action}")
            return alert_text
            
        except TimeoutException:
            self.logger.info("No alert present")
            return None
        except Exception as e:
            self.logger.error(f"Error handling alert: {str(e)}")
            return None
    
    def open_new_tab(self, url: str = None) -> bool:
        """
        Open a new tab
        
        Args:
            url: Optional URL to navigate to in new tab
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.driver.execute_script("window.open('');")
            tabs = self.driver.window_handles
            self.driver.switch_to.window(tabs[-1])
            
            if url:
                self.driver.get(url)
            
            self.logger.info("Successfully opened new tab")
            return True
            
        except Exception as e:
            self.logger.error(f"Error opening new tab: {str(e)}")
            return False
    
    def close_current_tab(self) -> bool:
        """
        Close current tab and switch to previous
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if len(self.driver.window_handles) > 1:
                self.driver.close()
                self.driver.switch_to.window(self.driver.window_handles[-1])
                self.logger.info("Successfully closed current tab")
                return True
            else:
                self.logger.warning("Cannot close last remaining tab")
                return False
                
        except Exception as e:
            self.logger.error(f"Error closing tab: {str(e)}")
            return False
    
    def take_screenshot(self, filename: str = None, element_selector: str = None) -> bool:
        """
        Take screenshot of page or specific element
        
        Args:
            filename: Screenshot filename (auto-generated if None)
            element_selector: Selector for specific element screenshot
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not filename:
                timestamp = int(time.time())
                filename = f"screenshot_{timestamp}.png"
            
            if element_selector:
                element = self.driver.find_element(By.CSS_SELECTOR, element_selector)
                element.screenshot(filename)
            else:
                self.driver.save_screenshot(filename)
            
            self.logger.info(f"Screenshot saved: {filename}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error taking screenshot: {str(e)}")
            return False
    
    def execute_javascript(self, script: str, *args) -> Any:
        """
        Execute JavaScript code
        
        Args:
            script: JavaScript code to execute
            *args: Arguments to pass to script
            
        Returns:
            Script return value
        """
        try:
            result = self.driver.execute_script(script, *args)
            self.logger.info("Successfully executed JavaScript")
            return result
        except Exception as e:
            self.logger.error(f"Error executing JavaScript: {str(e)}")
            return None
    
    def wait_for_text_in_element(self, selector: str, expected_text: str, 
                                timeout: int = None, by: By = By.CSS_SELECTOR) -> bool:
        """
        Wait for specific text to appear in element
        
        Args:
            selector: Element selector
            expected_text: Text to wait for
            timeout: Custom timeout
            by: Selenium By type
            
        Returns:
            True if text found, False if timeout
        """
        try:
            wait_time = timeout or self.timeout
            WebDriverWait(self.driver, wait_time).until(
                EC.text_to_be_present_in_element((by, selector), expected_text)
            )
            return True
        except TimeoutException:
            self.logger.warning(f"Text '{expected_text}' not found in element: {selector}")
            return False
    
    def drag_and_drop(self, source_selector: str, target_selector: str, 
                     by: By = By.CSS_SELECTOR) -> bool:
        """
        Perform drag and drop action
        
        Args:
            source_selector: Source element selector
            target_selector: Target element selector
            by: Selenium By type
            
        Returns:
            True if successful, False otherwise
        """
        try:
            source = self.wait_for_element((by, source_selector), "visible")
            target = self.wait_for_element((by, target_selector), "visible")
            
            if source and target:
                self.actions.drag_and_drop(source, target).perform()
                self.logger.info(f"Successfully performed drag and drop from {source_selector} to {target_selector}")
                return True
                
        except Exception as e:
            self.logger.error(f"Error performing drag and drop: {str(e)}")
        return False
    
    def simulate_human_behavior(self, min_delay: float = 0.5, max_delay: float = 2.0):
        """
        Add random delay to simulate human behavior
        
        Args:
            min_delay: Minimum delay in seconds
            max_delay: Maximum delay in seconds
        """
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)
        self.logger.debug(f"Simulated human delay: {delay:.2f}s")
    
    def close(self):
        """Clean up resources"""
        if self.driver:
            self.driver.quit()


# Utility functions for common sports automation tasks
class SportsAutomationHelpers:
    """
    Helper methods for common sports automation scenarios
    """
    
    def __init__(self, interactor: ElementInteractor):
        self.interactor = interactor
        self.logger = interactor.logger
    
    def login_to_sports_site(self, username_selector: str, password_selector: str,
                           login_button_selector: str, username: str, password: str) -> bool:
        """
        Perform login to sports website
        
        Args:
            username_selector: Username field selector
            password_selector: Password field selector
            login_button_selector: Login button selector
            username: Username to enter
            password: Password to enter
            
        Returns:
            True if login successful, False otherwise
        """
        try:
            # Fill username
            if not self.interactor.fill_input_field(username_selector, username):
                return False
            
            # Fill password
            if not self.interactor.fill_input_field(password_selector, password):
                return False
            
            # Click login button
            if not self.interactor.click_element(login_button_selector):
                return False
            
            # Wait for page to load after login
            self.interactor.wait_for_page_load()
            
            self.logger.info("Login process completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Error during login: {str(e)}")
            return False
    
    def navigate_to_team_page(self, team_name: str, search_selector: str = None) -> bool:
        """
        Navigate to specific team page
        
        Args:
            team_name: Name of team to search for
            search_selector: Search field selector
            
        Returns:
            True if navigation successful, False otherwise
        """
        try:
            if search_selector:
                # Use search functionality
                if self.interactor.fill_input_field(search_selector, team_name):
                    # Press Enter to search
                    element = self.interactor.driver.find_element(By.CSS_SELECTOR, search_selector)
                    element.send_keys(Keys.RETURN)
                    time.sleep(2)
                    
                    # Click on first search result
                    first_result_selector = ".search-result:first-child a, .team-link:first-child"
                    return self.interactor.click_element(first_result_selector)
            
            # Alternative: Look for team link directly
            team_link_selector = f"a[href*='{team_name.lower().replace(' ', '-')}']"
            return self.interactor.click_element(team_link_selector)
            
        except Exception as e:
            self.logger.error(f"Error navigating to team page: {str(e)}")
            return False
    
    def set_date_range(self, start_date_selector: str, end_date_selector: str,
                      start_date: str, end_date: str) -> bool:
        """
        Set date range for sports data filtering
        
        Args:
            start_date_selector: Start date field selector
            end_date_selector: End date field selector
            start_date: Start date string
            end_date: End date string
            
        Returns:
            True if successful, False otherwise
        """
        try:
            success = True
            success &= self.interactor.fill_input_field(start_date_selector, start_date, clear_first=True)
            success &= self.interactor.fill_input_field(end_date_selector, end_date, clear_first=True)
            
            if success:
                self.logger.info(f"Set date range: {start_date} to {end_date}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error setting date range: {str(e)}")
            return False