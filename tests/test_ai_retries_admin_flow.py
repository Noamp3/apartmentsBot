import pytest
from unittest.mock import MagicMock, AsyncMock
from telegram import Update, User as TGUser, Chat as TGChat, CallbackQuery
from telegram.ext import ContextTypes

from database import get_db
from database.repositories import UserRepository
from bot.handlers.callback_handler import CallbackHandler
from bot.handlers.message_handler import MessageHandler
from models.user import User
from config import settings


@pytest.mark.asyncio
async def test_ai_retries_admin_flow(db, monkeypatch):
    # Patch get_db to return the in-memory test db
    async def mock_get_db():
        return db
    monkeypatch.setattr("bot.handlers.callback_handler.get_db", mock_get_db)
    monkeypatch.setattr("bot.handlers.message_handler.get_db", mock_get_db)
    monkeypatch.setattr("database.get_db", mock_get_db)

    admin_id = 999999999
    
    # 1. Clean up user if exists
    user_repo = UserRepository(db)
    if await user_repo.exists(admin_id):
        await user_repo.delete_user(admin_id)
        
    # 2. Create admin
    admin_obj = User(telegram_id=admin_id, chat_id=admin_id, username="test_admin", is_admin=True)
    await user_repo.create(admin_obj)
    
    # 3. Setup mock Update and CallbackQuery for callback
    callback_handler = CallbackHandler()
    
    effective_user_mock = MagicMock(spec=TGUser)
    effective_user_mock.id = admin_id
    effective_user_mock.username = "test_admin"
    
    effective_chat_mock = MagicMock(spec=TGChat)
    effective_chat_mock.id = admin_id
    
    cb_update_mock = MagicMock(spec=Update)
    cb_update_mock.effective_user = effective_user_mock
    cb_update_mock.effective_chat = effective_chat_mock
    
    query_mock = MagicMock(spec=CallbackQuery)
    query_mock.from_user = effective_user_mock
    query_mock.answer = AsyncMock()
    query_mock.edit_message_text = AsyncMock()
    query_mock.edit_message_reply_markup = AsyncMock()
    cb_update_mock.callback_query = query_mock
    
    admin_command_handler_mock = MagicMock()
    admin_command_handler_mock.get_admin_dashboard_data = AsyncMock(return_value=("dashboard", MagicMock()))
    context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context_mock.bot_data = {"ai_engine": None, "admin_command_handler": admin_command_handler_mock}
    context_mock.user_data = {}
    
    # Trigger AI test/settings callback
    query_mock.data = "admin_menu_gemini"
    await callback_handler.handle_callback(cb_update_mock, context_mock)
    
    # Verify display shows current retries
    assert query_mock.edit_message_text.called
    args = query_mock.edit_message_text.call_args[0]
    assert "ניסיונות חוזרים (AI Retries):" in args[0]
    
    # Trigger setting AI retries prompt
    query_mock.edit_message_text.reset_mock()
    query_mock.data = "admin_menu_change_retries_prompt"
    await callback_handler.handle_callback(cb_update_mock, context_mock)
    
    # Check that prompt was displayed and user_data flag set
    assert query_mock.edit_message_text.called
    assert context_mock.user_data.get("admin_waiting_for_ai_retries") is True
    
    # 4. Mock message update for MessageHandler
    message_handler = MessageHandler()
    
    msg_update_mock = MagicMock(spec=Update)
    msg_update_mock.effective_user = effective_user_mock
    msg_update_mock.effective_chat = effective_chat_mock
    msg_update_mock.message = MagicMock()
    msg_update_mock.message.text = "25"
    msg_update_mock.message.reply_text = AsyncMock()
    
    # Send retries value to MessageHandler
    await message_handler.handle_message(msg_update_mock, context_mock)
    
    # Check that settings updated
    assert settings.GEMINI_503_RETRIES == 25
    assert msg_update_mock.message.reply_text.called
    reply_args = msg_update_mock.message.reply_text.call_args_list[0][0][0]
    assert "כמות הניסיונות החוזרים של AI עודכנה ל-25 בהצלחה!" in reply_args
    assert context_mock.user_data.get("admin_waiting_for_ai_retries") is None
    
    # Send invalid value
    context_mock.user_data["admin_waiting_for_ai_retries"] = True
    msg_update_mock.message.text = "invalid_number"
    await message_handler.handle_message(msg_update_mock, context_mock)
    
    # Check warning and that it put admin back in waiting state
    assert context_mock.user_data.get("admin_waiting_for_ai_retries") is True
    reply_args_invalid = msg_update_mock.message.reply_text.call_args_list[2][0][0]
    assert "ערך לא תקין" in reply_args_invalid

    # Send value outside range
    msg_update_mock.message.text = "99"
    await message_handler.handle_message(msg_update_mock, context_mock)
    assert context_mock.user_data.get("admin_waiting_for_ai_retries") is True

    # Cancel setting
    msg_update_mock.message.text = "ביטול"
    await message_handler.handle_message(msg_update_mock, context_mock)
    assert context_mock.user_data.get("admin_waiting_for_ai_retries") is None
    
    # Cleanup
    await user_repo.delete_user(admin_id)
