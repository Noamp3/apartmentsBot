"""Repository for listing and seen listings operations."""

import json
from datetime import datetime, timedelta
from typing import List, Optional, Set

from database.connection import DatabaseManager
from models.listing import Listing, EnrichedListing
from utils.logger import Loggers

log = Loggers.db()


class SeenListingsRepository:
    """Tracks which listings have been seen to avoid duplicates."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def is_seen(self, listing_id: str) -> bool:
        """Check if a listing has been seen."""
        row = await self.db.fetch_one(
            "SELECT 1 FROM seen_listings WHERE listing_id = ?",
            (listing_id,)
        )
        return row is not None
    
    async def mark_seen(self, listing: Listing):
        """Mark a listing as seen."""
        await self.db.execute(
            """
            INSERT OR IGNORE INTO seen_listings (listing_id, source, url, first_seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (listing.id, listing.source, listing.url, datetime.now().isoformat())
        )
    
    async def mark_many_seen(self, listings: List[Listing]):
        """Mark multiple listings as seen."""
        for listing in listings:
            await self.mark_seen(listing)
    
    async def get_seen_ids(self, source: Optional[str] = None) -> Set[str]:
        """Get all seen listing IDs, optionally filtered by source."""
        if source:
            rows = await self.db.fetch_all(
                "SELECT listing_id FROM seen_listings WHERE source = ?",
                (source,)
            )
        else:
            rows = await self.db.fetch_all(
                "SELECT listing_id FROM seen_listings"
            )
        return {row["listing_id"] for row in rows}
    
    async def filter_new(self, listings: List[Listing]) -> List[Listing]:
        """Filter out already-seen listings, returning only new ones."""
        seen_ids = await self.get_seen_ids()
        new_listings = []
        skipped_ids = []
        
        for l in listings:
            if l.id not in seen_ids:
                new_listings.append(l)
            else:
                skipped_ids.append(l.id)
        
        if skipped_ids:
            unique_skipped = list(set(skipped_ids))
            log.debug(f"Skipping {len(unique_skipped)} seen listings (found {len(skipped_ids)} in input): {unique_skipped[:5]}...")
            
        return new_listings
    
    async def cleanup_old_entries(self, days_to_keep: int = 7):
        """Remove entries older than specified days."""
        cutoff = datetime.now() - timedelta(days=days_to_keep)
        await self.db.execute(
            "DELETE FROM seen_listings WHERE first_seen_at < ?",
            (cutoff.isoformat(),)
        )


class ListingRepository:
    """Repository for enriched listings cache."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def save_enriched(self, enriched: EnrichedListing):
        """Save an enriched listing to cache."""
        await self.db.execute(
            """
            INSERT OR REPLACE INTO enriched_listings 
            (listing_id, source, url, title, description, location, raw_text, images,
             extracted_price, extracted_bedrooms, extracted_location, extracted_neighborhood,
             has_broker_fee, attributes, area_matches, bordering_areas, posted_at, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enriched.listing.id,
                enriched.listing.source,
                enriched.listing.url,
                enriched.listing.title,
                enriched.listing.description,
                enriched.listing.location,
                enriched.listing.raw_text,
                json.dumps(enriched.listing.images, ensure_ascii=False),
                enriched.extracted_price,
                enriched.extracted_bedrooms,
                enriched.extracted_location,
                enriched.extracted_neighborhood,
                enriched.has_broker_fee,
                json.dumps(enriched.attributes, ensure_ascii=False),
                json.dumps(enriched.area_matches, ensure_ascii=False),
                json.dumps(enriched.bordering_areas, ensure_ascii=False),
                enriched.listing.posted_at.isoformat() if enriched.listing.posted_at else None,
                enriched.listing.scraped_at.isoformat(),
            )
        )
        log.debug(f"Saved enriched listing {enriched.listing.id} to DB")
    
    async def get_enriched(self, listing_id: str) -> Optional[EnrichedListing]:
        """Get an enriched listing from cache."""
        row = await self.db.fetch_one(
            "SELECT * FROM enriched_listings WHERE listing_id = ?",
            (listing_id,)
        )
        if row:
            return self._row_to_enriched(row)
        return None
    
    async def get_recent(self, limit: int = 50) -> List[EnrichedListing]:
        """Get recent enriched listings."""
        rows = await self.db.fetch_all(
            """
            SELECT * FROM enriched_listings 
            ORDER BY enriched_at DESC 
            LIMIT ?
            """,
            (limit,)
        )
        return [self._row_to_enriched(row) for row in rows]
    
    async def get_recent_for_new_user(
        self, 
        max_age_hours: int = 24, 
        limit: int = 20
    ) -> List[EnrichedListing]:
        """Get recent listings for new users (max 1 day old by default)."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        rows = await self.db.fetch_all(
            """
            SELECT * FROM enriched_listings 
            WHERE enriched_at >= ?
            ORDER BY enriched_at DESC 
            LIMIT ?
            """,
            (cutoff.isoformat(), limit)
        )
        return [self._row_to_enriched(row) for row in rows]
    
    async def get_recent_enrichments(self, hours: int = 24) -> List[EnrichedListing]:
        """Get all enriched listings from the specified time window."""
        cutoff = datetime.now() - timedelta(hours=hours)
        rows = await self.db.fetch_all(
            """
            SELECT * FROM enriched_listings 
            WHERE enriched_at >= ?
            ORDER BY enriched_at DESC
            """,
            (cutoff.isoformat(),)
        )
        return [self._row_to_enriched(row) for row in rows]
    
    async def cleanup_old_listings(self, days_to_keep: int = 7):
        """Remove listings older than specified days."""
        cutoff = datetime.now() - timedelta(days=days_to_keep)
        await self.db.execute(
            "DELETE FROM enriched_listings WHERE enriched_at < ?",
            (cutoff.isoformat(),)
        )
    
    def _row_to_enriched(self, row) -> EnrichedListing:
        """Convert a database row to EnrichedListing."""
        listing = Listing(
            id=row["listing_id"],
            source=row["source"],
            url=row["url"],
            title=row["title"] or "",
            description=row["description"] or "",
            location=row["location"] or "",
            raw_text=row["raw_text"] or "",
            images=json.loads(row["images"]) if row["images"] else [],
            posted_at=row["posted_at"],
            scraped_at=row["scraped_at"],
        )
        
        return EnrichedListing(
            listing=listing,
            extracted_price=row["extracted_price"],
            extracted_bedrooms=row["extracted_bedrooms"],
            extracted_location=row["extracted_location"] or "",
            extracted_neighborhood=row["extracted_neighborhood"] or "",
            has_broker_fee=bool(row["has_broker_fee"]),
            attributes=json.loads(row["attributes"]) if row["attributes"] else {},
            area_matches=json.loads(row["area_matches"]) if row["area_matches"] else {},
            bordering_areas=json.loads(row["bordering_areas"]) if row["bordering_areas"] else {},
        )
