"""
Credentials management for Sports Connect Automation
"""
import csv
import os
import stat
import getpass
from pathlib import Path
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class CredentialsManager:
    """Manages credentials for Sports Connect"""
    
    @staticmethod
    def save_credentials(username: str, password: str, filepath: str) -> None:
        """
        Save credentials to CSV file
        
        Args:
            username: Sports Connect username
            password: Sports Connect password
            filepath: Path to credentials file
        """
        # Create directory if needed
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        # Write credentials
        with open(filepath, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile, delimiter=',', quotechar='|')
            writer.writerow([username, password])
        
        # Set file permissions (Windows/Unix compatible)
        try:
            # Try Unix-style permissions
            os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR)
        except:
            # Windows fallback - file will have default permissions
            pass
        
        logger.info(f"Credentials saved to: {filepath}")
    
    @staticmethod
    def load_credentials(filepath: str) -> Tuple[str, str]:
        """
        Load credentials from CSV file
        
        Args:
            filepath: Path to credentials file
            
        Returns:
            Tuple of (username, password)
            
        Raises:
            FileNotFoundError: If credentials file doesn't exist
            ValueError: If file format is invalid
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Credentials file not found: {filepath}")
        
        with open(filepath, 'r', newline='') as csvfile:
            reader = csv.reader(csvfile, delimiter=',', quotechar='|')
            for row in reader:
                if len(row) >= 2:
                    username = row[0].strip()
                    password = row[1].strip()
                    logger.info(f"Loaded credentials for user: {username}")
                    return username, password
        
        raise ValueError("Invalid credentials file format")
    
    @staticmethod
    def update_credentials(filepath: str) -> bool:
        """
        Interactive credential update
        
        Args:
            filepath: Path to credentials file
            
        Returns:
            True if credentials were updated
        """
        print("\nUpdate Sports Connect Credentials")
        print("-" * 40)
        
        # Get current username if file exists
        current_username = ""
        if os.path.exists(filepath):
            try:
                current_username, _ = CredentialsManager.load_credentials(filepath)
                print(f"Current username: {current_username}")
            except:
                pass
        
        # Get new credentials
        username = input(f"Enter username [{current_username}]: ").strip()
        if not username:
            username = current_username
        
        if not username:
            print("Username is required!")
            return False
        
        password = getpass.getpass("Enter password: ")
        if not password:
            print("Password is required!")
            return False
        
        # Confirm
        confirm = input("\nSave credentials? (y/n): ").lower()
        if confirm == 'y':
            CredentialsManager.save_credentials(username, password, filepath)
            print("Credentials updated successfully!")
            return True
        else:
            print("Credentials update cancelled.")
            return False
    
    @staticmethod
    def validate_credentials(username: str, password: str) -> bool:
        """
        Basic validation of credentials
        
        Args:
            username: Username to validate
            password: Password to validate
            
        Returns:
            True if credentials appear valid
        """
        if not username or not password:
            return False
        
        # Basic email validation for username
        if '@' in username:
            parts = username.split('@')
            if len(parts) != 2 or not parts[0] or not parts[1]:
                return False
        
        # Password should have minimum length
        if len(password) < 6:
            return False
        
        return True
    
    @staticmethod
    def create_credentials_file_interactive(filepath: str) -> bool:
        """
        Create credentials file with interactive prompts
        
        Args:
            filepath: Path to credentials file
            
        Returns:
            True if file was created
        """
        print("\nCreate Sports Connect Credentials File")
        print("=" * 40)
        print("This will create a credentials file for automated login.")
        print("Your password will be stored in plain text.")
        print("Make sure to secure the file appropriately.")
        print()
        
        proceed = input("Continue? (y/n): ").lower()
        if proceed != 'y':
            print("Cancelled.")
            return False
        
        return CredentialsManager.update_credentials(filepath)
    
    @staticmethod
    def check_credentials_exist(filepath: str) -> bool:
        """Check if credentials file exists and is valid"""
        if not os.path.exists(filepath):
            return False
        
        try:
            username, password = CredentialsManager.load_credentials(filepath)
            return CredentialsManager.validate_credentials(username, password)
        except:
            return False


class CredentialsEncryption:
    """Optional encryption for credentials (requires cryptography package)"""
    
    @staticmethod
    def is_available() -> bool:
        """Check if encryption is available"""
        try:
            from cryptography.fernet import Fernet
            return True
        except ImportError:
            return False
    
    @staticmethod
    def generate_key() -> bytes:
        """Generate encryption key"""
        if not CredentialsEncryption.is_available():
            raise ImportError("cryptography package not installed")
        
        from cryptography.fernet import Fernet
        return Fernet.generate_key()
    
    @staticmethod
    def encrypt_password(password: str, key: bytes) -> bytes:
        """Encrypt password"""
        if not CredentialsEncryption.is_available():
            raise ImportError("cryptography package not installed")
        
        from cryptography.fernet import Fernet
        f = Fernet(key)
        return f.encrypt(password.encode())
    
    @staticmethod
    def decrypt_password(encrypted: bytes, key: bytes) -> str:
        """Decrypt password"""
        if not CredentialsEncryption.is_available():
            raise ImportError("cryptography package not installed")
        
        from cryptography.fernet import Fernet
        f = Fernet(key)
        return f.decrypt(encrypted).decode()
