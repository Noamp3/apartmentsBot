# core/processing.py
"""Service for matching listings to users and sending notifications."""

import asyncio
from typing import List, Dict, Optional

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
from bot.telegram_bot import ApartmentBot
from utils.logger import Loggers

log = Loggers.scheduler()


class ProcessingService:
    """Service to handle core business logic: Matching -> Notification."""
    
    def __init__(self, bot: ApartmentBot, ai_engine: Optional[GeminiAIEngine] = None):
        self.bot = bot
        self.ai_engine = ai_engine
        self.matcher = ZeroAIUserMatcher()
    
    async def process_cycle(self, listings: List[EnrichedListing]):
        """Run matching for new listings against all users."""
        db = await get_db()
        user_repo = UserRepository(db)
        
        users = await user_repo.get_all_active()
        log.info(f"Matching {len(listings)} listings against {len(users)} users")
        
        for user in users:
            await self.match_user_to_listings(user, listings)

    async def match_user_to_listings(
        self, 
        user: User, 
        listings: List[EnrichedListing], 
        is_manual_trigger: bool = False,
        include_sent: bool = False
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
        rules = await rule_repo.get_user_rules(user.telegram_id)
        if not rules:
            return 0
            
        # Filter listings user has already received (unless filtering disabled)
        candidates = listings
        if not include_sent:
            sent_ids = await notification_repo.get_user_sent_ids(user.telegram_id)
            candidates = [l for l in listings if l.listing.id not in sent_ids]
        
        if not candidates:
            return 0
            
        notifications_sent = 0
        sass_for_first = ""
        
        # Generate sass only if we have matches coming
        # We don't know yet if we have matches, so we might generate in vain or generate late.
        # Strategy: Generate on first match found.
        
        for enriched in candidates:
            try:
                is_match, reasons = self.matcher.evaluate_listing(enriched, rules)
                
                if is_match:
                    # Get sass intro for the first notification only
                    if notifications_sent == 0 and self.ai_engine and not is_manual_trigger:
                        # Only auto-sass on scheduled runs or distinct triggers, 
                        # maybe skip on manual rules update to avoid spam?
                        # Actually keeping it adds personality.
                        try:
                            sass_for_first = await self.ai_engine.get_random_sass()
                        except:
                            sass_for_first = ""
                            
                    # Send notification
                    await self._notify_match(
                        user.chat_id, 
                        enriched, 
                        sass_intro=sass_for_first if notifications_sent == 0 else ""
                    )
                    
                    # Mark sent
                    await notification_repo.mark_sent(user.telegram_id, enriched.listing.id)
                    notifications_sent += 1
                    
                else:
                    # Log rejection (only if not a replay)
                    # We might not want to log rejections for manual re-runs to avoid clutter?
                    # But it helps debugging. Let's keep it.
                    await rejection_repo.log_rejection(
                        listing_id=enriched.listing.id,
                        user_id=user.telegram_id,
                        failed_rules=[r.value for r in rules if not is_match],
                        reasons=reasons,
                        listing_url=enriched.listing.url,
                        listing_price=enriched.extracted_price,
                        listing_location=enriched.extracted_location,
                        match_method="attribute"
                    )
                    
            except Exception as e:
                error_msg = str(e)
                if "Chat not found" in error_msg or "Forbidden" in error_msg:
                    log.warning(f"User {user.telegram_id} blocked the bot or was deleted. Removing user.")
                    await user_repo.delete_user(user.telegram_id)
                    break # Stop processing for this user
                log.error(f"Error processing listing logic {enriched.listing.id}: {e}")
                continue
        
        # Mark first notification status for new users
        if notifications_sent > 0 and user.is_new_user:
            await user_repo.mark_first_notification(user.telegram_id)
            
        return notifications_sent

    async def _notify_match(self, chat_id: int, enriched: EnrichedListing, sass_intro: str = ""):
        """Send the actual telegram message."""
        await self.bot.send_listing_notification(
            chat_id=chat_id,
            enriched=enriched,
            sass_intro=sass_intro
        )
