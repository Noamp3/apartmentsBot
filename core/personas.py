# core/personas.py
"""Definitions and prompt templates for supported AI personas."""

import os
import json
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class PersonaDefinition:
    """Contains all prompts, metadata, and copy for a specific bot persona."""
    name: str
    display_name: str
    emoji: str
    description: str
    system_prompt_prefix: str
    welcome_batch_prompt: str
    sass_batch_prompt: str
    parse_rules_prompt: str
    fallback_welcome: str
    switch_confirmation: str
    help_template: str  # Added template for /help command
    onboarding_welcome: str  # Onboarding welcome message asking for location
    onboarding_ask_budget: str  # Onboarding message asking for budget
    onboarding_ask_bedrooms: str  # Onboarding message asking for bedrooms
    no_matches_found: str  # Message sent when no matches are found in the database

# Registry of all available personas (loaded dynamically)
PERSONAS: Dict[str, PersonaDefinition] = {}

def load_personas():
    """Dynamically load all personas from the prompts/personas/ directory."""
    from core.prompt_manager import get_prompts_dir
    personas_dir = os.path.join(get_prompts_dir(), "personas")
    
    if not os.path.exists(personas_dir):
        return
        
    for filename in os.listdir(personas_dir):
        if filename.endswith(".json"):
            filepath = os.path.join(personas_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    persona = PersonaDefinition(**data)
                    PERSONAS[persona.name] = persona
            except Exception:
                # Avoid logging with app logger here to prevent circular imports on startup
                pass

# Load personas at module import time
load_personas()

def get_persona(name: Optional[str]) -> PersonaDefinition:
    """Retrieve a persona definition by name, defaulting to barakush."""
    if not name or name not in PERSONAS:
        name = "barakush"
    
    if name in PERSONAS:
        return PERSONAS[name]
        
    if PERSONAS:
        return list(PERSONAS.values())[0]
        
    raise RuntimeError("No personas loaded in the system!")
