"""Debug script to check actual config values."""
from config import settings

print("=== Current Configuration Values ===")
print(f"RESET_DB_ON_STARTUP: {settings.RESET_DB_ON_STARTUP}")
print(f"RESET_USERS_ON_STARTUP: {settings.RESET_USERS_ON_STARTUP}")
print(f"RESET_PERSONA_CACHE_ON_STARTUP: {settings.RESET_PERSONA_CACHE_ON_STARTUP}")
