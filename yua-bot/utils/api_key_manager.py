"""
API Key Manager for Yua Bot - Handles key rotation, tracking, and fallback logic.
"""
import os
from dataclasses import dataclass
from typing import Optional
from enum import Enum
from yua_bot.utils.logger import setup_logger

logger = setup_logger(__name__)


class APIProvider(Enum):
    """Available AI API providers."""
    GEMINI_1 = "gemini_1"
    GEMINI_2 = "gemini_2"
    GROQ = "groq"


@dataclass
class APIKeyStats:
    """Statistics for API key usage and failures."""
    provider: APIProvider
    success_count: int = 0
    failure_count: int = 0
    rate_limit_count: int = 0
    last_status: Optional[str] = None
    
    def __str__(self) -> str:
        return (
            f"{self.provider.value}: "
            f"✓{self.success_count} ✗{self.failure_count} "
            f"(Rate-limit: {self.rate_limit_count})"
        )


class APIKeyManager:
    """
    Manages API keys with rotation, tracking, and fallback logic.
    
    Handles:
    - Loading keys from environment variables
    - Tracking key usage and failures
    - Intelligent fallback strategy
    - Rate limit detection
    """
    
    def __init__(self):
        """Initialize API Key Manager."""
        self.key1 = os.getenv("GEMINI_API_KEY")
        self.key2 = os.getenv("GEMINI_API_KEY_2")
        self.groq_key = os.getenv("GROQ_API_KEY")
        
        # Validate at least one key exists
        if not self.key1:
            raise ValueError(
                "❌ GEMINI_API_KEY is required in environment variables. "
                "Please set it in Replit Secrets or .env file."
            )
        
        # Initialize statistics
        self.stats = {
            APIProvider.GEMINI_1: APIKeyStats(APIProvider.GEMINI_1),
            APIProvider.GEMINI_2: APIKeyStats(APIProvider.GEMINI_2) if self.key2 else None,
            APIProvider.GROQ: APIKeyStats(APIProvider.GROQ) if self.groq_key else None,
        }
        
        # Log initialization
        gemini_count = sum(1 for k in [self.key1, self.key2] if k)
        logger.info(
            f"✓ API Manager initialized: "
            f"{gemini_count} Gemini key(s), "
            f"Groq: {'Yes' if self.groq_key else 'No'}"
        )
    
    def get_available_providers(self) -> list:
        """Get list of available providers in fallback order."""
        providers = [APIProvider.GEMINI_1]
        
        if self.key2 and self.key2 != self.key1:
            providers.append(APIProvider.GEMINI_2)
        
        if self.groq_key:
            providers.append(APIProvider.GROQ)
        
        return providers
    
    def record_success(self, provider: APIProvider) -> None:
        """Record successful API call."""
        if provider in self.stats and self.stats[provider]:
            self.stats[provider].success_count += 1
            self.stats[provider].last_status = "SUCCESS"
            logger.debug(f"[{provider.value}] Success recorded. {self.stats[provider]}")
    
    def record_rate_limit(self, provider: APIProvider) -> None:
        """Record rate limit error (429)."""
        if provider in self.stats and self.stats[provider]:
            self.stats[provider].rate_limit_count += 1
            self.stats[provider].failure_count += 1
            self.stats[provider].last_status = "RATE_LIMIT"
            logger.warning(
                f"[{provider.value}] Rate limit hit. Total: {self.stats[provider].rate_limit_count}. "
                f"Switching to fallback..."
            )
    
    def record_failure(self, provider: APIProvider, reason: str = "UNKNOWN") -> None:
        """Record API failure."""
        if provider in self.stats and self.stats[provider]:
            self.stats[provider].failure_count += 1
            self.stats[provider].last_status = reason
            logger.warning(f"[{provider.value}] Failed ({reason}). {self.stats[provider]}")
    
    def record_suspension(self, provider: APIProvider) -> None:
        """Record key suspension (403 PERMISSION_DENIED)."""
        if provider in self.stats and self.stats[provider]:
            self.stats[provider].last_status = "SUSPENDED"
            logger.error(f"[{provider.value}] ⚠️ KEY SUSPENDED - Remove from secrets!")
            self.stats[provider].failure_count += 999  # Mark as unusable
    
    def get_stats_summary(self) -> str:
        """Get formatted statistics summary."""
        summary_lines = ["📊 API Usage Statistics:"]
        for provider, stats in self.stats.items():
            if stats:
                summary_lines.append(f"  {stats}")
        return "\n".join(summary_lines)
    
    def should_use_provider(self, provider: APIProvider) -> bool:
        """Check if provider should still be attempted."""
        if provider not in self.stats or not self.stats[provider]:
            return False
        
        stats = self.stats[provider]
        # If suspended, don't use
        if stats.last_status == "SUSPENDED":
            return False
        
        return True


# Global instance (initialize after environment is ready)
_api_key_manager: Optional[APIKeyManager] = None


def get_api_key_manager() -> APIKeyManager:
    """Get or create the global API Key Manager instance."""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager()
    return _api_key_manager
