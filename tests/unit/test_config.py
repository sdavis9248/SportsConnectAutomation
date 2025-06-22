"""
Unit tests for configuration management
"""
import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import ConfigManager
from core.exceptions import ConfigurationError


class TestConfigManager:
    """Test ConfigManager class"""
    
    @pytest.fixture
    def sample_config(self, tmp_path):
        """Create a sample configuration file"""
        config_data = {
            "organization_id": "14780",
            "base_url": "https://reporting.bluesombrero.com",
            "season": "2025 Fall Core",
            "download_dir": "data/downloads",
            "credentials_file": "config/credentials.csv",
            "default_timeout": 30,
            "download_delay": 5,
            "headless_mode": False,
            "log_level": "INFO",
            "reports": {
                "team_detail": {
                    "enabled": True,
                    "wait_time": 20
                },
                "volunteer_detail": {
                    "enabled": False,
                    "saved_report_id": "173209"
                }
            }
        }
        
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data, indent=2))
        return config_file
    
    def test_load_config_success(self, sample_config):
        """Test successful config loading"""
        config = ConfigManager(str(sample_config))
        loaded = config.load_config()
        
        assert loaded["organization_id"] == "14780"
        assert loaded["season"] == "2025 Fall Core"
        assert loaded["reports"]["team_detail"]["enabled"] == True
    
    def test_load_config_file_not_found(self):
        """Test loading non-existent config file"""
        config = ConfigManager("nonexistent.json")
        
        with pytest.raises(FileNotFoundError):
            config.load_config()
    
    def test_get_simple_value(self, sample_config):
        """Test getting simple configuration value"""
        config = ConfigManager(str(sample_config))
        
        assert config.get("organization_id") == "14780"
        assert config.get("download_delay") == 5
        assert config.get("nonexistent", "default") == "default"
    
    def test_get_nested_value(self, sample_config):
        """Test getting nested configuration value"""
        config = ConfigManager(str(sample_config))
        
        assert config.get("reports.team_detail.enabled") == True
        assert config.get("reports.volunteer_detail.saved_report_id") == "173209"
        assert config.get("reports.invalid.key", None) is None
    
    def test_set_simple_value(self, sample_config):
        """Test setting simple configuration value"""
        config = ConfigManager(str(sample_config))
        
        config.set("season", "2026 Spring Core")
        assert config.get("season") == "2026 Spring Core"
        
        # Verify it was saved
        reloaded = ConfigManager(str(sample_config))
        assert reloaded.get("season") == "2026 Spring Core"
    
    def test_set_nested_value(self, sample_config):
        """Test setting nested configuration value"""
        config = ConfigManager(str(sample_config))
        
        config.set("reports.team_detail.wait_time", 30)
        assert config.get("reports.team_detail.wait_time") == 30
        
        # Test creating new nested path
        config.set("new.nested.value", "test")
        assert config.get("new.nested.value") == "test"
    
    def test_properties(self, sample_config):
        """Test configuration properties"""
        config = ConfigManager(str(sample_config))
        
        assert config.organization_id == "14780"
        assert config.base_url == "https://reporting.bluesombrero.com"
        assert config.season == "2025 Fall Core"
        assert config.download_dir == "data/downloads"
        assert config.credentials_file == "config/credentials.csv"
        assert config.default_timeout == 30
        assert config.download_delay == 5
        assert config.headless_mode == False
        assert config.log_level == "INFO"
    
    def test_report_methods(self, sample_config):
        """Test report-specific methods"""
        config = ConfigManager(str(sample_config))
        
        # Test get_report_config
        team_config = config.get_report_config("team_detail")
        assert team_config["enabled"] == True
        assert team_config["wait_time"] == 20
        
        # Test is_report_enabled
        assert config.is_report_enabled("team_detail") == True
        assert config.is_report_enabled("volunteer_detail") == False
        assert config.is_report_enabled("nonexistent") == False
    
    def test_default_values(self, tmp_path):
        """Test default values when config is missing fields"""
        config_file = tmp_path / "minimal.json"
        config_file.write_text("{}")
        
        config = ConfigManager(str(config_file))
        
        # Properties should return defaults
        assert config.organization_id == "14780"
        assert config.default_timeout == 30
        assert config.headless_mode == False
