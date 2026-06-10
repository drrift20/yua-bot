"""
Improved logging module for Yua Bot with sensitive data masking.
"""
import logging
import os
from typing import Optional

class SensitiveDataFilter(logging.Filter):
    """Filter to mask API keys and sensitive data in logs."""
    
    def __init__(self):
        super().__init__()
        self.sensitive_keys = {
            "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
            "GEMINI_API_KEY_2": os.getenv("GEMINI_API_KEY_2", ""),
            "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
            "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN", ""),
            "MONGO_URI": os.getenv("MONGO_URI", ""),
        }
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Mask sensitive data in log records."""
        msg = record.getMessage()
        
        for key_name, key_value in self.sensitive_keys.items():
            if key_value and key_value in msg:
                msg = msg.replace(key_value, f"***{key_name[:8]}***")
        
        record.msg = msg
        record.args = ()
        return True


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """
    Setup logger with sensitive data filtering.
    
    Args:
        name: Logger name (usually __name__)
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Console handler
    handler = logging.StreamHandler()
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - [%(levelname)s] - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # Add sensitive data filter
    handler.addFilter(SensitiveDataFilter())
    
    logger.addHandler(handler)
    return logger
