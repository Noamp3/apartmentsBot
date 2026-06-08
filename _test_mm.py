
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

@pytest.mark.asyncio
async def test_patch_return_value():
    mock_db = MagicMock()
    print('starting test...')
    with patch('database.get_db', return_value=mock_db):
        from database import get_db
        print('calling get_db...')
        result = get_db()
        print('got result:', type(result))
        r = await result
        print('awaited result:', type(r))
