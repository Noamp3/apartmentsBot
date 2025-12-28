# database/__init__.py
"""Database layer for the apartment search bot."""

from database.connection import DatabaseManager, get_db

__all__ = [
    "DatabaseManager",
    "get_db",
]
