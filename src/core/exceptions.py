"""
Custom exceptions for Sports Connect Automation
"""


class SportsConnectError(Exception):
    """Base exception for Sports Connect automation"""
    pass


class ConfigurationError(SportsConnectError):
    """Raised when configuration is invalid or missing"""
    pass


class LoginError(SportsConnectError):
    """Raised when login fails"""
    pass


class ReportExportError(SportsConnectError):
    """Raised when report export fails"""
    pass


class ElementNotFoundError(SportsConnectError):
    """Raised when expected element is not found"""
    pass


class TimeoutError(SportsConnectError):
    """Raised when operation times out"""
    pass


class DownloadError(SportsConnectError):
    """Raised when file download fails"""
    pass


class WebDriverError(SportsConnectError):
    """Raised when WebDriver operations fail"""
    pass


class GoogleDriveError(SportsConnectError):
    """Raised when Google Drive operations fail"""
    pass


class AccessDatabaseError(SportsConnectError):
    """Raised when Access database operations fail"""
    pass


class ValidationError(SportsConnectError):
    """Raised when validation fails"""
    pass