# utils/text_utils.py
"""Text and formatting utilities."""

def escape_markdown(text: str) -> str:
    """Escape special Markdown V2 characters."""
    if not text:
        return ""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', 
                    '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text
