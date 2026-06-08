import pytest
from unittest.mock import MagicMock, AsyncMock
from telegram import Update, User as TGUser, Chat as TGChat
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository
from bot.handlers.command_handler import CommandHandler

@pytest.mark.asyncio
async def test_auto_registration_command(db, monkeypatch):
    import database.connection
    monkeypatch.setattr(database.connection, "_db_manager", db)
    
    user_repo = UserRepository(db)
    
    # 1. Clean up user if they exist
    test_user_id = 123456789
    if await user_repo.exists(test_user_id):
        await user_repo.delete_user(test_user_id)
        
    # Verify user does not exist in db
    assert not await user_repo.exists(test_user_id)
    
    # 2. Setup mock Update and Context
    update_mock = MagicMock(spec=Update)
    effective_user_mock = MagicMock(spec=TGUser)
    effective_user_mock.id = test_user_id
    effective_user_mock.username = "test_auto_user"
    effective_user_mock.first_name = "Test"
    effective_chat_mock = MagicMock(spec=TGChat)
    effective_chat_mock.id = test_user_id
    
    update_mock.effective_user = effective_user_mock
    update_mock.effective_chat = effective_chat_mock
    
    # Mock reply_text on message
    message_mock = MagicMock()
    message_mock.reply_text = AsyncMock()
    update_mock.message = message_mock
    
    context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context_mock.bot_data = {"ai_engine": None, "processing_service": None}
    
    # 3. Call help command (which is decorated with @ensure_user_exists)
    handler = CommandHandler()
    await handler.help(update_mock, context_mock)
    
    # 4. Verify user was automatically registered in database!
    assert await user_repo.exists(test_user_id)
    
    # Check details
    user = await user_repo.get_by_telegram_id(test_user_id)
    assert user is not None
    assert user.username == "test_auto_user"
    assert user.chat_id == test_user_id
    
    # Clean up
    await user_repo.delete_user(test_user_id)
