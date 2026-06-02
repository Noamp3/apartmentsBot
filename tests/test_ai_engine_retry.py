# tests/test_ai_engine_retry.py
"""Tests for safe non-rate-limit retry mechanism in AI engines."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from core.ai_engine import (
    retry_with_backoff,
    GeminiAIEngine,
    OpenAIEngine,
    AnthropicEngine,
    GroqEngine,
    OllamaEngine,
    RateLimiter
)

# A generic exception class with a status code
class MockAPIError(Exception):
    def __init__(self, message, code=None, status_code=None, status=None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.status = status


@pytest.mark.asyncio
async def test_retry_with_backoff_success():
    """Test retry_with_backoff succeeds on first try."""
    mock_func = AsyncMock(return_value="success_data")
    
    result = await retry_with_backoff(mock_func, "arg1", max_retries=3, base_delay=0.01)
    
    assert result == "success_data"
    mock_func.assert_called_once_with("arg1")


@pytest.mark.asyncio
async def test_retry_with_backoff_transient_retry():
    """Test retry_with_backoff retries on transient error and succeeds."""
    call_count = 0
    
    async def mock_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise MockAPIError("Transient server error", code=500)
        return "recovered"

    result = await retry_with_backoff(mock_func, max_retries=3, base_delay=0.01)
    
    assert result == "recovered"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_with_backoff_exhausted():
    """Test retry_with_backoff raises exception if retries are exhausted."""
    mock_func = AsyncMock(side_effect=MockAPIError("Continuous server error", code=503))
    
    with pytest.raises(MockAPIError) as exc_info:
        await retry_with_backoff(mock_func, max_retries=3, base_delay=0.01)
        
    assert "Continuous server error" in str(exc_info.value)
    assert mock_func.call_count == 3


@pytest.mark.asyncio
async def test_retry_with_backoff_non_retriable():
    """Test retry_with_backoff fails immediately on non-retriable error (e.g. 400)."""
    mock_func = AsyncMock(side_effect=MockAPIError("Bad Request", status_code=400))
    
    with pytest.raises(MockAPIError) as exc_info:
        await retry_with_backoff(mock_func, max_retries=3, base_delay=0.01)
        
    assert "Bad Request" in str(exc_info.value)
    mock_func.assert_called_once()  # No retries


@pytest.mark.asyncio
async def test_retry_with_backoff_rate_limit():
    """Test retry_with_backoff raises rate limit errors immediately (bypasses retry)."""
    mock_func = AsyncMock(side_effect=MockAPIError("Too Many Requests", status_code=429))
    
    with pytest.raises(MockAPIError) as exc_info:
        await retry_with_backoff(mock_func, max_retries=3, base_delay=0.01)
        
    assert "Too Many Requests" in str(exc_info.value)
    mock_func.assert_called_once()  # Bypassed retry


@pytest.mark.asyncio
async def test_gemini_engine_retry():
    """Test GeminiAIEngine retries on transient errors and rotates on rate limit."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        # Configure GeminiAIEngine
        engine = GeminiAIEngine(api_key="test_key", model="gemini-3-flash-preview")
        
        # Mock generate_content to fail once with 500, then succeed
        calls = 0
        def mock_generate(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise MockAPIError("Transient error", code=500)
            mock_resp = MagicMock()
            mock_resp.text = "gemini_success"
            return mock_resp
            
        mock_client.models.generate_content.side_effect = mock_generate
        
        # Run generate_content with low retry delay for testing
        with patch("core.ai_engine.retry_with_backoff") as mock_retry:
            async def side_effect_fn(func, *args, **kwargs):
                kwargs.pop("max_retries", None)
                return await retry_with_backoff(func, *args, max_retries=2, base_delay=0.01, **kwargs)
            mock_retry.side_effect = side_effect_fn
            
            result = await engine.generate_content("hello")
            
        assert result == "gemini_success"
        assert calls == 2


@pytest.mark.asyncio
async def test_openai_engine_retry():
    """Test OpenAIEngine retries on transient errors."""
    with patch("openai.AsyncOpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        
        engine = OpenAIEngine(api_key="test_key", model="gpt-4o")
        
        calls = 0
        async def mock_create(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise MockAPIError("Transient 502", status_code=502)
            mock_resp = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "openai_success"
            mock_resp.choices = [mock_choice]
            return mock_resp
            
        mock_client.chat.completions.create = mock_create
        
        # Patch retry_with_backoff to use small delays
        with patch("core.ai_engine.retry_with_backoff") as mock_retry:
            async def side_effect_fn(func, *args, **kwargs):
                kwargs.pop("max_retries", None)
                return await retry_with_backoff(func, *args, max_retries=2, base_delay=0.01, **kwargs)
            mock_retry.side_effect = side_effect_fn
            
            result = await engine.generate_content("hello")
            
        assert result == "openai_success"
        assert calls == 2


@pytest.mark.asyncio
async def test_gemini_engine_rotation_on_503():
    """Test GeminiAIEngine rotates to the next model when it encounters a 503 error."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        # Configure GeminiAIEngine with multiple models
        with patch("config.settings.GEMINI_MODEL", "model-1,model-2"):
            engine = GeminiAIEngine(api_key="test_key")
        
        # Ensure we have both models in rotation
        assert engine.models == ["model-1", "model-2"]
        
        calls_model_1 = 0
        calls_model_2 = 0
        
        def mock_generate(*args, **kwargs):
            nonlocal calls_model_1, calls_model_2
            model_used = kwargs.get("model")
            if model_used == "model-1":
                calls_model_1 += 1
                raise MockAPIError("503 UNAVAILABLE: Model demand is high", code=503)
            elif model_used == "model-2":
                calls_model_2 += 1
                mock_resp = MagicMock()
                mock_resp.text = "success_model_2"
                return mock_resp
            else:
                raise ValueError(f"Unknown model: {model_used}")
                
        mock_client.models.generate_content.side_effect = mock_generate
        
        # Patch retry_with_backoff to use low max_retries for model_1 call so it fails quickly
        with patch("core.ai_engine.retry_with_backoff") as mock_retry:
            async def side_effect_fn(func, *args, **kwargs):
                kwargs.pop("max_retries", None)
                return await retry_with_backoff(func, *args, max_retries=1, base_delay=0.01, **kwargs)
            mock_retry.side_effect = side_effect_fn
            
            result = await engine.generate_content("hello")
            
        assert result == "success_model_2"
        assert calls_model_1 == 1
        assert calls_model_2 == 1
        assert engine.current_model == "model-2"


@pytest.mark.asyncio
async def test_gemini_engine_uses_configurable_retries():
    """Test GeminiAIEngine uses config.settings.GEMINI_503_RETRIES by default."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        # Configure GeminiAIEngine with custom retries settings
        with patch("config.settings.GEMINI_503_RETRIES", 42):
            engine = GeminiAIEngine(api_key="test_key", model="gemini-3-flash-preview")
            
            with patch("core.ai_engine.retry_with_backoff", new_callable=AsyncMock) as mock_retry:
                await engine.generate_content("hello")
                
                # Check that retry_with_backoff was called with max_retries=42
                mock_retry.assert_called_once()
                kwargs_passed = mock_retry.call_args[1]
                assert kwargs_passed.get("max_retries") == 42


