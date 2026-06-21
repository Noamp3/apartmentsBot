# core/prompt_manager.py
import os
import logging
from typing import Dict, Any

log = logging.getLogger(__name__)

# Base directory for prompts (root of the repository /prompts)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(os.path.dirname(CURRENT_DIR), "prompts")

_PROMPT_CACHE: Dict[str, str] = {}

def get_prompts_dir() -> str:
    """Returns the absolute path to the prompts directory."""
    return PROMPTS_DIR

def load_prompt_template(name: str) -> str:
    """Reads a prompt template file from the prompts directory and caches it in memory."""
    if name in _PROMPT_CACHE:
        return _PROMPT_CACHE[name]
    
    # Try looking for {name}.txt
    filepath = os.path.join(PROMPTS_DIR, f"{name}.txt")
    if not os.path.exists(filepath):
        # Fallback to {name}.md if .txt doesn't exist
        filepath = os.path.join(PROMPTS_DIR, f"{name}.md")
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Prompt template file not found: {name} (tried .txt and .md in {PROMPTS_DIR})")
            
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    _PROMPT_CACHE[name] = content
    return content

def render_prompt(name: str, **kwargs: Any) -> str:
    """Loads a prompt template and substitutes placeholders formatted as {{key}}."""
    template = load_prompt_template(name)
    rendered = template
    for key, val in kwargs.items():
        placeholder = f"{{{{{key}}}}}"
        rendered = rendered.replace(placeholder, str(val))
    return rendered

def clear_prompt_cache():
    """Clears the internal cache of loaded prompt templates."""
    _PROMPT_CACHE.clear()
