# tests/conftest.py
"""Pytest fixtures for apartment bot tests."""

import pytest
import pytest_asyncio
import asyncio


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db():
    """Create a test database."""
    from database.connection import DatabaseManager
    
    db_manager = DatabaseManager(db_url="sqlite:///:memory:")
    await db_manager.initialize()
    yield db_manager
    await db_manager.close()
