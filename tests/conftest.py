"""
Pytest configuration and shared fixtures for Sports Connect Automation tests
"""
import pytest
import sys
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# Global fixtures

@pytest.fixture(scope="session")
def test_data_dir():
    """Create a temporary directory for test data that persists for the session"""
    temp_dir = tempfile.mkdtemp(prefix="sports_connect_test_")
    yield Path(temp_dir)
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_webdriver():
    """Mock WebDriver for unit tests"""
    driver = Mock()
    driver.current_url = "https://example.com"
    driver.page_source = "<html><body>Test</body></html>"
    driver.title = "Test Page"
    driver.find_element.return_value = Mock()
    driver.find_elements.return_value = [Mock()]
    return driver


@pytest.fixture
def sample_config_dict():
    """Sample configuration dictionary"""
    return {
        "organization_id": "14780",
        "base_url": "https://reporting.bluesombrero.com",
        "season": "2025 Fall Core",
        "download_dir": "data/downloads",
        "credentials_file": "config/credentials.csv",
        "default_timeout": 30,
        "download_delay": 5,
        "headless_mode": True,
        "log_level": "INFO",
        "reports": {
            "team_detail": {
                "enabled": True,
                "url_suffix": "/admin/static/TeamDetailReportsNewRegistration",
                "wait_time": 20
            },
            "volunteer_detail": {
                "enabled": True,
                "saved_report_id": "173209",
                "wait_time": 10
            },
            "player_detail": {
                "enabled": True,
                "saved_report_id": "65583",
                "wait_time": 12
            },
            "enrollment_summary": {
                "enabled": True,
                "url_suffix": "/admin/program-enrollment-summary",
                "wait_time": 10
            },
            "division_details": {
                "enabled": True,
                "saved_report_id": "173208",
                "wait_time": 5
            },
            "open_orders": {
                "enabled": True,
                "saved_report_id": "110470",
                "wait_time": 20
            }
        }
    }


@pytest.fixture
def mock_config(sample_config_dict):
    """Mock ConfigManager"""
    from core.config import ConfigManager
    config = Mock(spec=ConfigManager)
    
    # Set all properties
    for key, value in sample_config_dict.items():
        setattr(config, key, value)
    
    # Mock methods
    config.get.side_effect = lambda key, default=None: sample_config_dict.get(key, default)
    config.is_report_enabled.side_effect = lambda name: sample_config_dict["reports"].get(name, {}).get("enabled", False)
    config.get_report_config.side_effect = lambda name: sample_config_dict["reports"].get(name, {})
    
    return config


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging configuration between tests"""
    import logging
    # Remove all handlers
    logger = logging.getLogger()
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    yield
    # Cleanup after test
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)


@pytest.fixture
def capture_logs():
    """Capture log messages during tests"""
    import logging
    
    class LogCapture:
        def __init__(self):
            self.records = []
            self.handler = None
            
        def __enter__(self):
            self.handler = logging.Handler()
            self.handler.emit = lambda record: self.records.append(record)
            logging.getLogger().addHandler(self.handler)
            return self
            
        def __exit__(self, *args):
            logging.getLogger().removeHandler(self.handler)
            
        def get_messages(self, level=None):
            if level:
                return [r.getMessage() for r in self.records if r.levelname == level]
            return [r.getMessage() for r in self.records]
    
    return LogCapture()


# Markers and configuration

def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
    config.addinivalue_line("markers", "e2e: marks tests as end-to-end tests")
    config.addinivalue_line("markers", "skip_ci: marks tests to skip in CI/CD")


def pytest_collection_modifyitems(config, items):
    """Modify test collection"""
    # Add markers based on test location
    for item in items:
        # Add unit marker to tests in unit directory
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        # Add integration marker to tests in integration directory
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.slow)
    
    # Skip integration tests if not explicitly requested
    if not config.getoption("-m"):
        skip_integration = pytest.mark.skip(reason="Integration tests not selected")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


# Hooks for test reporting

def pytest_runtest_setup(item):
    """Setup for each test"""
    # Could add custom setup here
    pass


def pytest_runtest_teardown(item):
    """Teardown for each test"""
    # Could add custom teardown here
    pass


@pytest.fixture(scope="session", autouse=True)
def configure_test_environment():
    """Configure the test environment"""
    # Set environment variables for testing
    os.environ["SPORTS_CONNECT_TEST_MODE"] = "1"
    yield
    # Cleanup
    os.environ.pop("SPORTS_CONNECT_TEST_MODE", None)
