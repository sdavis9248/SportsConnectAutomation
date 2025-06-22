"""
Configuration manager for Sports Connect Automation
Updated with environment variable path resolution
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
from utilities.path_resolver import PathResolver

logger = logging.getLogger(__name__)

class ConfigManager:
    """Manages configuration with environment variable resolution"""
    
    def __init__(self, config_file: str = 'config/config.json'):
        """
        Initialize configuration manager
        
        Args:
            config_file: Path to configuration file
        """
        self.config_file = config_file
        self.config = {}
        self.resolved_config = {}
        
        # Default configuration
        self.defaults = {
            'base_url': 'https://reporting.bluesombrero.com',
            'organization_id': '14780',
            'season': '2025 Fall Core',
            'browser_config': {
                'headless_mode': False,
                'download_delay': 10,
                'default_timeout': 30
            },
            'paths': PathResolver.generate_default_config_paths(),
            'logging_config': {
                'log_level': 'INFO',
                'console_output': True,
                'file_output': True
            }
        }
    
    def load_config(self) -> bool:
        """
        Load configuration from file
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if config file exists
            if not os.path.exists(self.config_file):
                logger.warning(f"Config file not found: {self.config_file}")
                logger.info("Using default configuration")
                self.config = self.defaults.copy()
            else:
                # Load from file
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
                logger.info(f"Configuration loaded from: {self.config_file}")
            
            # Merge with defaults for any missing keys
            self._merge_defaults()
            
            # Resolve environment variables in paths
            self.resolved_config = PathResolver.resolve_config_paths(self.config)
            
            # Create necessary directories
            self._ensure_directories()
            
            # Validate critical paths
            self._validate_paths()
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            logger.info("Using default configuration")
            self.config = self.defaults.copy()
            self.resolved_config = PathResolver.resolve_config_paths(self.config)
            return False
    
    def save_config(self) -> bool:
        """
        Save current configuration to file
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure config directory exists
            config_dir = os.path.dirname(self.config_file)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)
            
            # Save configuration (use original config, not resolved)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            
            logger.info(f"Configuration saved to: {self.config_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value with path resolution
        
        Args:
            key: Configuration key (supports dot notation)
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        try:
            # Use resolved config for path values
            value = self._get_nested_value(self.resolved_config, key)
            if value is not None:
                return value
            
            # Fallback to original config
            value = self._get_nested_value(self.config, key)
            if value is not None:
                return value
            
            return default
            
        except Exception:
            return default
    
    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value
        
        Args:
            key: Configuration key (supports dot notation)
            value: Value to set
        """
        self._set_nested_value(self.config, key, value)
        # Re-resolve paths after setting
        self.resolved_config = PathResolver.resolve_config_paths(self.config)
    
    def _get_nested_value(self, config: Dict, key: str) -> Any:
        """Get value from nested dictionary using dot notation"""
        keys = key.split('.')
        value = config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return None
        
        return value
    
    def _set_nested_value(self, config: Dict, key: str, value: Any) -> None:
        """Set value in nested dictionary using dot notation"""
        keys = key.split('.')
        current = config
        
        # Navigate to parent of target key
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        
        # Set the value
        current[keys[-1]] = value
    
    def _merge_defaults(self) -> None:
        """Merge default values for missing keys"""
        def merge_dict(target: Dict, source: Dict) -> None:
            for key, value in source.items():
                if key not in target:
                    target[key] = value
                elif isinstance(value, dict) and isinstance(target[key], dict):
                    merge_dict(target[key], value)
        
        merge_dict(self.config, self.defaults)
    
    def _ensure_directories(self) -> None:
        """Ensure required directories exist"""
        directories = [
            self.get('paths.download_dir', 'data/downloads'),
            self.get('paths.log_dir', 'logs'),
            self.get('paths.archive_dir', 'data/archives')
        ]
        
        for directory in directories:
            if directory:
                PathResolver.ensure_directory_exists(directory)
    
    def _validate_paths(self) -> None:
        """Validate critical paths exist"""
        # Check Access executable
        access_exe = self.get('access_config.access_exe_path')
        if access_exe and not PathResolver.validate_path_exists(access_exe, 'file'):
            logger.warning(f"Access executable not found: {access_exe}")
        
        # Check Access database
        access_db = self.get('access_config.access_db_path')
        if access_db and not PathResolver.validate_path_exists(access_db, 'file'):
            logger.warning(f"Access database not found: {access_db}")
        
        # Check credentials file
        creds_file = self.get('credentials_config.sports_connect_creds')
        if creds_file and not PathResolver.validate_path_exists(creds_file, 'file'):
            logger.warning(f"Credentials file not found: {creds_file}")
    
    def is_report_enabled(self, report_name: str) -> bool:
        """
        Check if a report is enabled
        
        Args:
            report_name: Name of the report
            
        Returns:
            True if enabled, False otherwise
        """
        return self.get(f'reports.{report_name}', False)
    
    def get_common_paths(self) -> Dict[str, str]:
        """Get common resolved paths"""
        return {
            'download_dir': self.get('paths.download_dir'),
            'log_dir': self.get('paths.log_dir'),
            'archive_dir': self.get('paths.archive_dir'),
            'user_profile': self.get('paths.user_profile'),
            'onedrive_path': self.get('paths.onedrive_path'),
            'ayso_path': self.get('paths.ayso_path'),
            'credentials_file': self.get('paths.credentials_file')
        }
    
    def get_access_config(self) -> Dict[str, Any]:
        """Get Access database configuration"""
        return {
            'enabled': self.get('access_config.enabled', True),
            'exe_path': self.get('access_config.access_exe_path'),
            'db_path': self.get('access_config.access_db_path'),
            'macros': self.get('access_config.macros', {}),
            'auto_run': self.get('access_config.auto_run_macros', True),
            'backup': self.get('access_config.backup_before_macro', False)
        }
    
    def get_browser_config(self) -> Dict[str, Any]:
        """Get browser configuration"""
        return {
            'headless': self.get('browser_config.headless_mode', False),
            'timeout': self.get('browser_config.default_timeout', 30),
            'download_delay': self.get('browser_config.download_delay', 10),
            'window_size': self.get('browser_config.window_size', [1920, 1080])
        }
    
    def generate_config_template(self, username: str = None) -> Dict[str, Any]:
        """
        Generate a configuration template for a user
        
        Args:
            username: Optional username
            
        Returns:
            Configuration template
        """
        paths = PathResolver.generate_default_config_paths(username)
        
        template = {
            "base_url": "https://reporting.bluesombrero.com",
            "organization_id": "14780", 
            "season": "Fall 2024",
            "program_id": "120032032",
            "program_name": "2025 Fall Core",
            
            "browser_config": {
                "headless_mode": False,
                "download_delay": 10,
                "default_timeout": 30,
                "window_size": [1920, 1080]
            },
            
            "paths": {
                "download_dir": "data/downloads",
                "log_dir": "logs",
                "credentials_file": "config/credentials.json",
                "archive_dir": "data/archives",
                "user_profile": "${USERPROFILE}",
                "onedrive_path": "${USERPROFILE}\\OneDrive",
                "ayso_path": "${USERPROFILE}\\OneDrive\\AYSO"
            },
            
            "reports": {
                "team_detail": True,
                "volunteer_detail": True,
                "player_detail": True,
                "enrollment_summary": True,
                "division_details": True,
                "open_orders": True,
                "waitlist_management": False,
                "admin_credentials": True,
                "admin_details": True
            },
            
            "credentials_config": {
                "sports_connect_creds": "${USERPROFILE}\\OneDrive\\AYSO\\sports_connect_creds.csv",
                "google_creds": "credentials.json",
                "token_file": "token.pickle"
            },
            
            "access_config": {
                "enabled": True,
                "access_exe_path": f"{PathResolver.find_office_path()}\\msaccess.exe",
                "access_db_path": "${USERPROFILE}\\OneDrive\\AYSO\\AYSO 2019 2019_906-fidelio.accdb",
                "macros": {
                    "admin_detail": "UpdateAdminDetail",
                    "enrollment_summary": "UpdateEnrollmentSummary"
                },
                "auto_run_macros": True,
                "backup_before_macro": False
            }
        }
        
        return template
    
    # Convenience properties for common values
    @property
    def base_url(self) -> str:
        return self.get('base_url', 'https://reporting.bluesombrero.com')
    
    @property
    def organization_id(self) -> str:
        return self.get('organization_id', '14780')
    
    @property
    def season(self) -> str:
        return self.get('season', 'Fall 2025 Core')
    
    @property
    def download_dir(self) -> str:
        return self.get('paths.download_dir', 'data/downloads')
    
    @property
    def headless_mode(self) -> bool:
        return self.get('browser_config.headless_mode', False)
    
    @property
    def default_timeout(self) -> int:
        return self.get('browser_config.default_timeout', 30)
    
    @property
    def download_delay(self) -> int:
        return self.get('browser_config.download_delay', 10)
    
    @property
    def credentials_file(self) -> str:
        return self.get('credentials_config.sports_connect_creds', 
                       self.get('paths.credentials_file', 'config/credentials.json'))