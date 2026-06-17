# core/processing.py
"""Service for matching listings to users and sending notifications."""

import asyncio
from typing import List, Dict, Optional, Set

from config import settings
from database import get_db
from database.repositories import (
    UserRepository, 
    RuleRepository, 
    RejectionRepository,
    ListingRepository,
    NotificationRepository
)
from core.ai_engine import GeminiAIEngine
from core.matcher import ZeroAIUserMatcher
from models.listing import EnrichedListing
from models.user import User
from models.search_rule import SearchRule
from bot.telegram_bot import ApartmentBot
from bot.notifications import NotificationDispatcher, TelegramNotificationProvider
from utils.logger import Loggers
from utils.telemetry import telemetry

log = Loggers.processor()


class ProcessingService:
    """Service to handle core business logic: Matching -> Notification."""
    
    def __init__(self, bot: ApartmentBot, ai_engine: Optional[GeminiAIEngine] = None):
        self.bot = bot
        self.ai_engine = ai_engine
        self.matcher = ZeroAIUserMatcher()
        self.dispatcher = NotificationDispatcher()
        self.dispatcher.register_provider(TelegramNotificationProvider(bot))
    
    async def process_cycle(self, listings: List[EnrichedListing]):
        """Run matching for new listings against all users."""
        if not listings:
            return
            
        db = await get_db()
        user_repo = UserRepository(db)
        rule_repo = RuleRepository(db)
        
        users = await user_repo.get_all_active()
        log.info(f"Matching {len(listings)} listings against {len(users)} users")
        
        if not users:
            return
            
        # Bulk fetch active rules for all active users
        rules_rows = await db.fetch_all("SELECT * FROM search_rules WHERE is_active = TRUE ORDER BY created_at")
        rules_by_user = {}
        for row in rules_rows:
            rule = rule_repo._row_to_rule(row)
            rules_by_user.setdefault(rule.user_id, []).append(rule)
            
        # Bulk fetch sent notifications only for the listings in this cycle
        listing_ids = [l.listing.id for l in listings]
        sent_pairs = {}  # user_id -> Set[listing_id]
        
        if listing_ids:
            placeholders = ",".join("?" for _ in listing_ids)
            rows = await db.fetch_all(
                f"SELECT user_id, listing_id FROM sent_notifications WHERE listing_id IN ({placeholders})",
                tuple(listing_ids)
            )
            for row in rows:
                u_id = row["user_id"]
                l_id = row["listing_id"]
                sent_pairs.setdefault(u_id, set()).add(l_id)
                
        # Match each user
        for user in users:
            user_rules = rules_by_user.get(user.telegram_id, [])
            user_sent_ids = sent_pairs.get(user.telegram_id, set())
            
            await self.match_user_to_listings(
                user, 
                listings, 
                prefetched_rules=user_rules, 
                prefetched_sent_ids=user_sent_ids
            )
            
        # Clean up screenshots older than the configured threshold (e.g. 24 hours)
        try:
            from utils.screenshot_utils import cleanup_old_screenshots
            cleanup_old_screenshots()
        except Exception as cleanup_err:
            log.warning(f"Error cleaning up old screenshots after cycle: {cleanup_err}")

    async def match_user_to_listings(
        self, 
        user: User, 
        listings: List[EnrichedListing], 
        is_manual_trigger: bool = False,
        include_sent: bool = False,
        prefetched_rules: Optional[List[SearchRule]] = None,
        prefetched_sent_ids: Optional[Set[str]] = None
    ) -> int:
        """Match specific user against listings and notify.
        
        Returns:
            Number of notifications sent.
        """
        db = await get_db()
        rule_repo = RuleRepository(db)
        rejection_repo = RejectionRepository(db)
        notification_repo = NotificationRepository(db)
        user_repo = UserRepository(db)
        
        # Get user rules
        rules = prefetched_rules if prefetched_rules is not None else await rule_repo.get_user_rules(user.telegram_id)
        if not rules:
            return 0
            
        # Filter listings user has already received (unless filtering disabled)
        candidates = listings
        if not include_sent:
            if prefetched_sent_ids is not None:
                candidates = [l for l in listings if l.listing.id not in prefetched_sent_ids]
            else:
                sent_ids = await notification_repo.get_user_sent_ids(user.telegram_id)
                candidates = [l for l in listings if l.listing.id not in sent_ids]
        
        if not candidates:
            return 0
            
        notifications_sent = 0
        sass_for_first = ""
        
        evaluated_count = 0
        match_count = 0
        rejection_count = 0
        
        rejections_to_log = []
        
        for enriched in candidates:
            evaluated_count += 1
            try:
                allow_roomies = getattr(user, 'allow_roomies', True)
                allow_bordering = getattr(user, 'allow_bordering_neighborhoods', True)
                
                is_match, reasons = self.matcher.evaluate_listing(
                    enriched, 
                    rules, 
                    allow_bordering=allow_bordering,
                    allow_roomies=allow_roomies
                )
                
                if is_match:
                    # Get sass intro for the first notification only
                    if notifications_sent == 0 and self.ai_engine and not is_manual_trigger:
                        try:
                            persona_name = user.persona if hasattr(user, 'persona') else 'barakush'
                            sass_for_first = await self.ai_engine.get_random_sass(persona=persona_name)
                        except Exception:
                            sass_for_first = ""
                            
                    # Send notification
                    await self._notify_match(
                        user.chat_id, 
                        enriched, 
                        sass_intro=sass_for_first if notifications_sent == 0 else ""
                    )
                    
                    # Mark sent
                    await notification_repo.mark_sent(user.telegram_id, enriched.listing.id)
                    match_count += 1
                    notifications_sent += 1
                    
                else:
                    # Build detailed description of where the listing actually is
                    actual_parts = []
                    if enriched.extracted_neighborhood:
                        actual_parts.append(enriched.extracted_neighborhood)
                    if enriched.extracted_street:
                        actual_parts.append(enriched.extracted_street)
                    
                    city_or_loc = enriched.extracted_location or enriched.listing.location
                    if city_or_loc and city_or_loc not in actual_parts:
                        actual_parts.append(city_or_loc)
                    
                    actual_loc = ", ".join(actual_parts) if actual_parts else (enriched.extracted_location or enriched.listing.location or "לא ידוע")
 
                    # Determine match method
                    match_method = "attribute"
                    if not allow_roomies and enriched.roomies:
                        match_method = "roomies_filter"
                    
                    rejections_to_log.append({
                        "listing_id": enriched.listing.id,
                        "user_id": user.telegram_id,
                        "failed_rules": reasons.failed_rules if hasattr(reasons, "failed_rules") else [r.value for r in rules],
                        "reasons": reasons,
                        "listing_url": enriched.listing.url,
                        "listing_price": enriched.extracted_price,
                        "listing_location": actual_loc,
                        "match_method": match_method
                    })
                    rejection_count += 1
                    
            except Exception as e:
                error_msg = str(e)
                if "Chat not found" in error_msg or "Forbidden" in error_msg:
                    log.warning(f"User {user.telegram_id} blocked the bot or was deleted. Removing user.")
                    await user_repo.delete_user(user.telegram_id)
                    break # Stop processing for this user
                log.error(f"Error processing listing logic {enriched.listing.id}: {e}")
                telemetry.track_error("processor", type(e).__name__)
                rejection_count += 1
                continue
        
        # Batch log rejections
        if rejections_to_log:
            await rejection_repo.log_many_rejections(rejections_to_log)
        
        # Mark first notification status for new users
        if notifications_sent > 0 and user.is_new_user:
            await user_repo.mark_first_notification(user.telegram_id)
            
        telemetry.track_matches(evaluated_count, match_count, rejection_count)
            
        return notifications_sent

    async def _notify_match(self, chat_id: int, enriched: EnrichedListing, sass_intro: str = ""):
        """Send match notifications across registered providers."""
        await self.dispatcher.dispatch(
            chat_id=chat_id,
            enriched=enriched,
            sass_intro=sass_intro
        )
