"""
Test suite for Sports Connect Automation
"""
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.config import ConfigManager
from core.exceptions import LoginError, ReportExportError
from automation.sports_connect import SportsConnectAutomation
from automation.report_handlers import ReportType, ReportConfig
from utilities.credentials import CredentialsManager


class TestConfigManager:
    """Test configuration management"""
    
    def test_load_config(self, tmp_path):
        """Test loading configuration from file"""
        # Create test config
        config_file = tmp_path / "test_config.json"
        config_data = {
            "organization_id": "12345",
            "season": "2025 Test Season",
            "download_dir": "test/downloads"
        }
        
        import json
        config_file.write_text(json.dumps(config_data))
        
        # Test loading
        config = ConfigManager(str(config_file))
        assert config.organization_id == "12345"
        assert config.season == "2025 Test Season"
        assert config.download_dir == "test/downloads"
    
    def test_get_nested_config(self, tmp_path):
        """Test getting nested configuration values"""
        config_file = tmp_path / "test_config.json"
        config_data = {
            "reports": {
                "team_detail": {
                    "enabled": True,
                    "wait_time": 20
                }
            }
        }
        
        import json
        config_file.write_text(json.dumps(config_data))
        
        config = ConfigManager(str(config_file))
        assert config.get("reports.team_detail.enabled") == True
        assert config.get("reports.team_detail.wait_time") == 20
        assert config.get("reports.invalid.key", "default") == "default"
    
    def test_is_report_enabled(self, tmp_path):
        """Test checking if report is enabled"""
        config_file = tmp_path / "test_config.json"
        config_data = {
            "reports": {
                "team_detail": {"enabled": True},
                "player_detail": {"enabled": False}
            }
        }
        
        import json
        config_file.write_text(json.dumps(config_data))
        
        config = ConfigManager(str(config_file))
        assert config.is_report_enabled("team_detail") == True
        assert config.is_report_enabled("player_detail") == False
        assert config.is_report_enabled("nonexistent") == False


class TestCredentialsManager:
    """Test credentials management"""
    
    def test_save_and_load_credentials(self, tmp_path):
        """Test saving and loading credentials"""
        creds_file = tmp_path / "test_creds.csv"
        
        # Save credentials
        CredentialsManager.save_credentials(
            "test@example.com",
            "testpass123",
            str(creds_file)
        )
        
        # Load credentials
        username, password = CredentialsManager.load_credentials(str(creds_file))
        assert username == "test@example.com"
        assert password == "testpass123"
    
    def test_validate_credentials(self):
        """Test credential validation"""
        assert CredentialsManager.validate_credentials("user@example.com", "password123") == True
        assert CredentialsManager.validate_credentials("", "password") == False
        assert CredentialsManager.validate_credentials("user", "") == False
        assert CredentialsManager.validate_credentials("user", "short") == False


class TestSportsConnectAutomation:
    """Test main automation class"""
    
    @pytest.fixture
    def mock_config(self):
        """Create mock configuration"""
        config = Mock(spec=ConfigManager)
        config.organization_id = "14780"
        config.base_url = "https://reporting.bluesombrero.com"
        config.season = "2025 Fall Core"
        config.download_dir = "data/downloads"
        config.credentials_file = "config/credentials.csv"
        config.default_timeout = 30
        config.download_delay = 5
        config.headless_mode = True
        config.is_report_enabled.return_value = True
        return config
    
    @pytest.fixture
    def automation(self, mock_config):
        """Create automation instance with mocked dependencies"""
        with patch('automation.sports_connect.WebDriverManager'):
            with patch('automation.sports_connect.ElementInteractor'):
                automation = SportsConnectAutomation(mock_config)
                automation.driver = Mock()
                automation.interactor = Mock()
                return automation
    
    def test_initialization(self, automation):
        """Test automation initialization"""
        assert automation.config is not None
        assert automation.logged_in == False
        assert len(automation.reports) == 6  # Should have 6 report types
    
    @patch('automation.sports_connect.CredentialsManager')
    def test_login_success(self, mock_creds, automation):
        """Test successful login"""
        # Mock credentials
        mock_creds.return_value.load_credentials.return_value = ("user@test.com", "password")
        
        # Mock driver interactions
        automation.driver.current_url = "https://reporting.bluesombrero.com/dashboard"
        automation.interactor.try_multiple_selectors.return_value = True
        
        # Test login
        result = automation.login()
        assert result == True
        assert automation.logged_in == True
    
    def test_login_not_logged_in(self, automation):
        """Test export when not logged in"""
        automation.logged_in = False
        result = automation.export_report(ReportType.TEAM_DETAIL)
        assert result is None
    
    def test_export_report_success(self, automation):
        """Test successful report export"""
        automation.logged_in = True
        automation._find_latest_download = Mock(return_value="test_report.xlsx")
        automation._click_export_button = Mock()
        automation._select_excel_format = Mock()
        
        result = automation.export_report(ReportType.TEAM_DETAIL)
        assert result == "test_report.xlsx"
        assert ReportType.TEAM_DETAIL in automation.downloaded_files
    
    def test_run_single_report(self, automation):
        """Test running a single report"""
        automation.initialize = Mock()
        automation.login = Mock(return_value=True)
        automation.export_report = Mock(return_value="report.xlsx")
        
        result = automation.run_single_report("TEAM_DETAIL")
        assert result == "report.xlsx"
        automation.export_report.assert_called_once()
    
    def test_run_invalid_report(self, automation):
        """Test running invalid report name"""
        result = automation.run_single_report("INVALID_REPORT")
        assert result is None


class TestReportHandlers:
    """Test report handlers"""
    
    def test_report_type_enum(self):
        """Test ReportType enum"""
        assert ReportType.TEAM_DETAIL.value == "Team Detail"
        assert len(ReportType) == 6
    
    def test_get_report_configs(self):
        """Test getting report configurations"""
        from automation.report_handlers import ReportHandlers
        
        configs = ReportHandlers.get_report_configs(
            "https://test.com",
            "12345"
        )
        
        assert len(configs) == 6
        assert ReportType.TEAM_DETAIL in configs
        assert configs[ReportType.TEAM_DETAIL].name == "Team Detail Report"
        assert configs[ReportType.TEAM_DETAIL].wait_time == 20
    
    def test_get_report_by_name(self):
        """Test getting report type by name"""
        from automation.report_handlers import ReportHandlers
        
        assert ReportHandlers.get_report_by_name("team detail") == ReportType.TEAM_DETAIL
        assert ReportHandlers.get_report_by_name("TEAM_DETAIL") == ReportType.TEAM_DETAIL
        assert ReportHandlers.get_report_by_name("invalid") is None


class TestWebDriverManager:
    """Test WebDriver manager"""
    
    @patch('core.webdriver_manager.webdriver.Chrome')
    @patch('core.webdriver_manager.ChromeDriverManager')
    def test_create_driver(self, mock_cdm, mock_chrome):
        """Test creating WebDriver"""
        from core.webdriver_manager import WebDriverManager
        
        manager = WebDriverManager(headless=True)
        driver = manager.create_driver()
        
        assert driver is not None
        mock_chrome.assert_called_once()
    
    def test_context_manager(self):
        """Test WebDriver context manager"""
        from core.webdriver_manager import WebDriverManager
        
        with patch('core.webdriver_manager.webdriver.Chrome'):
            with WebDriverManager() as driver:
                assert driver is not None


class TestElementInteractor:
    """Test element interaction utilities"""
    
    def test_wait_for_element(self):
        """Test waiting for element"""
        from core.element_interactor import ElementInteractor
        
        mock_driver = Mock()
        mock_element = Mock()
        mock_driver.find_element.return_value = mock_element
        
        with patch('core.element_interactor.WebDriverWait'):
            interactor = ElementInteractor(mock_driver)
            # Would need more complex mocking for full test


@pytest.fixture
def clean_downloads(tmp_path):
    """Fixture to create and clean download directory"""
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    yield download_dir
    # Cleanup happens automatically with tmp_path


def test_integration_flow(tmp_path, clean_downloads):
    """Test complete integration flow"""
    # This would be an integration test requiring actual WebDriver
    # Marked as integration test to be run separately
    pytest.skip("Integration test - requires WebDriver")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
