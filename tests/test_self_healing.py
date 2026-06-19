# tests/test_self_healing.py
"""Unit and integration tests for LLM-based selector self-healing."""

import os
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from scrapers.self_healing import SelfHealingManager


@pytest.fixture
def temp_cache_path(tmp_path):
    """Fixture providing a temporary cache JSON path."""
    return str(tmp_path / "healed_selectors.json")


@pytest.fixture
def mock_ai_engine():
    """Fixture providing a mocked AI engine."""
    engine = AsyncMock()
    # Mock standard parsing behavior
    engine._parse_json_response = lambda text: json.loads(text) if isinstance(text, str) else text
    return engine


def test_manager_loads_defaults(temp_cache_path):
    """Test that the manager successfully initializes with default selectors."""
    manager = SelfHealingManager(persist_path=temp_cache_path)
    assert manager.get_selector("post_container") == 'div[role="article"]'
    assert manager.get_selector("post_url") == 'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]'
    assert manager.get_selector("author") == 'strong, h2, h3'


def test_manager_save_and_load_healed(temp_cache_path):
    """Test that the manager successfully loads and saves selector overrides."""
    manager = SelfHealingManager(persist_path=temp_cache_path)
    manager.healed_selectors["post_container"] = "div.custom-healed-post"
    manager.healed_selectors["author"] = "span.profile-name"
    manager.save_healed_selectors()

    # Create new instance to test loading from disk
    new_manager = SelfHealingManager(persist_path=temp_cache_path)
    assert new_manager.get_selector("post_container") == "div.custom-healed-post"
    assert new_manager.get_selector("author") == "span.profile-name"
    # Should fall back to default for other attributes
    assert new_manager.get_selector("post_url") == 'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]'


def test_clean_html():
    """Test that HTML cleaning successfully removes scripts, styles, svgs and noise."""
    manager = SelfHealingManager()
    dirty_html = """
    <html>
      <head>
        <style>body { color: red; }</style>
        <script>alert('malicious script');</script>
      </head>
      <body>
        <div class="post-wrap" data-testid="feed-item" role="article">
          <svg><path d="M0 0z" /></svg>
          <img src="avatar.jpg" />
          <a href="/groups/123/permalink/456/">Link to Post</a>
          <span class="text-content">Cozy 3-room apartment in Tel Aviv!</span>
        </div>
      </body>
    </html>
    """
    cleaned = manager.clean_html(dirty_html)

    # Ensure styles/scripts/svgs/images are decomposed
    assert "<style>" not in cleaned
    assert "body { color: red; }" not in cleaned
    assert "<script>" not in cleaned
    assert "<svg>" not in cleaned
    assert "<img>" not in cleaned

    # Ensure structural attributes and text are retained
    assert "class=\"post-wrap\"" in cleaned
    assert "role=\"article\"" in cleaned
    assert "href=\"/groups/123/permalink/456/\"" in cleaned
    assert "Cozy 3-room apartment in Tel Aviv!" in cleaned


@pytest.mark.asyncio
async def test_heal_post_container(mock_ai_engine, temp_cache_path):
    """Test the complete container self-healing cycle."""
    # Mock LLM returning selector suggestion
    mock_ai_engine.generate_content.return_value = '{"selector": "div.healed-post-class", "reason": "Facebook class list updated"}'

    manager = SelfHealingManager(ai_engine=mock_ai_engine, persist_path=temp_cache_path)

    # Mock Playwright Page
    mock_page = AsyncMock()
    mock_page.content.return_value = "<html><body><div class='healed-post-class'>Post</div></body></html>"
    # Selector validation should find elements
    mock_page.query_selector_all.return_value = [AsyncMock()]

    healed = await manager.heal_post_container(mock_page, "div[role='article']")

    assert healed == "div.healed-post-class"
    assert manager.get_selector("post_container") == "div.healed-post-class"

    # Reload from cache path to verify persistence
    reloaded = SelfHealingManager(persist_path=temp_cache_path)
    assert reloaded.get_selector("post_container") == "div.healed-post-class"


@pytest.mark.asyncio
async def test_heal_attribute(mock_ai_engine, temp_cache_path):
    """Test the attribute self-healing cycle."""
    # Mock LLM returning selector suggestion
    mock_ai_engine.generate_content.return_value = '{"selector": "span.healed-timestamp", "reason": "Timestamp relocated to custom class"}'

    manager = SelfHealingManager(ai_engine=mock_ai_engine, persist_path=temp_cache_path)

    # Mock Playwright ElementHandle representing a post
    mock_element = AsyncMock()
    mock_element.inner_html.return_value = "<div><span class='healed-timestamp'>2h</span></div>"
    # Mock verification selector query
    mock_element.query_selector.return_value = AsyncMock()

    healed = await manager.heal_attribute(AsyncMock(), mock_element, "post_date", "abbr")

    assert healed == "span.healed-timestamp"
    assert manager.get_selector("post_date") == "span.healed-timestamp"

    # Reload from cache path to verify persistence
    reloaded = SelfHealingManager(persist_path=temp_cache_path)
    assert reloaded.get_selector("post_date") == "span.healed-timestamp"


@pytest.mark.asyncio
async def test_heal_post_container_retries_and_succeeds(mock_ai_engine, temp_cache_path):
    """Test that post container healing retries when verification fails and succeeds eventually."""
    # LLM returns failing selectors first, then a working one
    responses = [
        '{"selector": "fail-1", "reason": "First try"}',
        '{"selector": "fail-2", "reason": "Second try"}',
        '{"selector": "div.healed-post-class", "reason": "Third time is the charm"}'
    ]
    mock_ai_engine.generate_content.side_effect = responses

    manager = SelfHealingManager(ai_engine=mock_ai_engine, persist_path=temp_cache_path)

    # Mock Playwright Page
    mock_page = AsyncMock()
    mock_page.content.return_value = "<html><body><div class='healed-post-class'>Post</div></body></html>"

    # Only return elements for the valid selector
    async def query_selector_all_side_effect(sel):
        if sel == "div.healed-post-class":
            return [AsyncMock()]
        return []
    mock_page.query_selector_all.side_effect = query_selector_all_side_effect

    healed = await manager.heal_post_container(mock_page, "div[role='article']")

    assert healed == "div.healed-post-class"
    assert mock_ai_engine.generate_content.call_count == 3

    # Verify that failed selectors were passed into the prompt history in subsequent calls
    history_call_2 = mock_ai_engine.generate_content.call_args_list[1][0][0]
    assert "fail-1" in history_call_2

    history_call_3 = mock_ai_engine.generate_content.call_args_list[2][0][0]
    assert "fail-1" in history_call_3
    assert "fail-2" in history_call_3


@pytest.mark.asyncio
async def test_heal_post_container_fails_after_10_tries(mock_ai_engine, temp_cache_path):
    """Test that post container healing gives up after 10 failed tries."""
    mock_ai_engine.generate_content.return_value = '{"selector": "always-fail", "reason": "Stubborn LLM"}'

    manager = SelfHealingManager(ai_engine=mock_ai_engine, persist_path=temp_cache_path)

    mock_page = AsyncMock()
    mock_page.content.return_value = "<html><body>No match</body></html>"
    # Never find elements for selectors
    mock_page.query_selector_all.return_value = []

    healed = await manager.heal_post_container(mock_page, "div[role='article']")

    assert healed is None
    assert mock_ai_engine.generate_content.call_count == 10


@pytest.mark.asyncio
async def test_heal_attribute_retries_and_succeeds(mock_ai_engine, temp_cache_path):
    """Test that attribute healing retries on failure and eventually succeeds."""
    responses = [
        '{"selector": "fail-attr-1", "reason": "Try 1"}',
        '{"selector": "fail-attr-2", "reason": "Try 2"}',
        '{"selector": "span.healed-timestamp", "reason": "Try 3"}'
    ]
    mock_ai_engine.generate_content.side_effect = responses

    manager = SelfHealingManager(ai_engine=mock_ai_engine, persist_path=temp_cache_path)

    # Mock Playwright ElementHandle representing a post
    mock_element = AsyncMock()
    mock_element.inner_html.return_value = "<div><span class='healed-timestamp'>2h</span></div>"

    # Only return element for correct selector
    async def query_selector_side_effect(sel):
        if sel == "span.healed-timestamp":
            return AsyncMock()
        return None
    mock_element.query_selector.side_effect = query_selector_side_effect

    healed = await manager.heal_attribute(AsyncMock(), mock_element, "post_date", "abbr")

    assert healed == "span.healed-timestamp"
    assert mock_ai_engine.generate_content.call_count == 3

    # Verify failed selectors are listed in the prompt history
    history_call_3 = mock_ai_engine.generate_content.call_args_list[2][0][0]
    assert "fail-attr-1" in history_call_3
    assert "fail-attr-2" in history_call_3


@pytest.mark.asyncio
async def test_heal_attribute_fails_after_10_tries(mock_ai_engine, temp_cache_path):
    """Test that attribute healing stops and returns None after 10 failed tries."""
    mock_ai_engine.generate_content.return_value = '{"selector": "always-fail-attr", "reason": "Stubborn LLM"}'

    manager = SelfHealingManager(ai_engine=mock_ai_engine, persist_path=temp_cache_path)

    mock_element = AsyncMock()
    mock_element.inner_html.return_value = "<div>No match</div>"
    mock_element.query_selector.return_value = None

    healed = await manager.heal_attribute(AsyncMock(), mock_element, "post_date", "abbr")

    assert healed is None
    assert mock_ai_engine.generate_content.call_count == 10


def test_manager_loads_defaults_for_prefixed_facebook_sources(temp_cache_path):
    """Test that the manager successfully falls back to facebook defaults for facebook_group and facebook_feed."""
    group_manager = SelfHealingManager(source="facebook_group", persist_path=temp_cache_path)
    assert group_manager.get_selector("post_container") == 'div[role="article"]'
    assert group_manager.get_selector("post_url") == 'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]'

    feed_manager = SelfHealingManager(source="facebook_feed", persist_path=temp_cache_path)
    assert feed_manager.get_selector("post_container") == 'div[role="article"]'
    assert feed_manager.get_selector("post_url") == 'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]'

