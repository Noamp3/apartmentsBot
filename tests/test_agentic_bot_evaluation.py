# tests/test_agentic_bot_evaluation.py
"""Comprehensive agentic E2E integration test running against the real database."""

import os
import json
import pytest
import asyncio
import pathlib
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

from telegram import Update, User as TGUser, Chat as TGChat, CallbackQuery
from telegram.ext import ContextTypes

from config import settings, AIProvider
from core.ai_engine import create_ai_engine
from database.connection import DatabaseManager, get_db
from database.repositories import (
    UserRepository, 
    RuleRepository, 
    ListingRepository, 
    SeenListingsRepository
)
from models.search_rule import SearchRule, RuleType
from models.listing import Listing, EnrichedListing
from bot.telegram_bot import ApartmentBot
from core.processing import ProcessingService
from utils.israeli_locations import get_location_db

# Register custom llm marker and skip if GEMINI_API_KEY is not set
pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not settings.GEMINI_API_KEY,
        reason="Skipping agentic E2E test: GEMINI_API_KEY is not set in environment or .env file."
    )
]


class SimulatedLLMUser:
    """Represents a simulated LLM user navigating the onboarding flow and receiving matches."""
    
    def __init__(self, telegram_id: int, username: str, persona: str, target_desc: str, style_desc: str, allow_roomies: bool = True, allow_bordering_neighborhoods: bool = True):
        self.telegram_id = telegram_id
        self.username = username
        self.persona = persona
        self.target_desc = target_desc
        self.style_desc = style_desc
        self.allow_roomies = allow_roomies
        self.allow_bordering_neighborhoods = allow_bordering_neighborhoods
        self.chat_history = []
        self.notifications_received = []

    async def generate_response(self, ai_engine, current_step: str) -> str:
        """Use default AI provider to write the Hebrew response based on step and goals."""
        prompt = f"""
You are simulating a real apartment seeker named '{self.username}' interacting with a Telegram search bot.
Bot Personality/Tone you selected: '{self.persona}'.
Your Style: {self.style_desc}.
Your Search Goal: {self.target_desc}.

The bot is currently asking you for your: '{current_step}'.
Please write a short response in Hebrew, behaving in character.
Only reply with the raw text to send to the bot. Do not add quotes, markdown formatting, or extra explanations.

Guidelines per step:
- If current_step is "ask_location": specify your target locations/neighborhoods.
- If current_step is "ask_budget": specify your monthly budget limit.
- If current_step is "ask_bedrooms": specify how many rooms you need.

Note:
If current_step is "ask_location" and you want to test the bot's direct completion capability, you may combine all your criteria (location, budget, rooms) in a single Hebrew sentence, e.g., "אני מחפש דירה בפלורנטין של שלושה חדרים עד 6000 שח".
"""
        response = await ai_engine.generate_content(prompt)
        return response.strip()

    async def generate_feedback(self, ai_engine) -> str:
        """Use default AI provider to write a review of the experience."""
        convo_lines = [f"{speaker}: {msg}" for speaker, msg in self.chat_history]
        convo_str = "\n".join(convo_lines)
        
        notif_str = "\n".join(self.notifications_received) if self.notifications_received else "None"
        
        prompt = f"""
You are the user '{self.username}' with search goal '{self.target_desc}'.
You just finished interacting with the Apartment Search Bot.

Here is the log of your conversation:
{convo_str}

Here are the matched listing notifications you received:
{notif_str}

Evaluate your experience. Did the bot understand your Hebrew inputs correctly? Were the rules correctly configured in the database? Did you get the matches you expected? How did you like the bot's persona/replies ({self.persona})?
Write a candid, realistic feedback review in English. Report any bugs, awkward formatting, or issues you disliked.
"""
        response = await ai_engine.generate_content(prompt)
        return response.strip()


async def simulate_telegram_interaction(user: SimulatedLLMUser, message_text: str, bot: ApartmentBot, db_manager: DatabaseManager, context_mock: MagicMock, record_bot_reply):
    """Simulates sending a text command or message to the bot's handlers."""
    update_mock = MagicMock(spec=Update)
    user_mock = MagicMock(spec=TGUser)
    user_mock.id = user.telegram_id
    user_mock.username = user.username
    user_mock.first_name = user.username
    chat_mock = MagicMock(spec=TGChat)
    chat_mock.id = user.telegram_id
    
    update_mock.effective_user = user_mock
    update_mock.effective_chat = chat_mock
    
    async def mock_reply_text(text, *args, **kwargs):
        record_bot_reply(user.telegram_id, text)
        return MagicMock()
        
    message_mock = MagicMock()
    message_mock.text = message_text
    message_mock.reply_text = AsyncMock(side_effect=mock_reply_text)
    update_mock.message = message_mock
    
    with patch("bot.handlers.message_handler.get_db", return_value=db_manager), \
         patch("bot.handlers.command_handler.get_db", return_value=db_manager), \
         patch("bot.handlers.callback_handler.get_db", return_value=db_manager):
         
         if message_text.startswith("/"):
             cmd = message_text.split()[0][1:]
             if cmd == "start":
                  await bot.command_handler.start(update_mock, context_mock)
         else:
             await bot.message_handler.handle_message(update_mock, context_mock)


async def simulate_callback_query(user: SimulatedLLMUser, callback_data: str, bot: ApartmentBot, db_manager: DatabaseManager, context_mock: MagicMock, record_bot_reply):
    """Simulates clicking an inline keyboard button."""
    update_mock = MagicMock(spec=Update)
    user_mock = MagicMock(spec=TGUser)
    user_mock.id = user.telegram_id
    user_mock.username = user.username
    chat_mock = MagicMock(spec=TGChat)
    chat_mock.id = user.telegram_id
    
    update_mock.effective_user = user_mock
    update_mock.effective_chat = chat_mock
    
    async def mock_edit_message_text(text, *args, **kwargs):
        record_bot_reply(user.telegram_id, text)
        return MagicMock()
        
    query_mock = MagicMock(spec=CallbackQuery)
    query_mock.data = callback_data
    query_mock.from_user = user_mock
    query_mock.answer = AsyncMock()
    query_mock.edit_message_text = AsyncMock(side_effect=mock_edit_message_text)
    update_mock.callback_query = query_mock
    
    with patch("bot.handlers.callback_handler.get_db", return_value=db_manager):
        await bot.callback_handler.handle_callback(update_mock, context_mock)


@pytest.mark.asyncio
async def test_agentic_bot_evaluation(tmp_path):
    """Comprehensive agentic E2E integration test: LLMs act as users and judge the bot."""
    print("\n--- Starting E2E Agentic Bot Evaluation against Real DB ---")
    
    # 1. Setup Real Database Manager
    print("Using production/actual database...")
    db_manager = DatabaseManager(db_url=settings.DATABASE_URL)
    await db_manager.initialize()
    
    user_repo = UserRepository(db_manager)
    rule_repo = RuleRepository(db_manager)
    listing_repo = ListingRepository(db_manager)
    
    try:
        # 2. Initialize AI Engines
        # Default AI Engine for simulated users and bot chat interaction
        chat_ai = create_ai_engine(
            provider=settings.chat_provider,
            api_key=settings.chat_api_key,
            model_name=settings.chat_model
        )
        
        # Healing/Judge AI Engine
        judge_provider = settings.SELF_HEALING_AI_PROVIDER or AIProvider.GEMINI
        judge_model = settings.SELF_HEALING_MODEL or "gemma-4-31b-it"
        judge_api_key = settings.get_provider_api_key(judge_provider)
        
        print(f"Default Chat AI Engine: {settings.chat_provider.value} ({settings.chat_model})")
        print(f"Healing/Judge AI Engine: {judge_provider.value} ({judge_model})")
        
        judge_ai = create_ai_engine(
            provider=judge_provider,
            api_key=judge_api_key,
            model_name=judge_model
        )
        
        # 3. Load actual listings from remote/local real DB
        print("Loading actual listings from real DB...")
        db_listings_raw = await listing_repo.get_recent(limit=20)
        assert len(db_listings_raw) >= 3, f"Real database must contain at least 3 recent listings for this E2E test, found {len(db_listings_raw)}"
        print(f"Loaded {len(db_listings_raw)} actual listings successfully.")
        
        # Re-enrich listings using the updated logic/prompt to avoid stale DB values
        print("Re-enriching listings using current AI engine rules...")
        from core.ai_engine import ListingEnricher
        enricher = ListingEnricher(chat_ai)
        raw_listings = [e.listing for e in db_listings_raw]
        db_listings = await enricher.enrich_listings(raw_listings)
        print(f"Successfully re-enriched {len(db_listings)} listings.")
        
        # Save the re-enriched listings back to the database to overwrite stale database entries
        print("Saving fresh enriched listings back to DB to overwrite stale entries...")
        for e in db_listings:
             await listing_repo.save_enriched(e)
        
        # 4. Configure user criteria dynamically based on loaded listings to test matching features
        l_shir = db_listings[0 % len(db_listings)]
        l_arnon = db_listings[1 % len(db_listings)]
        l_keren = db_listings[2 % len(db_listings)]
        l_dan = db_listings[3 % len(db_listings)] if len(db_listings) > 3 else db_listings[0]
        
        # Shir -> Roommate filtering test (allow_roomies=False)
        loc_shir = l_shir.extracted_neighborhood or l_shir.extracted_location or "Florentin"
        rooms_shir = l_shir.extracted_bedrooms or 3
        price_shir = l_shir.extracted_price or 6000
        shir_target = f"{rooms_shir}-room apartment in {loc_shir} with budget up to {price_shir + 500} NIS. Full apartment only, absolutely no roommates."
        
        # Arnon -> Broker Fee Amortization Test
        loc_arnon = l_arnon.extracted_neighborhood or l_arnon.extracted_location or "לב העיר"
        rooms_arnon = l_arnon.extracted_bedrooms or 2
        price_arnon = l_arnon.extracted_price or 5000
        # If the listing has a broker fee, set budget limit so it exceeds when amortized, otherwise set budget slightly below rent
        if l_arnon.has_broker_fee:
             budget_arnon = price_arnon + (price_arnon // 24)  # Exceeds when amortized
        else:
             budget_arnon = price_arnon - 200
        arnon_target = f"{rooms_arnon}-room apartment in {loc_arnon} with budget up to {budget_arnon} NIS."
        
        # Keren -> Bordering Neighborhoods Test
        loc_keren = l_keren.extracted_neighborhood or l_keren.extracted_location or "פלורנטין"
        rooms_keren = l_keren.extracted_bedrooms or 3
        price_keren = l_keren.extracted_price or 6000
        bordering_list = get_location_db().get_bordering_neighborhoods(loc_keren)
        if bordering_list:
             search_loc_keren = bordering_list[0]
             print(f"Keren will search in bordering neighborhood '{search_loc_keren}' to match listing in '{loc_keren}'")
        else:
             search_loc_keren = loc_keren
        keren_target = f"{rooms_keren}-room apartment in {search_loc_keren} with budget up to {price_keren + 500} NIS. Bordering areas are OK."
        
        # Dan -> Roommate allowed / roommate seeker matching test
        loc_dan = l_dan.extracted_neighborhood or l_dan.extracted_location or "נווה שאנן"
        rooms_dan = l_dan.extracted_bedrooms or 3
        price_dan = l_dan.extracted_price or 3000
        dan_target = f"room/roommate search in {loc_dan} with budget up to {price_dan + 500} NIS. Roommate flatshares are OK."
        
        # 5. Initialize Bot and Simulated Users
        bot = ApartmentBot(ai_engine=chat_ai)
        await bot.setup()
        
        # Create Simulated User Agents
        shir = SimulatedLLMUser(
            telegram_id=11111111,
            username="שיר (Shir - No Roommates)",
            persona="barakush",
            target_desc=shir_target,
            style_desc="Casual Israeli student, using slang. Bypasses onboarding by sending direct multi-constraint message.",
            allow_roomies=False,
            allow_bordering_neighborhoods=True
        )
        
        arnon = SimulatedLLMUser(
            telegram_id=22222222,
            username="ארנון (Arnon - Broker Fee Test)",
            persona="yekke",
            target_desc=arnon_target,
            style_desc="Professional, polite. Strict budget. Onboards step by step.",
            allow_roomies=False,
            allow_bordering_neighborhoods=True
        )
        
        keren = SimulatedLLMUser(
            telegram_id=33333333,
            username="קרן (Keren - Bordering Area Test)",
            persona="mom",
            target_desc=keren_target,
            style_desc="Polite, protective grandmother. Wants a full apartment, bordering areas are OK.",
            allow_roomies=False,
            allow_bordering_neighborhoods=True
        )
        
        dan = SimulatedLLMUser(
            telegram_id=44444444,
            username="דן (Dan - Roommate Match Test)",
            persona="stoner",
            target_desc=dan_target,
            style_desc="Chill stoner guy. Looking specifically for roommate flatshares.",
            allow_roomies=True,
            allow_bordering_neighborhoods=True
        )
        
        users = [shir, arnon, keren, dan]
        users_dict = {u.telegram_id: u for u in users}
        
        # Callback to log bot responses to user history
        def record_bot_reply(chat_id, text):
            user = users_dict.get(chat_id)
            if user:
                user.chat_history.append(("Bot", text))
                print(f"[{user.username}] Bot: {text}")
                
        # Mock bot's notification sender to capture notifications
        async def mock_send_listing_notification(chat_id: int, enriched: EnrichedListing, bordering_note: str = "", sass_intro: str = ""):
            msg = bot.formatter.format_listing(enriched, bordering_note, sass_intro)
            user = users_dict.get(chat_id)
            if user:
                user.notifications_received.append(msg)
                user.chat_history.append(("Bot Notification", msg))
                print(f"[{user.username}] MATCH NOTIFICATION:\n{msg}")
                
        bot.send_listing_notification = mock_send_listing_notification
        
        # 6. Run Simulated Onboarding Loop
        print("\n--- Starting Simulated Onboarding Dialogues ---")
        
        with patch("database.get_db", return_value=db_manager), \
             patch("database.connection.get_db", return_value=db_manager):
             
             for user in users:
                 print(f"\n--- Onboarding {user.username} ---")
                 
                 # Create TG user record in DB
                 await user_repo.get_or_create(
                     telegram_id=user.telegram_id,
                     chat_id=user.telegram_id,
                     username=user.username
                 )
                 # Set preferences in the DB directly
                 await user_repo.update_allow_roomies(user.telegram_id, user.allow_roomies)
                 await user_repo.update_allow_bordering(user.telegram_id, user.allow_bordering_neighborhoods)
                 await user_repo.update_onboarding_step(user.telegram_id, "choose_persona")
                 
                 context_mock = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
                 context_mock.bot_data = {"ai_engine": chat_ai, "processing_service": None}
                 context_mock.user_data = {}
                 
                 # Send /start
                 user.chat_history.append(("User", "/start"))
                 await simulate_telegram_interaction(user, "/start", bot, db_manager, context_mock, record_bot_reply)
                 
                 db_user = await user_repo.get_by_telegram_id(user.telegram_id)
                 
                 turn = 0
                 while db_user.onboarding_step is not None and turn < 10:
                     turn += 1
                     step = db_user.onboarding_step
                     
                     if step == "choose_persona":
                         callback_data = f"set_persona:{user.persona}"
                         user.chat_history.append(("User Callback", callback_data))
                         await simulate_callback_query(user, callback_data, bot, db_manager, context_mock, record_bot_reply)
                     else:
                         reply = await user.generate_response(chat_ai, step)
                         user.chat_history.append(("User", reply))
                         print(f"[{user.username}] User: {reply}")
                         await simulate_telegram_interaction(user, reply, bot, db_manager, context_mock, record_bot_reply)
                         
                     db_user = await user_repo.get_by_telegram_id(user.telegram_id)
                     
                 print(f"Finished onboarding {user.username} in {turn} turns. Onboarding step is: {db_user.onboarding_step}")
                 
                 # Verify rules were successfully written to DB
                 saved_rules = await rule_repo.get_user_rules(user.telegram_id)
                 assert len(saved_rules) >= 2, f"User {user.username} should have rules saved in database, found {len(saved_rules)}"
                 print(f"Saved {len(saved_rules)} rules for {user.username}: {[f'{r.rule_type.name}: {r.value}' for r in saved_rules]}")
        
        # 7. Run Matching Engine Processing Cycle
        print("\n--- Running Matcher Cycle ---")
        processing_service = ProcessingService(bot, chat_ai)
        
        # Patch get_db to return our test database during the cycle
        with patch("database.get_db", return_value=db_manager), \
             patch("database.connection.get_db", return_value=db_manager), \
             patch("core.processing.get_db", return_value=db_manager):
             
             await processing_service.process_cycle(db_listings)
             
        print("Matches checked and delivered successfully to both users!")
        
        # 8. Generate User Reviews
        print("\n--- Generating User Reviews via LLM ---")
        reviews = {}
        for user in users:
            review = await user.generate_feedback(chat_ai)
            reviews[user.username] = review
            print(f"\nFeedback from {user.username}:\n{review}")
            
        # 9. Judge compiles Evaluation Report (using self-healing provider)
        print("\n--- Compiling Final Judge Evaluation Report ---")
        
        user_data_compiled = []
        for user in users:
            convo_lines = [f"{speaker}: {msg}" for speaker, msg in user.chat_history]
            convo_str = "\n".join(convo_lines)
            review = reviews[user.username]
            user_data_compiled.append(f"""
=== User: {user.username} ===
Persona: {user.persona}
Target Criteria: {user.target_desc}
Conversation Transcript:
{convo_str}
Feedback Review:
{review}
""")
        
        compiled_inputs = "\n".join(user_data_compiled)
        
        judge_prompt = f"""
You are the Agentic E2E Integration Test Judge.
We completed a comprehensive E2E utility test of the Israeli Apartment Search Bot using 4 simulated LLM users representing different feature cases.
Here is the raw conversation logs and feedback reviews compiled from the test:

{compiled_inputs}

Analyze this data and compile a comprehensive evaluation report in Markdown.
The report must focus on:
1. Executive Summary: Overall success rate and bot rating (out of 5 stars).
2. Onboarding & Extraction Evaluation: How well did the bot parse Hebrew inputs into structured rules? Assess step-by-step onboarding vs direct multi-rule onboarding.
3. Utility & Matching Evaluation:
   - **Broker Fee Amortization**: Did the bot correctly block listings that exceed budget when the broker fee is amortized (e.g. rent 5400 + broker = 5850 exceeding 5500 limit)?
   - **Roommate Filtering**: Did the bot successfully filter out room-rent/flatmate listings for users with roommate mode turned off (`allow_roomies = False`), and match them for users seeking roommates?
   - **Bordering Areas**: Did the bordering neighborhoods expansion (`allow_bordering_neighborhoods = True`) match adjacent areas correctly?
   - **Custom Rules**: How accurately did the AI-driven custom rules filter listings (e.g. must allow dogs, must have balcony)?
4. Persona & Tone Evaluation: Assess usability, tone, and character compliance.
5. Identified Issues & Bugs: List any logical or formatting bugs.
6. Recommendations: Actionable steps for improvement.

Use clean, professional Markdown. Do not include extra comments outside the Markdown report.
"""
        
        report_md = await judge_ai.generate_content(judge_prompt)
        
        # Save report to docs/agentic_eval_report.md
        docs_dir = Path("docs")
        os.makedirs(docs_dir, exist_ok=True)
        report_file = docs_dir / "agentic_eval_report.md"
        
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report_md)
            
        print(f"\n✅ Final Judge Report written successfully to: {report_file}")
        assert report_file.exists(), "Final report file was not written."
        
    finally:
        # 10. Clean up database
        print("\n--- Cleaning up Database ---")
        try:
            # Always delete the test users to avoid cluttering remote/production DB
            for u_id in [11111111, 22222222, 33333333, 44444444]:
                await user_repo.delete_user(u_id)
            print("Successfully deleted E2E test users from database.")
        except Exception as e:
            print(f"Error during user cleanup: {e}")
            
        await db_manager.close()
