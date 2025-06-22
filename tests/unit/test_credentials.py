"""
Unit tests for credentials management
"""
import pytest
import os
import sys
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from utilities.credentials import CredentialsManager, CredentialsEncryption


class TestCredentialsManager:
    """Test CredentialsManager class"""
    
    def test_save_credentials(self, tmp_path):
        """Test saving credentials to file"""
        creds_file = tmp_path / "test_creds.csv"
        
        CredentialsManager.save_credentials(
            "testuser@example.com",
            "testpassword123",
            str(creds_file)
        )
        
        assert creds_file.exists()
        content = creds_file.read_text()
        assert "testuser@example.com" in content
        assert "testpassword123" in content
    
    def test_load_credentials(self, tmp_path):
        """Test loading credentials from file"""
        creds_file = tmp_path / "test_creds.csv"
        creds_file.write_text("user@test.com,mypassword")
        
        username, password = CredentialsManager.load_credentials(str(creds_file))
        
        assert username == "user@test.com"
        assert password == "mypassword"
    
    def test_load_credentials_with_quotes(self, tmp_path):
        """Test loading credentials with special characters"""
        creds_file = tmp_path / "test_creds.csv"
        creds_file.write_text('|user@test.com|,|pass,word|')
        
        username, password = CredentialsManager.load_credentials(str(creds_file))
        
        assert username == "user@test.com"
        assert password == "pass,word"
    
    def test_load_credentials_file_not_found(self):
        """Test loading from non-existent file"""
        with pytest.raises(FileNotFoundError):
            CredentialsManager.load_credentials("nonexistent.csv")
    
    def test_load_credentials_invalid_format(self, tmp_path):
        """Test loading from invalid file format"""
        creds_file = tmp_path / "invalid.csv"
        creds_file.write_text("onlyonevalue")
        
        with pytest.raises(ValueError):
            CredentialsManager.load_credentials(str(creds_file))
    
    def test_validate_credentials(self):
        """Test credential validation"""
        # Valid cases
        assert CredentialsManager.validate_credentials("user@example.com", "password123") == True
        assert CredentialsManager.validate_credentials("user", "password123") == True
        
        # Invalid cases
        assert CredentialsManager.validate_credentials("", "password") == False
        assert CredentialsManager.validate_credentials("user", "") == False
        assert CredentialsManager.validate_credentials("user", "short") == False  # Too short
        assert CredentialsManager.validate_credentials("user@", "password") == False  # Invalid email
        assert CredentialsManager.validate_credentials("@domain.com", "password") == False  # Invalid email
    
    @patch('builtins.input')
    @patch('getpass.getpass')
    def test_update_credentials(self, mock_getpass, mock_input, tmp_path):
        """Test interactive credential update"""
        creds_file = tmp_path / "creds.csv"
        
        # Mock user inputs
        mock_input.side_effect = ["newuser@example.com", "y"]
        mock_getpass.return_value = "newpassword123"
        
        result = CredentialsManager.update_credentials(str(creds_file))
        
        assert result == True
        assert creds_file.exists()
        
        # Verify saved credentials
        username, password = CredentialsManager.load_credentials(str(creds_file))
        assert username == "newuser@example.com"
        assert password == "newpassword123"
    
    @patch('builtins.input')
    def test_update_credentials_cancelled(self, mock_input, tmp_path):
        """Test cancelling credential update"""
        creds_file = tmp_path / "creds.csv"
        
        mock_input.side_effect = ["user@example.com", "n"]
        
        result = CredentialsManager.update_credentials(str(creds_file))
        
        assert result == False
        assert not creds_file.exists()
    
    def test_check_credentials_exist(self, tmp_path):
        """Test checking if credentials exist and are valid"""
        creds_file = tmp_path / "creds.csv"
        
        # File doesn't exist
        assert CredentialsManager.check_credentials_exist(str(creds_file)) == False
        
        # Valid credentials
        CredentialsManager.save_credentials("user@test.com", "password123", str(creds_file))
        assert CredentialsManager.check_credentials_exist(str(creds_file)) == True
        
        # Invalid credentials (too short password)
        creds_file.write_text("user@test.com,pass")
        assert CredentialsManager.check_credentials_exist(str(creds_file)) == False


class TestCredentialsEncryption:
    """Test CredentialsEncryption class"""
    
    def test_is_available(self):
        """Test checking if encryption is available"""
        # This will depend on whether cryptography is installed
        result = CredentialsEncryption.is_available()
        assert isinstance(result, bool)
    
    @patch('utilities.credentials.CredentialsEncryption.is_available')
    def test_encryption_not_available(self, mock_available):
        """Test encryption when cryptography is not available"""
        mock_available.return_value = False
        
        with pytest.raises(ImportError):
            CredentialsEncryption.generate_key()
        
        with pytest.raises(ImportError):
            CredentialsEncryption.encrypt_password("test", b"key")
        
        with pytest.raises(ImportError):
            CredentialsEncryption.decrypt_password(b"encrypted", b"key")
    
    def test_encryption_roundtrip(self):
        """Test encryption and decryption (if available)"""
        if not CredentialsEncryption.is_available():
            pytest.skip("cryptography package not installed")
        
        # Generate key
        key = CredentialsEncryption.generate_key()
        assert isinstance(key, bytes)
        
        # Encrypt password
        original = "mysecretpassword123"
        encrypted = CredentialsEncryption.encrypt_password(original, key)
        assert isinstance(encrypted, bytes)
        assert encrypted != original.encode()
        
        # Decrypt password
        decrypted = CredentialsEncryption.decrypt_password(encrypted, key)
        assert decrypted == original
