import pytest
import logging
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock
from database import get_db
from database.repositories import UserRepository
from models.user import User
from utils.admin_notifier import TelegramAdminNotificationHandler

class MockBot:
    def __init__(self):
        self.application = MagicMock()
        self.application.bot = MagicMock()
        self.application.bot.send_message = AsyncMock()

@pytest.mark.asyncio
async def test_admin_notifier_success(db, monkeypatch):
    # Patch database retrieval
    async def mock_get_db():
        return db
    monkeypatch.setattr("database.get_db", mock_get_db)
    
    # Register an admin user in the database
    user_repo = UserRepository(db)
    admin_id = 999999999
    admin_user = User(telegram_id=admin_id, chat_id=admin_id, username="admin_user", is_admin=True)
    await user_repo.create(admin_user)
    
    # Initialize mock bot and handler
    mock_bot = MockBot()
    handler = TelegramAdminNotificationHandler()
    handler.set_bot(mock_bot)
    
    # Create an error record
    logger = logging.getLogger("test_logger")
    record = logger.makeRecord(
        name="test_logger",
        level=logging.ERROR,
        fn="test_file.py",
        lno=42,
        msg="Something went terribly wrong!",
        args=(),
        exc_info=None
    )
    
    # Emit and await a short duration for the async task to run
    handler.emit(record)
    await asyncio.sleep(0.1)
    
    # Verify the message was sent to the admin
    mock_bot.application.bot.send_message.assert_called_once()
    args, kwargs = mock_bot.application.bot.send_message.call_args
    assert kwargs["chat_id"] == admin_id
    assert "Something went terribly wrong!" in kwargs["text"]
    assert kwargs["parse_mode"] == "HTML"

@pytest.mark.asyncio
async def test_admin_notifier_rate_limiting(db, monkeypatch):
    async def mock_get_db():
        return db
    monkeypatch.setattr("database.get_db", mock_get_db)
    
    user_repo = UserRepository(db)
    admin_id = 999999998
    admin_user = User(telegram_id=admin_id, chat_id=admin_id, username="admin_user_2", is_admin=True)
    await user_repo.create(admin_user)
    
    mock_bot = MockBot()
    handler = TelegramAdminNotificationHandler()
    handler.set_bot(mock_bot)
    
    # Emit 10 logs in rapid succession
    logger = logging.getLogger("test_logger")
    for i in range(10):
        record = logger.makeRecord(
            name="test_logger",
            level=logging.ERROR,
            fn="test_file.py",
            lno=10 + i,
            msg=f"Error number {i}",
            args=(),
            exc_info=None
        )
        handler.emit(record)
        
    await asyncio.sleep(0.1)
    
    # Verify exactly 5 messages were sent due to rate limiting
    assert mock_bot.application.bot.send_message.call_count == 5

@pytest.mark.asyncio
async def test_admin_notifier_recursion_protection(db, monkeypatch):
    async def mock_get_db():
        return db
    monkeypatch.setattr("database.get_db", mock_get_db)
    
    user_repo = UserRepository(db)
    admin_id = 999999997
    admin_user = User(telegram_id=admin_id, chat_id=admin_id, username="admin_user_3", is_admin=True)
    await user_repo.create(admin_user)
    
    mock_bot = MockBot()
    handler = TelegramAdminNotificationHandler()
    handler.set_bot(mock_bot)
    
    # Emit a record from the notifier logger itself
    logger = logging.getLogger("apt_bot.admin_notifier")
    record = logger.makeRecord(
        name="apt_bot.admin_notifier",
        level=logging.ERROR,
        fn="admin_notifier.py",
        lno=100,
        msg="Error inside the notifier",
        args=(),
        exc_info=None
    )
    handler.emit(record)
    
    # Emit a record with _from_notifier attribute set
    logger2 = logging.getLogger("test_logger")
    record2 = logger2.makeRecord(
        name="test_logger",
        level=logging.ERROR,
        fn="test_file.py",
        lno=200,
        msg="Fake notifier error",
        args=(),
        exc_info=None
    )
    record2._from_notifier = True
    handler.emit(record2)
    
    await asyncio.sleep(0.1)
    
    # Verify no messages were sent
    assert mock_bot.application.bot.send_message.call_count == 0
