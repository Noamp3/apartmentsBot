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
    
    def _normalize_phone(self, phone: Optional[str]) -> Optional[str]:
        """Normalize phone number for comparison.
        
        Removes spaces, dashes, parentheses and handles Israeli phone format.
        Returns None if phone is empty or invalid.
        """
        if not phone:
            return None
        
        # Remove common separators
        normalized = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        normalized = normalized.replace("+", "")
        
        # Remove Israeli country code if present
        if normalized.startswith("972"):
            normalized = "0" + normalized[3:]
        
        # Must be at least 9 digits
        if len(normalized) < 9:
            return None
            
        return normalized
    
    def _normalize_street(self, street: Optional[str]) -> Optional[str]:
        """Normalize street name for comparison.
        
        Converts to lowercase and removes common prefixes.
        Returns None if street is empty.
        """
        if not street:
            return None
        
        normalized = street.lower().strip()
        
        # Remove common prefixes
        prefixes = ["רחוב ", "st ", "street ", "st. "]
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                break
        
        return normalized if normalized else None
    
    def _normalize_author(self, author: Optional[str]) -> Optional[str]:
        """Normalize author/poster name for comparison.
        
        Converts to lowercase and removes extra whitespace.
        Returns None if author is empty or "Unknown".
        """
        if not author or author.lower() in ["unknown", "לא ידוע"]:
            return None
        
        # Normalize whitespace and lowercase
        normalized = " ".join(author.lower().strip().split())
        
        return normalized if normalized and len(normalized) > 2 else None
    
    async def find_duplicate_by_fingerprint(
        self, 
        listing: "Listing",
        enriched: Optional["EnrichedListing"] = None
    ) -> Optional[tuple[str, list[str]]]:
        """Check if a listing matches an existing fingerprint.
        
        Returns (duplicate_listing_id, matched_fields) if duplicate found, None otherwise.
        
        A listing is considered duplicate if:
        1. Phone number matches + at least one other field (phone is clearly identifying)
        2. Author matches + price/bedrooms/street (same poster with same details)
        3. Street matches + price OR bedrooms (same location is specific enough)
        
        This prevents false positives from matching only price+bedrooms which could
        easily be different apartments.
        
        Args:
            listing: The listing to check
            enriched: Optional enriched data (for extracted fields)
            
        Returns:
            Tuple of (duplicate_listing_id, matched_fields) or None
        """
        # Extract and normalize identifying fields
        author = self._normalize_author(listing.author)
        phone = self._normalize_phone(listing.phone)
        price = enriched.extracted_price if enriched else listing.price
        bedrooms = enriched.extracted_bedrooms if enriched else listing.bedrooms
        street = self._normalize_street(enriched.extracted_street if enriched else "")
        neighborhood = enriched.extracted_neighborhood if enriched else ""
        
        # Build query conditions for each non-null field
        conditions = []
        params = []
        
        if author:
            conditions.append("author = ?")
            params.append(author)
        if phone:
            conditions.append("phone = ?")
            params.append(phone)
        if price:
            # Price tolerance: ±5%
            price_min = int(price * 0.95)
            price_max = int(price * 1.05)
            conditions.append("price BETWEEN ? AND ?")
            params.extend([price_min, price_max])
        if bedrooms:
            conditions.append("bedrooms = ?")
            params.append(bedrooms)
        if street:
            conditions.append("street = ?")
            params.append(street)
        
        # Need at least 2 fields to check
        if len(conditions) < 2:
            return None
        
        # Query for potential duplicates
        query = f"""
            SELECT listing_id, author, phone, price, bedrooms, street, neighborhood, source
            FROM listing_fingerprints
            WHERE ({" OR ".join(conditions)})
            AND listing_id != ?
        """
        params.append(listing.id)
        
        rows = await self.db.fetch_all(query, tuple(params))
        
        # Check each potential duplicate with stricter rules
        for row in rows:
            matched_fields = []
            
            # Check author match (clearly identifying)
            has_author_match = author and row["author"] == author
            if has_author_match:
                matched_fields.append("author")
            
            # Check phone match (clearly identifying)
            has_phone_match = phone and row["phone"] == phone
            if has_phone_match:
                matched_fields.append("phone")
            
            # Check price match (within tolerance)
            has_price_match = False
            if price and row["price"]:
                if abs(row["price"] - price) <= price * 0.05:
                    matched_fields.append("price")
                    has_price_match = True
            
            # Check bedrooms match
            has_bedrooms_match = False
            if bedrooms and row["bedrooms"] == bedrooms:
                matched_fields.append("bedrooms")
                has_bedrooms_match = True
            
            # Check street match (location-based identifying)
            has_street_match = False
            if street and row["street"] == street:
                matched_fields.append("street")
                has_street_match = True
            
            # Determine if this is a duplicate based on CLEARLY IDENTIFYING combinations:
            # IMPORTANT: Brokers can have multiple listings with same phone + bedrooms!
            # So phone + bedrooms alone is NOT sufficient. Must include price or street.
            # 
            # Safe duplicate indicators:
            # 1. Phone + price (same contact + same price = same listing)
            # 2. Phone + street (same contact + same location = same listing)  
            # 3. Author + price + bedrooms (private seller: same person + same details)
            # 4. Street + price (same location + price = same apartment)
            is_duplicate = False
            
            if has_phone_match and has_price_match:
                # Same phone + same price = definitely same listing
                is_duplicate = True
            elif has_phone_match and has_street_match:
                # Same phone + same street = definitely same listing
                is_duplicate = True
            elif has_author_match and has_price_match and has_bedrooms_match:
                # Same author + price + bedrooms = likely same listing (private seller)
                is_duplicate = True
            elif has_street_match and has_price_match:
                # Same street + price = likely same apartment
                is_duplicate = True
            
            if is_duplicate:
                log.info(
                    f"Duplicate found",
                    current_source=listing.source,
                    current_id=listing.id[:8],
                    current_author=author,
                    current_phone=phone,
                    current_price=price,
                    current_bedrooms=bedrooms,
                    matched_source=row['source'],
                    matched_id=row['listing_id'][:8],
                    matched_author=row['author'],
                    matched_phone=row['phone'],
                    matched_price=row['price'],
                    matched_bedrooms=row['bedrooms'],
                    matched_fields=matched_fields,
                )
                return (row["listing_id"], matched_fields)
        
        return None
    
    async def save_fingerprint(
        self,
        listing: "Listing",
        enriched: Optional["EnrichedListing"] = None
    ):
        """Save listing fingerprint for future duplicate detection.
        
        Args:
            listing: The listing to save fingerprint for
            enriched: Optional enriched data (for extracted fields)
        """
        # Ensure parent seen_listing exists before inserting fingerprint
        await self.mark_seen(listing)
        author = self._normalize_author(listing.author)
        phone = self._normalize_phone(listing.phone)
        price = enriched.extracted_price if enriched else listing.price
        bedrooms = enriched.extracted_bedrooms if enriched else listing.bedrooms
        street = self._normalize_street(enriched.extracted_street if enriched else "")
        neighborhood = enriched.extracted_neighborhood if enriched else ""
        
        await self.db.execute(
            """
            INSERT OR REPLACE INTO listing_fingerprints
            (listing_id, author, phone, price, bedrooms, street, neighborhood, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing.id,
                author,
                phone,
                price,
                bedrooms,
                street,
                neighborhood,
                listing.source,
                datetime.now().isoformat(),
            )
        )
        log.debug(f"Saved fingerprint for listing {listing.id[:8]} from {listing.source}")
    
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
             has_broker_fee, roomies, attributes, area_matches, bordering_areas, posted_at, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                enriched.roomies,
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
            roomies=bool(row["roomies"]) if "roomies" in row.keys() else False,
            attributes=json.loads(row["attributes"]) if row["attributes"] else {},
            area_matches=json.loads(row["area_matches"]) if row["area_matches"] else {},
            bordering_areas=json.loads(row["bordering_areas"]) if row["bordering_areas"] else {},
        )
