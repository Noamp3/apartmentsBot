# config.py
"""Configuration management using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional, Literal
from functools import lru_cache
from enum import Enum


class AIProvider(str, Enum):
    """Supported AI providers."""
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"  # For local models


class GeminiModel(str, Enum):
    """Available Gemini models."""
    GEMINI_3_FLASH = "gemini-3-flash-preview"  # Latest, recommended for free tier
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_FLASH = "gemini-2.0-flash"
    GEMINI_1_5_FLASH = "gemini-1.5-flash"
    GEMINI_1_5_PRO = "gemini-1.5-pro"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    
    # AI Provider Configuration
    AI_PROVIDER: AIProvider = AIProvider.GEMINI
    
    # Gemini Settings
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3-flash-preview"  # Free tier model
    
    # OpenAI Settings
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    
    # Anthropic Settings
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-haiku-20240307"
    
    # Ollama Settings (local models)
    # Ollama Settings (local models)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    
    LOG_LEVEL: str = "INFO"
    RESET_DB_ON_STARTUP: bool = True  # Resets listings, rejections, and seen history
    RESET_USERS_ON_STARTUP: bool = False # Resets users AND their search rules
    
    # Database
    DATABASE_URL: str = "sqlite:///data/apartments.db"
    
    # Scraping Settings
    SCRAPE_INTERVAL_MINUTES: int = 7
    MIN_DELAY_SECONDS: float = 1.0
    MAX_DELAY_SECONDS: float = 5.0
    
    # Facebook Group URLs (comma-separated in .env)
    FACEBOOK_GROUP_URLS: str = ""
    
    # Facebook Login (required for group access)
    FACEBOOK_EMAIL: str = ""
    FACEBOOK_PASSWORD: str = ""
    
    # Debug Mode
    DEBUG: bool = True
    
    @property
    def facebook_groups(self) -> List[str]:
        """Parse Facebook group URLs from comma-separated string."""
        if not self.FACEBOOK_GROUP_URLS:
            return []
        return [url.strip() for url in self.FACEBOOK_GROUP_URLS.split(",") if url.strip()]
    
    @property
    def active_api_key(self) -> str:
        """Get the API key for the active provider."""
        keys = {
            AIProvider.GEMINI: self.GEMINI_API_KEY,
            AIProvider.OPENAI: self.OPENAI_API_KEY,
            AIProvider.ANTHROPIC: self.ANTHROPIC_API_KEY,
            AIProvider.OLLAMA: "",  # Ollama doesn't need an API key
        }
        return keys.get(self.AI_PROVIDER, "")
    
    @property
    def active_model(self) -> str:
        """Get the model name for the active provider."""
        models = {
            AIProvider.GEMINI: self.GEMINI_MODEL,
            AIProvider.OPENAI: self.OPENAI_MODEL,
            AIProvider.ANTHROPIC: self.ANTHROPIC_MODEL,
            AIProvider.OLLAMA: self.OLLAMA_MODEL,
        }
        return models.get(self.AI_PROVIDER, "")
    
    # Rate Limiting
    # Gemini free tier: RPM limits vary by model, typically 10-15 RPM
    # Gemini 3 Flash Preview free tier: No explicit daily limit, but usage may be throttled
    # For paid tier, limits are much higher
    GEMINI_RPM_LIMIT: int = 10  # Conservative for free tier
    GEMINI_DAILY_LIMIT: int = 1500  # Soft limit for free tier (may not apply to Gemini 3)
    OPENAI_RPM_LIMIT: int = 60
    ANTHROPIC_RPM_LIMIT: int = 60
    RATE_LIMIT_SAFETY_MARGIN: float = 0.9
    
    # Batch Processing (prompt batching, NOT Batch API - works on free tier)
    # This controls how many listings we include in a single prompt
    AI_BATCH_SIZE: int = 30
    AI_CALLS_PER_CYCLE_BUDGET: int = 7
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience access
settings = get_settings()

