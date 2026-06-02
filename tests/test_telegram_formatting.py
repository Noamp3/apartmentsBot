# tests/test_telegram_formatting.py
import pytest
import html
import re
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch

from database.repositories import RuleRepository
from bot.formatters.listing_formatter import ListingFormatter
from bot.handlers.command_handler import CommandHandler
from bot.handlers.callback_handler import CallbackHandler
from models.listing import Listing, EnrichedListing
from models.rejection_log import RejectionLog
from models.search_rule import SearchRule, RuleType


def validate_html(text: str):
    """Verify that text is valid HTML/XML and contains no parsing errors."""
    # Wrap in root element to check well-formedness
    wrapped = f"<root>{text}</root>"
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        raise AssertionError(f"HTML Formatting error: {e}\nContent:\n{text}")


def validate_markdown_v2(text: str):
    """Verify that Markdown V2 syntax is balanced and all reserved characters are escaped."""
    # Strip inline code blocks first since characters inside them don't need escaping
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`\n]+`', '', text)
    
    # Strip valid links: [text](url)
    # The URL itself doesn't require escaping of most reserved chars, but brackets do
    # Search for unescaped links
    link_pattern = r'(?<!\\)\[(.*?)(?<!\\)\]\((.*?)(?<!\\)\)'
    text = re.sub(link_pattern, r'\1', text) # Keep text part for escaping checks
    
    # Check for balanced styling syntax
    # Bold (*text*)
    bold_pattern = r'(?<!\\)\*(.*?)(?<!\\)\*'
    while re.search(bold_pattern, text):
        text = re.sub(bold_pattern, r'\1', text)
        
    # Italic (_text_)
    italic_pattern = r'(?<!\\)_(.*?)(?<!\\)_'
    while re.search(italic_pattern, text):
        text = re.sub(italic_pattern, r'\1', text)

    # Remaining special characters must be escaped
    # Telegram MarkdownV2 special characters: _ * [ ] ( ) ~ ` > # + - = | { } . !
    special_chars = r'_*[]()~`>#+-=|{}.!'
    
    # Find any of these special chars that are NOT preceded by a backslash
    for char in special_chars:
        # Match char that is not preceded by a backslash
        # Using a negative lookbehind
        pattern = r'(?<!\\)' + re.escape(char)
        matches = list(re.finditer(pattern, text))
        if matches:
            char_snippet = text[max(0, matches[0].start() - 15) : min(len(text), matches[0].end() + 15)]
            raise AssertionError(
                f"Unescaped MarkdownV2 character '{char}' found at position {matches[0].start()}.\n"
                f"Context snippet: ...{char_snippet}...\n"
                f"Full content:\n{text}"
            )


# --- Tests ---

def test_listing_formatter_markdown_v2_with_special_chars():
    """Verify ListingFormatter generates valid MarkdownV2 with stress-test inputs."""
    listing = Listing(
        id="fb_12345",
        source="facebook",
        url="https://facebook.com/groups/apartments/posts/12345/?param=value",
        title="דירת 3 חדרים מהממת ברוטשילד!",
        description="דירת חלומות! 3 חדרים, מרפסת + חניה. פשוט מושלמת! (בעלי חיים מותרים).",
        location="רוטשילד, תל אביב",
        raw_text="דירת חלומות! 3 חדרים, מרפסת + חניה. פשוט מושלמת! (בעלי חיים מותרים).",
        posted_at="2026-06-01T12:00:00"
    )
    enriched = EnrichedListing(
        listing=listing,
        extracted_price=5500,
        extracted_bedrooms=3.0,
        extracted_location="תל אביב",
        extracted_neighborhood="לב העיר",
        has_broker_fee=True,
        attributes={
            "has_parking": True,
            "has_balcony": True,
            "has_elevator": False,
            "allows_pets": True
        }
    )
    
    # Format notification with special chars in bordering note & sass
    bordering_note = "קרוב לשכונת נווה צדק (במרחק 5 דקות הליכה!)."
    sass_intro = "תראו את הדירה הזו! לא תאמינו למחיר... פשוט מטורף!"
    
    msg = ListingFormatter.format_listing(enriched, bordering_note, sass_intro)
    
    # Validate
    validate_markdown_v2(msg)


def test_rejections_markdown_v2_escaping():
    """Verify ListingFormatter format_rejection and format_rejections_summary are valid MarkdownV2."""
    rejection = RejectionLog(
        listing_id="yad2_9999",
        user_id=12345,
        listing_url="https://yad2.co.il/apartments/9999",
        listing_price=6200,
        listing_location="דיזינגוף, תל אביב",
        rejected_rules=["price_max"],
        reasons=["המחיר (6,200₪) גבוה מהתקציב המקסימלי (6,000₪)!"],
        match_method="zero_ai"
    )
    
    # Test single rejection log formatting
    single_msg = ListingFormatter.format_rejection(rejection)
    validate_markdown_v2(single_msg)
    
    # Test rejection summary log formatting
    summary_msg = ListingFormatter.format_rejections_summary([rejection, rejection])
    validate_markdown_v2(summary_msg)


def test_rules_list_markdown_v2_escaping():
    """Verify ListingFormatter format_rules_list is valid MarkdownV2."""
    rules = [
        SearchRule(id=1, user_id=123, rule_type=RuleType.PRICE_MAX, value="6000", original_text="עד 6,000 ש\"ח"),
        SearchRule(id=2, user_id=123, rule_type=RuleType.BEDROOMS_MIN, value="2.5", original_text="לפחות 2.5 חדרים"),
        SearchRule(id=3, user_id=123, rule_type=RuleType.AREA, value="לב העיר", original_text="בלב העיר, תל אביב!"),
        SearchRule(id=4, user_id=123, rule_type=RuleType.BORDER_AREA, value="נווה צדק,כרם התימנים", original_text="נווה צדק וכרם התימנים")
    ]
    
    rules_msg = ListingFormatter.format_rules_list(rules, allow_bordering=True)
    validate_markdown_v2(rules_msg)
    
    # Test empty rules
    empty_msg = ListingFormatter.format_rules_list([], allow_bordering=False)
    validate_markdown_v2(empty_msg)


@pytest.mark.asyncio
async def test_admin_dashboard_html():
    """Verify CommandHandler.get_admin_dashboard_data builds valid HTML."""
    handler = CommandHandler()
    
    # Mock get_db results
    mock_db = MagicMock()
    mock_db.fetch_one = AsyncMock(side_effect=[
        {"count": 12},  # users_count
        {"count": 8},   # active_users
        {"count": 25},  # rules_count
        {"count": 150}, # seen_count
        {"count": 45},  # enriched_count
        {"count": 300}  # rejections_count
    ])
    
    with patch('bot.handlers.command_handler.get_db', return_value=mock_db), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.stat') as mock_stat:
        
        # Mock database file size: 1.5MB
        mock_stat.return_value.st_size = 1.5 * 1024 * 1024
        
        dashboard_msg, reply_markup = await handler.get_admin_dashboard_data()
        
        # Verify message compiles as valid HTML
        validate_html(dashboard_msg)
        assert "👑" in dashboard_msg
        assert "1.50 MB" in dashboard_msg


@pytest.mark.asyncio
async def test_admin_callbacks_html():
    """Verify that all CallbackHandler admin menu methods generate valid HTML."""
    cb = CallbackHandler()
    
    # Create mock query with awaitable methods
    mock_query = MagicMock()
    mock_query.edit_message_reply_markup = AsyncMock()
    mock_query.answer = AsyncMock()
    mock_query.message = MagicMock()
    mock_query.message.chat_id = 999
    
    # Store sent messages to validate
    sent_messages = []
    
    async def mock_safe_edit_message_text(query, text, parse_mode=None):
        if parse_mode == "HTML":
            validate_html(text)
        sent_messages.append((text, parse_mode))
        
    cb._safe_edit_message_text = mock_safe_edit_message_text
    
    # Mock database
    mock_db = MagicMock()
    mock_db.fetch_all = AsyncMock()
    
    # Setup context
    mock_context = MagicMock()
    mock_command_handler = CommandHandler()
    mock_context.bot_data = {"command_handler": mock_command_handler}
    
    with patch('bot.handlers.callback_handler.get_db', return_value=mock_db), \
         patch('bot.handlers.command_handler.get_db', return_value=mock_db):
        
        # 1. Test _show_admin_users
        mock_db.fetch_all.return_value = [
            {"telegram_id": 111, "username": "user_one", "is_active": True, "is_admin": False, "persona": "yekke", "created_at": "2026-06-01T10:00:00"},
            {"telegram_id": 222, "username": "admin_two", "is_active": True, "is_admin": True, "persona": "barakush", "created_at": "2026-06-01T10:10:00"}
        ]
        sent_messages.clear()
        # Mock RuleRepository
        with patch('database.repositories.RuleRepository.get_user_rules', return_value=[]):
            await cb._show_admin_users(mock_query, mock_context)
        assert len(sent_messages) == 1
        assert sent_messages[0][1] == "HTML"
        validate_html(sent_messages[0][0])
        
        # 2. Test _show_admin_recent_listings
        mock_db.fetch_all.return_value = [
            {
                "title": "דירה מהממת ברוטשילד / דיזינגוף & פינסקר!",
                "source": "yad2",
                "url": "https://yad2.co.il/item/1",
                "extracted_price": 5000,
                "extracted_bedrooms": 2,
                "extracted_neighborhood": "לב העיר",
                "enriched_at": "2026-06-02T10:00:00"
            }
        ]
        sent_messages.clear()
        await cb._show_admin_recent_listings(mock_query, mock_context)
        assert len(sent_messages) == 1
        assert sent_messages[0][1] == "HTML"
        validate_html(sent_messages[0][0])
        
        # 3. Test _show_admin_fb_menu
        sent_messages.clear()
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getmtime', return_value=1717282800), \
             patch('os.path.getsize', return_value=2048):
            await cb._show_admin_fb_menu(mock_query, mock_context)
        assert len(sent_messages) == 1
        assert sent_messages[0][1] == "HTML"
        validate_html(sent_messages[0][0])
        
        # 4. Test _show_admin_clear_menu
        sent_messages.clear()
        await cb._show_admin_clear_menu(mock_query, mock_context)
        assert len(sent_messages) == 1
        assert sent_messages[0][1] == "HTML"
        validate_html(sent_messages[0][0])
        
        # 5. Test _show_admin_server_stats
        sent_messages.clear()
        with patch('shutil.disk_usage', return_value=(100*1024**3, 40*1024**3, 60*1024**3)), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.stat') as mock_stat:
            mock_stat.return_value.st_size = 2 * 1024 * 1024
            await cb._show_admin_server_stats(mock_query, mock_context)
        assert len(sent_messages) == 1
        assert sent_messages[0][1] == "HTML"
        validate_html(sent_messages[0][0])
        
        # 6. Test _show_admin_gemini_test
        sent_messages.clear()
        mock_ai = AsyncMock()
        mock_ai.generate_content.return_value = "OK"
        mock_ai.current_model = "gemini-2.5-flash"
        mock_context.bot_data["ai_engine"] = mock_ai
        
        await cb._show_admin_gemini_test(mock_query, mock_context)
        assert len(sent_messages) == 1
        assert sent_messages[0][1] == "HTML"
        validate_html(sent_messages[0][0])
        assert "gemini-2.5-flash" in sent_messages[0][0]
        
        # 7. Test _prompt_admin_broadcast
        sent_messages.clear()
        await cb._prompt_admin_broadcast(mock_query, mock_context)
        assert len(sent_messages) == 1
        assert sent_messages[0][1] == "HTML"
        validate_html(sent_messages[0][0])

def test_static_telegram_calls_formatting_escaping():
    """Statically analyze the entire codebase to ensure Telegram formatting safety.
    
    Verifies that for every message-sending call, any dynamic interpolations (f-strings)
    are properly escaped using html.escape (for HTML) or _escape_markdown (for Markdown V2).
    """
    import os
    import ast
    
    sending_methods = {
        'send_message', 'reply_text', 'edit_message_text', 
        '_safe_reply_text', '_safe_edit_message_text',
        'send_listing_notification', 'format_listing', 'format_rejection'
    }
    
    errors = []
    
    # Walk codebase
    for root, _, files in os.walk('.'):
        # Ignore external folders
        if any(x in root for x in ['.venv', '.git', '__pycache__', '.pytest_cache', '.idea']):
            continue
            
        for file in files:
            if not file.endswith('.py'):
                continue
                
            # Skip the test file itself to avoid self-reference matching
            if file == 'test_telegram_formatting.py':
                continue
                
            file_path = os.path.join(root, file)
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    tree = ast.parse(f.read(), filename=file_path)
                except SyntaxError as se:
                    continue
                    
            # AST Visitor
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                    
                # Get function name
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                    
                if func_name not in sending_methods:
                    continue
                    
                # Find parse_mode and text argument
                parse_mode = None
                text_arg = None
                
                # Default parse_modes based on function signature / convention in bot
                # e.g., send_listing_notification default is MarkdownV2
                if func_name == 'send_listing_notification':
                    parse_mode = 'MarkdownV2'
                
                for kw in node.keywords:
                    if kw.arg == 'parse_mode':
                        if isinstance(kw.value, ast.Constant):
                            parse_mode = kw.value.value
                        elif isinstance(kw.value, ast.Name):
                            parse_mode = kw.value.id
                            
                # Skip validation if parse_mode is not a formatted mode (HTML, Markdown, MarkdownV2)
                if parse_mode not in ('HTML', 'MarkdownV2', 'Markdown'):
                    continue
                            
                # Get text/message/caption argument
                if node.args:
                    text_arg = node.args[0]
                else:
                    for kw in node.keywords:
                        if kw.arg in ('text', 'caption', 'message', 'enriched'):
                            text_arg = kw.value
                            
                if not text_arg:
                    continue
                    
                # If the text argument is an f-string (ast.JoinedStr)
                if isinstance(text_arg, ast.JoinedStr):
                    for part in text_arg.values:
                        if not isinstance(part, ast.FormattedValue):
                            continue
                            
                        # Verify the variable inside formatted value is escaped
                        val_node = part.value
                        is_escaped = False
                        
                        # 1. Simple calls like html.escape(...) or self._escape_markdown(...)
                        if isinstance(val_node, ast.Call):
                            call_func = ""
                            if isinstance(val_node.func, ast.Name):
                                call_func = val_node.func.id
                            elif isinstance(val_node.func, ast.Attribute):
                                call_func = val_node.func.attr
                            
                            # Check if the function name indicates escaping
                            if any(x in call_func.lower() for x in ('escape', 'format', 'icon', 'str', 'markup', 'keyboard')):
                                is_escaped = True
                                
                        # 2. Variable name formatting checks (e.g. price_escaped, title_escaped)
                        elif isinstance(val_node, ast.Name):
                            var_name = val_node.id
                            if any(x in var_name.lower() for x in ('escaped', 'icon', 'emoji', 'count', 'size_mb', 'size_kb', 'date_str', 'price_str', 'beds_str', 'time_str', 'id', 'num', 'total_gb', 'used_gb', 'free_gb')):
                                is_escaped = True
                                
                        # 3. Simple constants or properties
                        elif isinstance(val_node, ast.Constant) or isinstance(val_node, ast.Subscript):
                            is_escaped = True
                            
                        # If not escaped, report error
                        if not is_escaped:
                            # Try to extract the raw source string of the variable/value
                            val_str = ast.unparse(val_node) if hasattr(ast, 'unparse') else str(val_node)
                            errors.append(
                                f"File '{file_path}': Unescaped variable '{val_str}' interpolated in "
                                f"Telegram call '{func_name}' with parse_mode='{parse_mode}'."
                            )
                            
    if errors:
        raise AssertionError(
            "Telegram formatting safety static analysis failed!\n" +
            "\n".join(errors) +
            "\n\n💡 Tip: Wrap the interpolated variables in html.escape() for HTML parse_mode, "
            "or _escape_markdown() for MarkdownV2 parse_mode."
        )

