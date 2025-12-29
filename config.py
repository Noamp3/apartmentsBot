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
    # Comma-separated list of models to rotate through. First one is primary.
    GEMINI_MODEL: str = "gemini-3-flash-preview,gemini-2.0-flash-exp,gemini-1.5-flash,gemini-1.5-flash-8b,gemini-1.5-pro"
    
    # OpenAI Settings
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    
    # Anthropic Settings
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-haiku-20240307"
    
    # Ollama Settings (local models)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    
    LOG_LEVEL: str = "INFO"
    RESET_DB_ON_STARTUP: bool = False  # Resets listings, rejections, and seen history
    RESET_USERS_ON_STARTUP: bool = False # Resets users AND their search rules
    RESET_PERSONA_CACHE_ON_STARTUP: bool = False # Resets AI generated welcome/sass cache
    
    # Database
    DATABASE_URL: str = "sqlite:///data/apartments.db"
    
    # Scraping Settings
    SCRAPE_INTERVAL_MINUTES: int = 15
    SCRAPE_JITTER_SECONDS: int = 120
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
    def gemini_models(self) -> List[str]:
        """Parse Gemini models from comma-separated string."""
        if not self.GEMINI_MODEL:
            return []
        return [m.strip() for m in self.GEMINI_MODEL.split(",") if m.strip()]
    
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
        """Get the primary model name for the active provider."""
        models = {
            AIProvider.GEMINI: self.gemini_models[0] if self.gemini_models else "",
            AIProvider.OPENAI: self.OPENAI_MODEL,
            AIProvider.ANTHROPIC: self.ANTHROPIC_MODEL,
            AIProvider.OLLAMA: self.OLLAMA_MODEL,
        }
        return models.get(self.AI_PROVIDER, "")
    
    # Rate Limiting
    # Gemini free tier: RPM limits vary by model, typically 10-15 RPM
    # Gemini 3 Flash Preview free tier: 20 RPD limit usually applies to paid/free distinction but user specifically requested 20 RPD.
    GEMINI_RPM_LIMIT: int = 10 
    GEMINI_DAILY_LIMIT: int = 20  # As requested by user
    OPENAI_RPM_LIMIT: int = 60
    ANTHROPIC_RPM_LIMIT: int = 60
    RATE_LIMIT_SAFETY_MARGIN: float = 1.0  # Trust exact numbers for now
    
    @property
    def AI_RATE_LIMIT(self) -> int:
        """Get rate limit for active provider."""
        limits = {
            AIProvider.GEMINI: self.GEMINI_RPM_LIMIT,
            AIProvider.OPENAI: self.OPENAI_RPM_LIMIT,
            AIProvider.ANTHROPIC: self.ANTHROPIC_RPM_LIMIT,
            AIProvider.OLLAMA: 100,  # High limit for local
        }
        return int(limits.get(self.AI_PROVIDER, 10))
    
    # Batch Processing (prompt batching, NOT Batch API - works on free tier)
    # This controls how many listings we include in a single prompt
    AI_BATCH_SIZE: int = 50
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

