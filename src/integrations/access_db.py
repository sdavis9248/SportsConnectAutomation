"""
Microsoft Access Database Manager for Sports Connect Automation
Handles Access database operations and macro execution
"""
import os
import logging
import subprocess
import glob
from pathlib import Path
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

class AccessDatabaseManager:
    """Manages Microsoft Access database operations"""
    
    def __init__(self, config=None):
        """
        Initialize Access Database Manager
        
        Args:
            config: Configuration manager instance
        """
        self.config = config
        
        # Get user profile directory from environment
        userprofile = os.getenv('USERPROFILE', os.path.expanduser('~'))
        
        # Get paths from config or use defaults
        if config:
            access_config = config.get('access_config', {})
            
            # Get paths and replace {userprofile} placeholder
            access_exe_path = access_config.get('access_exe_path', 
                "C:\\Program Files\\Microsoft Office\\root\\Office16\\msaccess.exe")
            database_path = access_config.get('access_db_path',
                "{userprofile}\\OneDrive\\AYSO\\AYSO 2019 2019_906-fidelio.accdb")
            
            # Replace {userprofile} placeholder with actual path
            self.access_exe_path = access_exe_path.replace('{userprofile}', userprofile)
            self.database_path = database_path.replace('{userprofile}', userprofile)
        else:
            # Default paths using environment userprofile
            self.access_exe_path = "C:\\Program Files\\Microsoft Office\\root\\Office16\\msaccess.exe"
            self.database_path = f"{userprofile}\\OneDrive\\AYSO\\AYSO 2019 2019_906-fidelio.accdb"
    
    def run_macro(self, macro_name: str) -> bool:
        """
        Run a macro in the Access database
        
        Args:
            macro_name: Name of the macro to run
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f'Running Access macro: {macro_name}')
        
        try:
            # Verify Access executable exists
            if not os.path.exists(self.access_exe_path):
                logger.error(f"Microsoft Access not found at: {self.access_exe_path}")
                return False
            
            # Verify database exists
            if not os.path.exists(self.database_path):
                logger.error(f"Access database not found at: {self.database_path}")
                return False
            
            # Construct Access command
            cmd = f'"{self.access_exe_path}" "{self.database_path}" /x {macro_name}'
            
            logger.info(f"Executing command: {cmd}")
            
            # Run the macro
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                logger.info(f"Access macro '{macro_name}' completed successfully")
                return True
            else:
                logger.error(f"Access macro failed with return code: {result.returncode}")
                if result.stderr:
                    logger.error(f"Error output: {result.stderr}")
                if result.stdout:
                    logger.info(f"Standard output: {result.stdout}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"Access macro '{macro_name}' timed out after 5 minutes")
            return False
        except Exception as e:
            logger.error(f"Error running Access macro '{macro_name}': {e}")
            return False
    
    def run_admin_detail_macro(self) -> bool:
        """Run the UpdateAdminDetail macro (Sports Affinity specific)"""
        return self.run_macro("UpdateAdminDetail")
    
    def run_enrollment_summary_macro(self) -> bool:
        """Run the UpdateEnrollmentSummary macro (Sports Connect specific)"""
        return self.run_macro("UpdateEnrollmentSummary")
    
    def open_file_in_excel(self, file_path: str) -> bool:
        """
        Open a file in Microsoft Excel
        
        Args:
            file_path: Path to the file to open
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                return False
            
            # Try different Excel executable paths
            excel_paths = [
                "C:\\Program Files\\Microsoft Office\\root\\Office16\\excel.exe",
                "C:\\Program Files (x86)\\Microsoft Office\\root\\Office16\\excel.exe",
                "excel"  # If in PATH
            ]
            
            excel_exe = None
            for path in excel_paths:
                if os.path.exists(path) or path == "excel":
                    excel_exe = path
                    break
            
            if not excel_exe:
                logger.error("Microsoft Excel not found")
                return False
            
            # Open file in Excel
            cmd = f'"{excel_exe}" "{file_path}"'
            subprocess.Popen(cmd, shell=True)
            
            logger.info(f"Opened file in Excel: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error opening file in Excel: {e}")
            return False
    
    def find_enrollment_summary_file(self, search_directory: str) -> Optional[str]:
        """
        Find the enrollment summary file in a directory
        
        Args:
            search_directory: Directory to search in
            
        Returns:
            Path to the file if found, None otherwise
        """
        try:
            if not os.path.exists(search_directory):
                logger.warning(f"Search directory not found: {search_directory}")
                return None
            
            # Search patterns for enrollment summary files
            patterns = [
                "*enrollment*summary*.xlsx",
                "*enrollment*summary*.xls",
                "*ProgramEnrollmentSummary*.xlsx",
                "*enrollment*.xlsx"
            ]
            
            for pattern in patterns:
                search_path = os.path.join(search_directory, pattern)
                files = glob.glob(search_path, recursive=True)
                
                if files:
                    # Return the most recent file
                    latest_file = max(files, key=os.path.getmtime)
                    logger.info(f"Found enrollment summary file: {latest_file}")
                    return latest_file
            
            logger.warning(f"No enrollment summary file found in: {search_directory}")
            return None
            
        except Exception as e:
            logger.error(f"Error searching for enrollment summary file: {e}")
            return None
    
    def backup_database(self, backup_dir: str = None) -> Optional[str]:
        """
        Create a backup of the Access database
        
        Args:
            backup_dir: Directory to store backup (optional)
            
        Returns:
            Path to backup file if successful, None otherwise
        """
        try:
            if backup_dir is None:
                backup_dir = os.path.dirname(self.database_path)
            
            # Create backup directory if it doesn't exist
            os.makedirs(backup_dir, exist_ok=True)
            
            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_name = Path(self.database_path).stem
            backup_filename = f"{db_name}_backup_{timestamp}.accdb"
            backup_path = os.path.join(backup_dir, backup_filename)
            
            # Copy database file
            import shutil
            shutil.copy2(self.database_path, backup_path)
            
            logger.info(f"Database backup created: {backup_path}")
            return backup_path
            
        except Exception as e:
            logger.error(f"Error creating database backup: {e}")
            return None
    
    def check_database_connection(self) -> bool:
        """
        Check if the database can be accessed
        
        Returns:
            True if database is accessible, False otherwise
        """
        try:
            if not os.path.exists(self.database_path):
                logger.error(f"Database file not found: {self.database_path}")
                return False
            
            # Check if file is readable
            with open(self.database_path, 'rb') as f:
                # Read first few bytes to verify it's a valid Access file
                header = f.read(16)
                if b'Standard Jet DB' in header or b'Standard ACE DB' in header:
                    logger.info("Database connection check successful")
                    return True
                else:
                    logger.error("File does not appear to be a valid Access database")
                    return False
                    
        except Exception as e:
            logger.error(f"Error checking database connection: {e}")
            return False
    
    def get_database_info(self) -> dict:
        """
        Get information about the database
        
        Returns:
            Dictionary with database information
        """
        info = {
            "database_path": self.database_path,
            "access_exe_path": self.access_exe_path,
            "database_exists": os.path.exists(self.database_path),
            "access_exe_exists": os.path.exists(self.access_exe_path),
            "database_size": 0,
            "last_modified": None
        }
        
        try:
            if info["database_exists"]:
                stat = os.stat(self.database_path)
                info["database_size"] = stat.st_size
                info["last_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                
        except Exception as e:
            logger.error(f"Error getting database info: {e}")
        
        return info
    
    def list_available_macros(self) -> List[str]:
        """
        List commonly used macros (this is a static list since we can't easily query Access)
        
        Returns:
            List of macro names
        """
        return [
            "UpdateAdminDetail",           # Sports Affinity admin details
            "UpdateEnrollmentSummary",     # Sports Connect enrollment
            "ImportTeamDetails",           # Team detail imports
            "ImportVolunteerData",         # Volunteer data imports
            "UpdatePlayerDetails",         # Player detail updates
            "GenerateReports",             # Report generation
            "DataValidation",              # Data validation routines
            "BackupData"                   # Data backup routines
        ]