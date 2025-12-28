# database/repositories/rule_repository.py
"""Repository for search rule operations."""

from datetime import datetime
from typing import List, Optional

from database.connection import DatabaseManager
from models.search_rule import SearchRule, RuleType


class RuleRepository:
    """Handles CRUD operations for search rules."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def create(self, rule: SearchRule) -> SearchRule:
        """Create a new search rule."""
        rule_id = await self.db.execute(
            """
            INSERT INTO search_rules (user_id, rule_type, value, original_text, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (rule.user_id, rule.rule_type.value, rule.value, 
             rule.original_text, rule.is_active, rule.created_at.isoformat())
        )
        rule.id = rule_id
        return rule
    
    async def get_user_rules(self, user_id: int, active_only: bool = True) -> List[SearchRule]:
        """Get all rules for a user."""
        if active_only:
            rows = await self.db.fetch_all(
                "SELECT * FROM search_rules WHERE user_id = ? AND is_active = TRUE ORDER BY created_at",
                (user_id,)
            )
        else:
            rows = await self.db.fetch_all(
                "SELECT * FROM search_rules WHERE user_id = ? ORDER BY created_at",
                (user_id,)
            )
        return [self._row_to_rule(row) for row in rows]
    
    async def get_by_id(self, rule_id: int) -> Optional[SearchRule]:
        """Get a rule by ID."""
        row = await self.db.fetch_one(
            "SELECT * FROM search_rules WHERE id = ?",
            (rule_id,)
        )
        if row:
            return self._row_to_rule(row)
        return None
    
    async def update(self, rule: SearchRule):
        """Update an existing rule."""
        await self.db.execute(
            """
            UPDATE search_rules 
            SET rule_type = ?, value = ?, original_text = ?, is_active = ?
            WHERE id = ?
            """,
            (rule.rule_type.value, rule.value, rule.original_text, 
             rule.is_active, rule.id)
        )
    
    async def delete(self, rule_id: int):
        """Delete a rule (soft delete by setting inactive)."""
        await self.db.execute(
            "UPDATE search_rules SET is_active = FALSE WHERE id = ?",
            (rule_id,)
        )
    
    async def delete_all_user_rules(self, user_id: int):
        """Delete all rules for a user."""
        await self.db.execute(
            "UPDATE search_rules SET is_active = FALSE WHERE user_id = ?",
            (user_id,)
        )
    
    async def get_rules_by_type(self, user_id: int, rule_type: RuleType) -> List[SearchRule]:
        """Get rules of a specific type for a user."""
        rows = await self.db.fetch_all(
            """
            SELECT * FROM search_rules 
            WHERE user_id = ? AND rule_type = ? AND is_active = TRUE
            """,
            (user_id, rule_type.value)
        )
        return [self._row_to_rule(row) for row in rows]
    
    def _row_to_rule(self, row) -> SearchRule:
        """Convert a database row to SearchRule object."""
        return SearchRule(
            id=row["id"],
            user_id=row["user_id"],
            rule_type=RuleType(row["rule_type"]),
            value=row["value"],
            original_text=row["original_text"] or "",
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
        )
