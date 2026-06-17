# tests/conftest.py
"""Pytest fixtures for apartment bot tests."""

# Patch platform._wmi_query to avoid hangs on Windows environments with broken WMI
import sys
if sys.platform == "win32":
    try:
        import platform
        platform._wmi_query = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("WMI disabled"))
    except Exception:
        pass

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


def pytest_addoption(parser):
    parser.addoption(
        "--run-llm", action="store_true", default=False, help="run tests that call live LLM APIs"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-llm"):
        return
    
    skip_llm = pytest.mark.skip(reason="requires --run-llm to run")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip_llm)





