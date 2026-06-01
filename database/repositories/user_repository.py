# database/repositories/user_repository.py
"""Repository for user data operations."""

from datetime import datetime
from typing import List, Optional

from database.connection import DatabaseManager
from models.user import User


class UserRepository:
    """Handles CRUD operations for users."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def create(self, user: User) -> User:
        """Create a new user record."""
        await self.db.execute(
            """
            INSERT OR REPLACE INTO users (telegram_id, chat_id, username, created_at, is_active, first_notified_at, persona, is_admin, onboarding_step, allow_bordering_neighborhoods)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user.telegram_id, user.chat_id, user.username, 
             user.created_at.isoformat(), user.is_active,
             user.first_notified_at.isoformat() if user.first_notified_at else None,
             user.persona, user.is_admin, user.onboarding_step, user.allow_bordering_neighborhoods)
        )
        return user
    
    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get a user by their Telegram ID."""
        row = await self.db.fetch_one(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        if row:
            return self._row_to_user(row)
        return None
    
    async def get_by_chat_id(self, chat_id: int) -> Optional[User]:
        """Get a user by their Chat ID."""
        row = await self.db.fetch_one(
            "SELECT * FROM users WHERE chat_id = ?",
            (chat_id,)
        )
        if row:
            return self._row_to_user(row)
        return None
    
    async def get_all_active(self) -> List[User]:
        """Get all active users."""
        rows = await self.db.fetch_all(
            "SELECT * FROM users WHERE is_active = TRUE"
        )
        return [self._row_to_user(row) for row in rows]
    
    async def update_active_status(self, telegram_id: int, is_active: bool):
        """Update a user's active status."""
        await self.db.execute(
            "UPDATE users SET is_active = ? WHERE telegram_id = ?",
            (is_active, telegram_id)
        )
    
    async def exists(self, telegram_id: int) -> bool:
        """Check if a user exists."""
        row = await self.db.fetch_one(
            "SELECT 1 FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        return row is not None
    
    async def get_or_create(self, telegram_id: int, chat_id: int, 
                           username: Optional[str] = None) -> User:
        """Get existing user or create new one."""
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            return user
        
        # Check if this is the first user in the database
        row = await self.db.fetch_one("SELECT COUNT(*) as count FROM users")
        is_first_user = row["count"] == 0 if row else True
        
        new_user = User(
            telegram_id=telegram_id,
            chat_id=chat_id,
            username=username,
            is_admin=is_first_user,
            onboarding_step="choose_persona"  # Setup onboarding for new users
        )
        return await self.create(new_user)
    
    def _row_to_user(self, row) -> User:
        """Convert a database row to User object."""
        first_notified = row.get("first_notified_at") if hasattr(row, 'get') else None
        try:
            first_notified = row["first_notified_at"]
        except (KeyError, IndexError):
            first_notified = None
            
        persona = "barakush"
        try:
            persona = row["persona"] or "barakush"
        except (KeyError, IndexError, TypeError):
            pass
            
        is_admin = False
        try:
            is_admin = bool(row["is_admin"])
        except (KeyError, IndexError, TypeError):
            pass
            
        onboarding_step = None
        try:
            onboarding_step = row["onboarding_step"]
        except (KeyError, IndexError, TypeError):
            pass
            
        allow_bordering = True
        try:
            allow_bordering = bool(row["allow_bordering_neighborhoods"])
        except (KeyError, IndexError, TypeError):
            pass
            
        return User(
            telegram_id=row["telegram_id"],
            chat_id=row["chat_id"],
            username=row["username"],
            created_at=row["created_at"],
            is_active=bool(row["is_active"]),
            first_notified_at=first_notified,
            persona=persona,
            is_admin=is_admin,
            onboarding_step=onboarding_step,
            allow_bordering_neighborhoods=allow_bordering,
        )
        
    async def update_persona(self, telegram_id: int, persona: str):
        """Update a user's selected persona."""
        await self.db.execute(
            "UPDATE users SET persona = ? WHERE telegram_id = ?",
            (persona, telegram_id)
        )
        
    async def update_onboarding_step(self, telegram_id: int, onboarding_step: Optional[str]):
        """Update a user's onboarding step."""
        await self.db.execute(
            "UPDATE users SET onboarding_step = ? WHERE telegram_id = ?",
            (onboarding_step, telegram_id)
        )
        
    async def update_allow_bordering(self, telegram_id: int, allow_bordering: bool):
        """Update a user's bordering neighborhood preference."""
        await self.db.execute(
            "UPDATE users SET allow_bordering_neighborhoods = ? WHERE telegram_id = ?",
            (allow_bordering, telegram_id)
        )
    
    async def mark_first_notification(self, telegram_id: int):
        """Mark that user received their first notification."""
        await self.db.execute(
            """
            UPDATE users SET first_notified_at = ? 
            WHERE telegram_id = ? AND first_notified_at IS NULL
            """,
            (datetime.now().isoformat(), telegram_id)
        )
    
    async def delete_user(self, telegram_id: int):
        """Delete user and all associated data."""
        # Delete related data manually first (since no CASCADE on foreign keys)
        await self.db.execute("DELETE FROM search_rules WHERE user_id = ?", (telegram_id,))
        await self.db.execute("DELETE FROM rejection_logs WHERE user_id = ?", (telegram_id,))
        await self.db.execute("DELETE FROM sent_notifications WHERE user_id = ?", (telegram_id,))
        
        # Delete the user
        await self.db.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
