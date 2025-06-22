"""
WebDriver management for Sports Connect Automation
"""
import logging
import os
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from .exceptions import WebDriverError

logger = logging.getLogger(__name__)


class WebDriverManager:
    """Manages Chrome WebDriver lifecycle and configuration"""
    
    def __init__(self, download_dir: str = None, headless: bool = False, 
                 window_size: tuple = (1920, 1080)):
        """
        Initialize WebDriver Manager
        
        Args:
            download_dir: Directory for downloads
            headless: Run in headless mode
            window_size: Browser window size (width, height)
        """
        self.download_dir = download_dir or str(Path("data/downloads").absolute())
        self.headless = headless
        self.window_size = window_size
        self.driver: Optional[webdriver.Chrome] = None
        
        # Ensure download directory exists
        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
    
    def _get_manual_chromedriver_path(self) -> Optional[str]:
        """Get manual ChromeDriver path as fallback"""
        common_paths = [
            r"C:\Program Files\Google\Chrome\Application\chromedriver.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chromedriver.exe",
            r"C:\chromedriver\chromedriver.exe",
            "./chromedriver.exe",
            "chromedriver.exe"
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                logger.info(f"Found ChromeDriver at: {path}")
                return path
        
        return None
    
    def clear_driver_cache(self) -> None:
        """Clear webdriver-manager cache to force re-download"""
        import shutil
        cache_dir = Path.home() / '.wdm'
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            logger.info("Cleared webdriver-manager cache")
    
    def create_driver(self) -> webdriver.Chrome:
        """Create and configure Chrome WebDriver"""
        try:
            options = self._get_chrome_options()
            
            # Force 64-bit ChromeDriver download
            os.environ['WDM_ARCH'] = '64'
            
            # Use webdriver-manager to automatically download correct driver
            try:
                service = Service(ChromeDriverManager().install())
            except Exception as e:
                logger.warning(f"ChromeDriverManager failed: {e}, trying manual path")
                # Fallback to manual driver path if webdriver-manager fails
                driver_path = self._get_manual_chromedriver_path()
                if driver_path:
                    service = Service(driver_path)
                else:
                    raise WebDriverError("Could not find ChromeDriver")
            
            self.driver = webdriver.Chrome(service=service, options=options)
            
            if not self.headless:
                self.driver.maximize_window()
            
            logger.info("WebDriver created successfully")
            return self.driver
            
        except Exception as e:
            logger.error(f"Failed to create WebDriver: {e}")
            raise WebDriverError(f"Failed to create WebDriver: {e}")
    
    def _get_chrome_options(self) -> Options:
        """Configure Chrome options"""
        options = Options()
        
        # Configure download directory
        prefs = {
            "download.default_directory": self.download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "safebrowsing.disable_download_protection": True,
            "profile.default_content_settings.popups": 0,
            "profile.default_content_setting_values.automatic_downloads": 1,
        }
        options.add_experimental_option("prefs", prefs)
        
        # Headless mode
        if self.headless:
            options.add_argument("--headless")
            options.add_argument(f"--window-size={self.window_size[0]},{self.window_size[1]}")
        
        # Performance and stability options
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Anti-detection options
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--disable-extensions")
        
        # Additional options for stability
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        
        # User agent
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        return options
    
    def quit(self) -> None:
        """Quit the WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("WebDriver closed")
            except Exception as e:
                logger.error(f"Error closing WebDriver: {e}")
            finally:
                self.driver = None
    
    def __enter__(self):
        """Context manager entry"""
        return self.create_driver()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.quit()
    
    def get_driver(self) -> webdriver.Chrome:
        """Get the current driver instance"""
        if not self.driver:
            return self.create_driver()
        return self.driver
    
    def refresh(self) -> None:
        """Refresh the current page"""
        if self.driver:
            self.driver.refresh()
    
    def clear_cache(self) -> None:
        """Clear browser cache"""
        if self.driver:
            self.driver.delete_all_cookies()
            self.driver.execute_script("window.localStorage.clear();")
            self.driver.execute_script("window.sessionStorage.clear();")
    
    def take_screenshot(self, filename: str = None) -> str:
        """Take a screenshot"""
        if not self.driver:
            raise WebDriverError("No active driver")
        
        if not filename:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
        
        screenshot_dir = Path("logs/screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = screenshot_dir / filename
        self.driver.save_screenshot(str(filepath))
        logger.info(f"Screenshot saved: {filepath}")
        
        return str(filepath)
    
    def execute_script(self, script: str, *args):
        """Execute JavaScript"""
        if not self.driver:
            raise WebDriverError("No active driver")
        
        return self.driver.execute_script(script, *args)
    
    def get_page_source(self) -> str:
        """Get current page source"""
        if not self.driver:
            raise WebDriverError("No active driver")
        
        return self.driver.page_source
    
    def get_current_url(self) -> str:
        """Get current URL"""
        if not self.driver:
            raise WebDriverError("No active driver")
        
        return self.driver.current_url