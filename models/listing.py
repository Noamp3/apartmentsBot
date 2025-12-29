# models/listing.py
"""Apartment listing models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Listing:
    """Raw apartment listing scraped from a source."""
    
    id: str  # Unique identifier (hash of URL + source)
    source: str  # "facebook" or "yad2"
    url: str
    title: str
    description: str
    location: str
    raw_text: str  # Original Hebrew text
    
    price: Optional[int] = None
    bedrooms: Optional[int] = None
    phone: Optional[str] = None  # Contact phone number
    images: List[str] = field(default_factory=list)
    posted_at: Optional[datetime] = None
    scraped_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Handle type conversions."""
        if isinstance(self.posted_at, str):
            self.posted_at = datetime.fromisoformat(self.posted_at)
        if isinstance(self.scraped_at, str):
            self.scraped_at = datetime.fromisoformat(self.scraped_at)


@dataclass
class EnrichedListing:
    """Listing with AI-extracted metadata. Created ONCE, used for ALL users.
    
    This class adds structured data extracted by AI to optimize matching
    against user rules without additional AI calls per user.
    """
    
    # Original data
    listing: Listing
    
    # AI-extracted structured data (extracted ONCE)
    extracted_price: Optional[int] = None
    extracted_bedrooms: Optional[int] = None
    extracted_location: str = ""
    extracted_neighborhood: str = ""
    extracted_street: str = ""
    
    # Broker fee handling
    has_broker_fee: bool = False  # True if listing mentions תיווך
    
    # AI-computed attributes for custom rule matching
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    # Pre-computed area matches (cached)
    area_matches: Dict[str, bool] = field(default_factory=dict)
    bordering_areas: Dict[str, str] = field(default_factory=dict)
    
    @property
    def effective_monthly_price(self) -> Optional[int]:
        """Calculate effective monthly price including amortized broker fee.
        
        If listing has תיווך (broker fee), adds 1/12 of monthly rent to the price.
        Standard broker fee in Israel is ~1 month rent, distributed over 12 months.
        
        Example: 
            - Rent: 5000₪/month
            - With broker: 5000 + (5000/12) = 5000 + 417 = 5417₪/month effective
        """
        if self.extracted_price is None:
            return None
        
        if self.has_broker_fee:
            # Add amortized broker fee (1 month rent / 12 months)
            broker_fee_monthly = self.extracted_price // 12
            return self.extracted_price + broker_fee_monthly
        
        return self.extracted_price
    
    @property
    def broker_fee_note(self) -> str:
        """Generate Hebrew explanation of the effective price.
        
        Used in notifications to explain the price calculation.
        """
        if not self.has_broker_fee or self.extracted_price is None:
            return ""
        
        broker_monthly = self.extracted_price // 12
        effective = self.effective_monthly_price
        
        return f"💰 מחיר כולל תיווך מפורס: {effective:,}₪ (שכירות {self.extracted_price:,}₪ + {broker_monthly:,}₪/חודש דמי תיווך)"
    
    @property
    def display_price(self) -> str:
        """Format price for display, including broker note if applicable."""
        if self.extracted_price is None:
            return "לא צוין מחיר"
        
        if self.has_broker_fee:
            return f"{self.extracted_price:,}₪ (+ תיווך)"
        
        return f"{self.extracted_price:,}₪"
