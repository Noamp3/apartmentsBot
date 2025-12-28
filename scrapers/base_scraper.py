# scrapers/base_scraper.py
"""Abstract base class for all scrapers."""

from abc import ABC, abstractmethod
from typing import List
from models.listing import Listing


class BaseScraper(ABC):
    """Abstract base class for all scrapers."""
    
    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the name of the source (e.g., 'facebook', 'yad2')."""
        pass
    
    @abstractmethod
    async def scrape(self) -> List[Listing]:
        """Scrape listings from the source.
        
        Returns: List of Listing objects
        """
        pass
    
    @abstractmethod
    def parse_listing(self, raw_data: dict) -> Listing:
        """Convert raw scraped data to a Listing object.
        
        Args:
            raw_data: Raw data from scraping
            
        Returns: Listing object
        """
        pass
    
    def generate_listing_id(self, url: str) -> str:
        """Generate a unique ID for a listing based on URL and source.
        
        Args:
            url: The listing URL
            
        Returns: A unique identifier string
        """
        import hashlib
        content = f"{self.source_name}:{url}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
