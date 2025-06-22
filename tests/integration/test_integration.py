"""
Integration tests for Sports Connect Automation
These tests require actual WebDriver and may interact with real websites
"""
import pytest
import sys
import os
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import ConfigManager
from automation.sports_connect import SportsConnectAutomation
from automation.report_handlers import ReportType


# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestSportsConnectIntegration:
    """Integration tests for Sports Connect automation"""
    
    @pytest.fixture
    def test_config(self, tmp_path):
        """Create test configuration"""
        config_data = {
            "organization_id": "14780",
            "base_url": "https://reporting.bluesombrero.com",
            "season": "2025 Fall Core",
            "download_dir": str(tmp_path / "downloads"),
            "credentials_file": str(tmp_path / "credentials.csv"),
            "default_timeout": 30,
            "download_delay": 5,
            "headless_mode": True,
            "log_level": "DEBUG",
            "reports": {
                "team_detail": {"enabled": True, "wait_time": 20},
                "volunteer_detail": {"enabled": True},
                "player_detail": {"enabled": True},
                "enrollment_summary": {"enabled": True},
                "division_details": {"enabled": True},
                "open_orders": {"enabled": True}
            }
        }
        
        config_file = tmp_path / "config.json"
        import json
        config_file.write_text(json.dumps(config_data))
        
        # Create download directory
        (tmp_path / "downloads").mkdir()
        
        return ConfigManager(str(config_file))
    
    @pytest.fixture
    def test_credentials(self, tmp_path):
        """Create test credentials file"""
        creds_file = tmp_path / "credentials.csv"
        # These would be test credentials - DO NOT use real credentials in tests
        creds_file.write_text("test@example.com,testpassword123")
        return str(creds_file)
    
    @pytest.mark.slow
    def test_webdriver_initialization(self, test_config):
        """Test WebDriver can be initialized"""
        automation = SportsConnectAutomation(test_config)
        
        try:
            automation.initialize()
            assert automation.driver is not None
            assert automation.interactor is not None
            
            # Test navigation
            automation.driver.get("https://www.google.com")
            assert "google" in automation.driver.current_url.lower()
            
        finally:
            automation.cleanup()
    
    @pytest.mark.slow
    @pytest.mark.skipif(not os.getenv("RUN_LIVE_TESTS"), reason="Live tests not enabled")
    def test_login_flow(self, test_config, test_credentials):
        """Test actual login flow (requires valid credentials)"""
        # This test would actually attempt to login
        # Should only run with valid test credentials
        automation = SportsConnectAutomation(test_config)
        
        try:
            automation.initialize()
            
            # Would need real test credentials for this to work
            result = automation.login()
            
            # If we get here with test credentials, login failed as expected
            assert result == False or not automation.logged_in
            
        finally:
            automation.cleanup()
    
    def test_full_automation_flow_mocked(self, test_config, monkeypatch):
        """Test full automation flow with mocked external calls"""
        with patch('automation.sports_connect.WebDriverManager') as mock_wdm:
            with patch('automation.sports_connect.ElementInteractor') as mock_ei:
                # Mock the driver
                mock_driver = mock_wdm.return_value.create_driver.return_value
                mock_driver.current_url = "https://reporting.bluesombrero.com/dashboard"
                
                # Mock successful interactions
                mock_interactor = mock_ei.return_value
                mock_interactor.try_multiple_selectors.return_value = True
                
                automation = SportsConnectAutomation(test_config)
                
                # Test initialization
                automation.initialize()
                assert automation.driver is not None
                
                # Test login (mocked)
                with patch('utilities.credentials.CredentialsManager.load_credentials') as mock_creds:
                    mock_creds.return_value = ("test@example.com", "password")
                    result = automation.login()
                    # Would fail with real login, but mocked should pass
                    assert automation.logged_in == True
    
    @pytest.mark.slow
    def test_download_wait_logic(self, test_config, tmp_path):
        """Test download waiting logic"""
        automation = SportsConnectAutomation(test_config)
        
        # Create a test file that simulates a download
        download_dir = tmp_path / "downloads"
        test_file = download_dir / "TestReport.xlsx"
        
        # Test finding the file
        test_file.write_text("test data")
        
        found_file = automation._find_latest_download("TestReport")
        assert found_file is not None
        assert "TestReport.xlsx" in found_file
    
    def test_report_url_generation(self, test_config):
        """Test that report URLs are generated correctly"""
        automation = SportsConnectAutomation(test_config)
        
        # Check all report URLs
        for report_type, config in automation.reports.items():
            assert config.url.startswith(test_config.base_url)
            assert test_config.organization_id in config.url
            
            if config.is_saved_report:
                assert config.report_id in config.url
    
    @pytest.mark.parametrize("report_type", list(ReportType))
    def test_report_configurations(self, test_config, report_type):
        """Test each report type has proper configuration"""
        automation = SportsConnectAutomation(test_config)
        
        report_config = automation.reports[report_type]
        assert report_config.name
        assert report_config.url
        assert report_config.export_filename_prefix
        assert report_config.wait_time > 0


class TestEndToEndScenarios:
    """End-to-end scenario tests"""
    
    @pytest.mark.slow
    @pytest.mark.skipif(not os.getenv("RUN_E2E_TESTS"), reason="E2E tests not enabled")
    def test_single_report_export(self, test_config):
        """Test exporting a single report end-to-end"""
        # This would be a full end-to-end test with real browser
        # Requires proper test environment setup
        pass
    
    @pytest.mark.slow  
    @pytest.mark.skipif(not os.getenv("RUN_E2E_TESTS"), reason="E2E tests not enabled")
    def test_all_reports_export(self, test_config):
        """Test exporting all reports end-to-end"""
        # This would test the full workflow
        # Requires proper test environment setup
        pass


# Fixtures for integration testing

@pytest.fixture(scope="session")
def chrome_driver_path():
    """Ensure ChromeDriver is available"""
    from webdriver_manager.chrome import ChromeDriverManager
    return ChromeDriverManager().install()


@pytest.fixture
def clean_screenshots(tmp_path):
    """Clean up screenshots after tests"""
    screenshots_dir = tmp_path / "logs" / "screenshots"
    screenshots_dir.mkdir(parents=True)
    yield screenshots_dir
    # Cleanup happens automatically with tmp_path


# Run integration tests separately
if __name__ == "__main__":
    # Run only integration tests
    pytest.main([__file__, "-v", "-m", "integration"])
