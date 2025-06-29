"""
Path resolver utility for Sports Connect Automation
Handles environment variable expansion in configuration paths
"""
import os
import re
from pathlib import Path
from typing import Union, Dict, Any

class PathResolver:
    """Resolves environment variables and relative paths in configuration"""
    
    @staticmethod
    def resolve_path(path: str) -> str:
        """
        Resolve environment variables and normalize path
        
        Args:
            path: Path string that may contain environment variables
            
        Returns:
            Resolved absolute path string
        """
        if not path:
            return path
        
        # Handle environment variables like ${USERPROFILE} or %USERPROFILE%
        resolved_path = path
        
        # Handle ${VAR} format
        env_vars = re.findall(r'\$\{([^}]+)\}', path)
        for var in env_vars:
            env_value = os.environ.get(var, '')
            if env_value:
                resolved_path = resolved_path.replace(f'${{{var}}}', env_value)
        
        # Handle %VAR% format (Windows style)
        env_vars = re.findall(r'%([^%]+)%', resolved_path)
        for var in env_vars:
            env_value = os.environ.get(var, '')
            if env_value:
                resolved_path = resolved_path.replace(f'%{var}%', env_value)
        
        # Expand user directory (~)
        resolved_path = os.path.expanduser(resolved_path)
        
        # Convert to absolute path
        resolved_path = os.path.abspath(resolved_path)
        
        return resolved_path
    
    @staticmethod
    def resolve_config_paths(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively resolve all paths in configuration dictionary
        
        Args:
            config: Configuration dictionary
            
        Returns:
            Configuration with resolved paths
        """
        resolved_config = {}
        
        for key, value in config.items():
            if isinstance(value, dict):
                # Recursively resolve nested dictionaries
                resolved_config[key] = PathResolver.resolve_config_paths(value)
            elif isinstance(value, str) and PathResolver._is_path_like(key, value):
                # Resolve path strings
                resolved_config[key] = PathResolver.resolve_path(value)
            else:
                # Keep other values as-is
                resolved_config[key] = value
        
        return resolved_config
    
    @staticmethod
    def _is_path_like(key: str, value: str) -> bool:
        """
        Determine if a string value represents a file/directory path
        
        Args:
            key: Configuration key name
            value: String value to check
            
        Returns:
            True if value appears to be a path
        """
        # Keys that typically contain paths
        path_keys = [
            'path', 'dir', 'directory', 'file', 'exe_path', 'db_path',
            'download_dir', 'log_dir', 'archive_dir', 'credentials_file',
            'access_exe_path', 'access_db_path', 'user_profile', 
            'onedrive_path', 'ayso_path', 'sports_connect_creds',
            'google_creds', 'token_file'
        ]
        
        # Check if key name suggests it's a path
        key_lower = key.lower()
        if any(path_key in key_lower for path_key in path_keys):
            return True
        
        # Check if value looks like a path
        if isinstance(value, str):
            # skip if email address
            if re.match(r'^[a-zA-Z0-9._%-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', value):
                return False
            # skip if url
            if 'http' in value:
                return False
            # Contains environment variables
            if '${' in value or '%' in value:
                return True
            # Contains path separators
            if '\\' in value or '/' in value:
                return True
            # not a filename
            if '.' not in value:
                return False
            # Has file extension
            if '.' in value and len(value.split('.')[-1]) <= 5:
                return True
        
        return False
    
    @staticmethod
    def ensure_directory_exists(path: str) -> bool:
        """
        Ensure directory exists, create if necessary
        
        Args:
            path: Directory path to create
            
        Returns:
            True if directory exists or was created successfully
        """
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            return True
        except Exception:
            return False
    
    @staticmethod
    def validate_path_exists(path: str, path_type: str = 'file') -> bool:
        """
        Validate that a path exists
        
        Args:
            path: Path to validate
            path_type: 'file' or 'directory'
            
        Returns:
            True if path exists and is correct type
        """
        if not path or not os.path.exists(path):
            return False
        
        if path_type == 'file':
            return os.path.isfile(path)
        elif path_type == 'directory':
            return os.path.isdir(path)
        
        return True
    
    @staticmethod
    def get_common_paths() -> Dict[str, str]:
        """
        Get common system paths for reference
        
        Returns:
            Dictionary of common system paths
        """
        userprofile = os.environ.get('USERPROFILE', os.path.expanduser('~'))
        
        return {
            'userprofile': userprofile,
            'onedrive': os.path.join(userprofile, 'OneDrive'),
            'ayso': os.path.join(userprofile, 'OneDrive', 'AYSO'),
            'downloads': os.path.join(userprofile, 'Downloads'),
            'documents': os.path.join(userprofile, 'Documents'),
            'desktop': os.path.join(userprofile, 'Desktop'),
            'temp': os.environ.get('TEMP', '/tmp'),
            'program_files': os.environ.get('PROGRAMFILES', 'C:\\Program Files'),
            'program_files_x86': os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)')
        }
    
    @staticmethod
    def find_office_path() -> str:
        """
        Find Microsoft Office installation path
        
        Returns:
            Path to Microsoft Office executable directory
        """
        possible_paths = [
            "C:\\Program Files\\Microsoft Office\\root\\Office16",
            "C:\\Program Files (x86)\\Microsoft Office\\root\\Office16",
            "C:\\Program Files\\Microsoft Office\\Office16",
            "C:\\Program Files (x86)\\Microsoft Office\\Office16"
        ]
        
        for path in possible_paths:
            if os.path.exists(os.path.join(path, 'msaccess.exe')):
                return path
        
        return "C:\\Program Files\\Microsoft Office\\root\\Office16"  # Default fallback
    
    @staticmethod
    def generate_default_config_paths(username: str = None) -> Dict[str, str]:
        """
        Generate default configuration paths for a user
        
        Args:
            username: Optional username, uses current user if not provided
            
        Returns:
            Dictionary of default paths
        """
        if not username:
            userprofile = os.environ.get('USERPROFILE', os.path.expanduser('~'))
        else:
            userprofile = f"C:\\Users\\{username}"
        
        office_path = PathResolver.find_office_path()
        
        return {
            'user_profile': userprofile,
            'onedrive_path': f"{userprofile}\\OneDrive",
            'ayso_path': f"{userprofile}\\OneDrive\\AYSO",
            'download_dir': "data/downloads",
            'log_dir': "logs", 
            'archive_dir': "data/archives",
            'credentials_file': "config/credentials.json",
            'sports_connect_creds': f"{userprofile}\\OneDrive\\AYSO\\sports_connect_creds.csv",
            'access_exe_path': f"{office_path}\\msaccess.exe",
            'access_db_path': f"{userprofile}\\OneDrive\\AYSO\\AYSO 2019 2019_906-fidelio.accdb"
        }
