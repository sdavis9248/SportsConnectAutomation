"""
Logging configuration for Sports Connect Automation
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

def setup_logging(log_level: str = "INFO", log_dir: str = "logs", 
                 console_output: bool = True, file_output: bool = True) -> logging.Logger:
    """Set up logging configuration"""
    # Create log directory
    Path(log_dir).mkdir(exist_ok=True)
    
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Console handler with UTF-8 encoding
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
        # Force UTF-8 encoding for console output
        if hasattr(console_handler.stream, 'reconfigure'):
            console_handler.stream.reconfigure(encoding='utf-8')
        logger.addHandler(console_handler)
    
    # File handler - main log (already handles UTF-8 by default)
    if file_output:
        log_file = os.path.join(log_dir, f"sports_connect_{datetime.now().strftime('%Y%m%d')}.log")
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'  # Explicitly set UTF-8 encoding
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        logger.addHandler(file_handler)
        
        # Error log handler
        error_file = os.path.join(log_dir, "errors.log")
        error_handler = RotatingFileHandler(
            error_file,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3,
            encoding='utf-8'  # Explicitly set UTF-8 encoding
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)
        logger.addHandler(error_handler)
    
    # Log startup message
    logger.info("="*60)
    logger.info("Sports Connect Automation Started")
    logger.info(f"Log Level: {log_level}")
    logger.info(f"Log Directory: {os.path.abspath(log_dir)}")
    logger.info("="*60)
    
    return logger

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module"""
    return logging.getLogger(name)


class LogContext:
    """Context manager for logging operations"""
    
    def __init__(self, operation: str, logger: logging.Logger = None):
        self.operation = operation
        self.logger = logger or logging.getLogger()
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.info(f"Starting: {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds()
        
        if exc_type:
            self.logger.error(f"Failed: {self.operation} after {duration:.2f}s - {exc_val}")
        else:
            self.logger.info(f"Completed: {self.operation} in {duration:.2f}s")
        
        return False  # Don't suppress exceptions
