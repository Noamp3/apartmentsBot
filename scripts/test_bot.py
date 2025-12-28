# scripts/test_bot.py
"""Standalone script to test the Telegram bot without scrapers."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from utils.logger import LoggerFactory
from database import get_db
from bot import ApartmentBot
from core.ai_engine import create_ai_engine


async def test_bot_polling():
    """Test bot in polling mode (interactive)."""
    print("\n" + "="*50)
    print("🤖 Testing Telegram Bot (Polling Mode)")
    print("="*50)
    
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        print("\n❌ TELEGRAM_BOT_TOKEN not configured in .env")
        print("   Get a token from @BotFather on Telegram")
        return
    
    # Initialize database
    db = await get_db()
    print("✅ Database initialized")
    
    # Initialize AI engine (optional for bot testing)
    ai_engine = None
    if settings.active_api_key:
        try:
            ai_engine = create_ai_engine()
            print(f"✅ AI engine initialized ({settings.AI_PROVIDER.value})")
        except Exception as e:
            print(f"⚠️ AI engine failed: {e} (bot will work without AI)")
    
    # Create and start bot
    bot = ApartmentBot(ai_engine=ai_engine)
    await bot.setup()
    print("✅ Bot initialized")
    
    print("\n📱 Bot is now running!")
    print("   Open Telegram and message your bot")
    print("   Commands to try:")
    print("   • /start - Get welcome message")
    print("   • /help - Show help")
    print("   • /rules - Show your rules")
    print("   • Send any text - Add a search rule")
    print("\n   Press Ctrl+C to stop\n")
    
    try:
        await bot.run()
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n⏹️ Stopping bot...")
        await bot.stop()
        print("✅ Bot stopped")


async def test_bot_send_message():
    """Test sending a message to yourself."""
    print("\n" + "="*50)
    print("📤 Testing Bot Message Sending")
    print("="*50)
    
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        print("\n❌ TELEGRAM_BOT_TOKEN not configured")
        return
    
    chat_id = input("\n  Enter your Telegram chat ID (or press Enter to skip): ").strip()
    
    if not chat_id:
        print("  Skipped. To get your chat ID:")
        print("  1. Message your bot with /start")
        print("  2. The chat ID will be logged")
        return
    
    try:
        chat_id = int(chat_id)
    except ValueError:
        print("  ❌ Invalid chat ID (must be a number)")
        return
    
    bot = ApartmentBot()
    await bot.setup()
    
    # Start the application properly
    await bot.application.initialize()
    await bot.application.start()
    
    await bot.send_message(chat_id, "🏠 Test message from Apartment Bot!")
    print(f"  ✅ Message sent to chat {chat_id}")
    
    await bot.application.stop()
    await bot.application.shutdown()


async def main():
    """Run bot tests."""
    LoggerFactory.initialize(debug=True)
    
    print("\n🏠 Apartment Bot - Bot Test")
    print("============================\n")
    
    print("Select test mode:")
    print("  1. Run bot in polling mode (interactive)")
    print("  2. Send a test message")
    print("  3. Exit")
    
    choice = input("\nChoice (1-3): ").strip()
    
    if choice == "1":
        await test_bot_polling()
    elif choice == "2":
        await test_bot_send_message()
    else:
        print("Exiting.")


if __name__ == "__main__":
    asyncio.run(main())
