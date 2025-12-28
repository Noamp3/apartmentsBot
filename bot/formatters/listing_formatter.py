# bot/formatters/listing_formatter.py
"""Telegram message formatting for apartment listings."""

from typing import List, Optional
from models.listing import EnrichedListing
from models.rejection_log import RejectionLog


class ListingFormatter:
    """Formats listings and rejections for Telegram messages."""
    
    @staticmethod
    def format_listing(enriched: EnrichedListing, bordering_note: str = "") -> str:
        """Format an enriched listing for Telegram notification."""
        lines = []
        
        # Title/header
        lines.append("🏘️ *ערב טוב\\! מצאתי משהו:*")
        lines.append("")
        
        # Price (with broker fee note if applicable)
        if enriched.extracted_price:
            # Escape the price number
            price_val = ListingFormatter._escape_markdown(f"{enriched.extracted_price:,}")
            price_str = f"💰 *מחיר:* {price_val}₪"
            
            if enriched.has_broker_fee:
                effective = enriched.effective_monthly_price
                effective_val = ListingFormatter._escape_markdown(f"{effective:,}")
                price_str += f" \\(\\+ תיווך \\= {effective_val}₪ אפקטיבי\\)"
            lines.append(price_str)
        
        # Rooms
        if enriched.extracted_bedrooms:
            rooms_val = ListingFormatter._escape_markdown(str(enriched.extracted_bedrooms))
            lines.append(f"🛏️ *חדרים:* {rooms_val}")
        
        # Location
        location = enriched.extracted_neighborhood or enriched.extracted_location
        if location:
            loc_val = ListingFormatter._escape_markdown(location)
            lines.append(f"📍 *מיקום:* {loc_val}")
        
        # Bordering neighborhood note
        if bordering_note:
            note_val = ListingFormatter._escape_markdown(bordering_note)
            lines.append(f"ℹ️ {note_val}")
        
        # Key attributes
        attrs = enriched.attributes or {}
        attr_icons = []
        
        if attrs.get("has_parking"):
            attr_icons.append("🅿️ חניה")
        if attrs.get("has_balcony"):
            attr_icons.append("🌿 מרפסת")
        if attrs.get("has_elevator"):
            attr_icons.append("🛗 מעלית")
        if attrs.get("has_ac"):
            attr_icons.append("❄️ מזגן")
        if attrs.get("allows_pets"):
            attr_icons.append("🐕 מותר חיות")
        if attrs.get("is_furnished"):
            attr_icons.append("🪑 מרוהט")
        
        if attr_icons:
            lines.append("")
            # No need to escape icons/Hebrew attribute names as they are hardcoded safe strings
            lines.append("✨ " + " \\| ".join(attr_icons))
        
        # Description snippet
        if enriched.listing.description:
            desc = enriched.listing.description[:200]
            if len(enriched.listing.description) > 200:
                desc += "..."
            # Escape special chars for Markdown
            desc = ListingFormatter._escape_markdown(desc)
            lines.append("")
            lines.append(f"📝 {desc}")
        
        # Link
        if enriched.listing.url:
            lines.append("")
            # URL must be escaped in the text part, but handled carefully in the link part
            # Actually for [text](url), the url shouldn't be escaped usually, but parentheses inside need care
            # Simplest for now is standard link
            lines.append(f"🔗 [לצפייה בדירה]({enriched.listing.url})")
        
        # Source
        source_name = "פייסבוק" if enriched.listing.source == "facebook" else "Yad2"
        lines.append(f"📌 מקור: {source_name}")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_rejection(rejection: RejectionLog) -> str:
        """Format a rejection log for display."""
        lines = []
        
        lines.append("❌ *דירה שנפסלה*")
        lines.append("")
        
        if rejection.listing_price:
            price_val = ListingFormatter._escape_markdown(f"{rejection.listing_price:,}")
            lines.append(f"💰 מחיר: {price_val}₪")
        
        if rejection.listing_location:
            loc_val = ListingFormatter._escape_markdown(rejection.listing_location)
            lines.append(f"📍 מיקום: {loc_val}")
        
        lines.append("")
        lines.append("*סיבות פסילה:*")
        for reason in rejection.reasons:
            reason_val = ListingFormatter._escape_markdown(reason)
            lines.append(f"• {reason_val}")
        
        if rejection.listing_url:
            lines.append("")
            lines.append(f"[לצפייה]({rejection.listing_url})")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_rejections_summary(rejections: List[RejectionLog]) -> str:
        """Format a summary of multiple rejections."""
        if not rejections:
            return "✅ לא נמצאו דירות שנפסלו בשבוע האחרון"
        
        lines = []
        lines.append(f"📋 *{len(rejections)} דירות נפסלו לאחרונה:*")
        lines.append("")
        
        for i, rej in enumerate(rejections[:10], 1):
            price = f"{rej.listing_price:,}" if rej.listing_price else "?"
            price = ListingFormatter._escape_markdown(price)
            
            loc = rej.listing_location or "לא ידוע"
            loc = ListingFormatter._escape_markdown(loc)
            
            reason = rej.reasons[0] if rej.reasons else "לא צוין"
            reason = ListingFormatter._escape_markdown(reason)
            
            lines.append(f"{i}\\. {price}₪ \\| {loc}")
            lines.append(f"   ↳ {reason}")
            lines.append("")
        
        if len(rejections) > 10:
            lines.append(f"\\.\\.\\. ועוד {len(rejections) - 10} דירות")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_rules_list(rules: list) -> str:
        """Format user's active search rules."""
        if not rules:
            return "📋 אין לך כללי חיפוש פעילים\\.\n\nשלח הודעה עם הדרישות שלך ואני אוסיף אותן\\!"
        
        lines = []
        lines.append("📋 *כללי החיפוש שלך:*")
        lines.append("")
        
        for i, rule in enumerate(rules, 1):
            type_icons = {
                "price_max": "💰",
                "price_min": "💰",
                "bedrooms_min": "🛏️",
                "bedrooms_max": "🛏️",
                "area": "📍",
                "custom": "✨",
            }
            
            icon = type_icons.get(rule.rule_type.value, "•")
            text = rule.original_text or rule.value
            # Escape rule text
            text = ListingFormatter._escape_markdown(text)
            lines.append(f"{i}\\. {icon} {text}")
        
        lines.append("")
        lines.append("_שלח הודעה כדי להוסיף כלל חדש_")
        lines.append("_או /clear למחיקת כל הכללים_")
        
        return "\n".join(lines)
    
    @staticmethod
    def _escape_markdown(text: str) -> str:
        """Escape special Markdown V2 characters."""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', 
                        '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
