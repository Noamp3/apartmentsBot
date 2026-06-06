# tests/test_agentic_bot_evaluation.py
"""Comprehensive agentic E2E integration test where LLM agents act as users and judge the bot."""

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
from scrapers.yad2_playwright_scraper import Yad2PlaywrightScraper
from bot.telegram_bot import ApartmentBot
from core.processing import ProcessingService

# Register custom llm marker and skip if GEMINI_API_KEY is not set
pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not settings.GEMINI_API_KEY,
        reason="Skipping agentic E2E test: GEMINI_API_KEY is not set in environment or .env file."
    )
]

# Real Yad2 NextData HTML mockup structure containing Florentin and Kerem HaTeimanim listings
MOCK_YAD2_HTML = """
<!DOCTYPE html>
<html>
<head><title>דירות להשכרה - יד2</title></head>
<body>
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "dehydratedState": {
            "queries": [
              {
                "state": {
                  "data": {
                    "private": [
                      {
                        "token": "yad2_token_florentin_e2e",
                        "adType": "private",
                        "address": {
                          "city": {"text": "תל אביב"},
                          "neighborhood": {"text": "פלורנטין"},
                          "street": {"text": "העליה"},
                          "house": {"number": "30", "floor": 2}
                        },
                        "price": "5,500 ש\\\"ח",
                        "additionalDetails": {
                          "roomsCount": 3,
                          "squareMeter": 75
                        },
                        "metaData": {
                          "images": ["https://img.yad2.co.il/Pic/202606/06/1.jpg"]
                        }
                      },
                      {
                        "token": "yad2_token_kerem_e2e",
                        "adType": "private",
                        "address": {
                          "city": {"text": "תל אביב"},
                          "neighborhood": {"text": "כרם התימנים"},
                          "street": {"text": "גאולה"},
                          "house": {"number": "10", "floor": 1}
                        },
                        "price": "4,800 ש\\\"ח",
                        "additionalDetails": {
                          "roomsCount": 2,
                          "squareMeter": 50
                        },
                        "metaData": {
                          "images": ["https://img.yad2.co.il/Pic/202606/06/2.jpg"]
                        }
                      }
                    ]
                  }
                }
              }
            ]
          }
        }
      }
    }
    </script>
</body>
</html>
"""



class SimulatedLLMUser:
    """Represents a simulated LLM user navigating the onboarding flow and receiving matches."""
    
    def __init__(self, telegram_id: int, username: str, persona: str, target_desc: str, style_desc: str):
        self.telegram_id = telegram_id
        self.username = username
        self.persona = persona
        self.target_desc = target_desc
        self.style_desc = style_desc
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
    print("\n--- Starting E2E Agentic Bot Evaluation ---")
    
    # 1. Setup Isolated In-Memory Database
    db_manager = DatabaseManager(db_url="sqlite:///:memory:")
    await db_manager.initialize()
    
    # 2. Write Mock HTML Yad2 Page to Temp File
    mock_html_file = tmp_path / "mock_yad2_e2e.html"
    with open(mock_html_file, "w", encoding="utf-8") as f:
        f.write(MOCK_YAD2_HTML)
    
    mock_html_url = mock_html_file.as_uri()
    print(f"Mock HTML path created: {mock_html_url}")
    
    # 3. Create Scraper & Patch for Local File navigation
    # Force headless mode during test
    with patch("config.settings.HEADLESS_MODE", True):
        scraper = Yad2PlaywrightScraper(max_pages=1, max_listings=5)
        # Patch full URL building to return local file URI
        scraper._build_full_url = lambda params: mock_html_url
        
        # Execute real scraping (runs Playwright headlessly on local HTML file)
        print("Running scraper on mock local HTML...")
        listings = await scraper.scrape()
        
    assert len(listings) == 2, f"Should have scraped 2 listings, got {len(listings)}"
    print(f"Scraped 2 listings successfully. Listing 1: {listings[0].title}, Listing 2: {listings[1].title}")
    
    # 4. Initialize AI Engines
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
    
    # 5. Enrich Scraped Listings using Real AI Enricher
    from core.ai_engine import ListingEnricher
    enricher = ListingEnricher(chat_ai)
    print("Enriching listings via AI...")
    enriched_listings = await enricher.enrich_listings(listings)
    assert len(enriched_listings) == 2
    
    # Save enriched listings to the DB
    listing_repo = ListingRepository(db_manager)
    for enriched in enriched_listings:
        await listing_repo.save_enriched(enriched)
    print("Saved enriched listings to DB.")
    
    # 6. Initialize Bot and Simulated Users
    bot = ApartmentBot(ai_engine=chat_ai)
    await bot.setup()
    
    user_repo = UserRepository(db_manager)
    rule_repo = RuleRepository(db_manager)
    
    # Create 2 Simulated User Agents
    shir = SimulatedLLMUser(
        telegram_id=11111111,
        username="שיר (Shir)",
        persona="barakush",
        target_desc="3-room apartment in Florentin, Tel Aviv with budget up to 6,000 NIS. Speak casually.",
        style_desc="Casual Israeli student, using slang and typing in standard step-by-step Hebrew."
    )
    
    arnon = SimulatedLLMUser(
        telegram_id=22222222,
        username="ארנון (Arnon)",
        persona="yekke",
        target_desc="2-room apartment in Kerem HaTeimanim, Tel Aviv for up to 5,000 NIS.",
        style_desc="Professional, polite, wants to test direct multi-rule onboarding by combining everything into one single input."
    )
    
    users = [shir, arnon]
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
    
    # 7. Run Simulated Onboarding Loop
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
    
    # 8. Run Matching Engine Processing Cycle
    print("\n--- Running Matcher Cycle ---")
    processing_service = ProcessingService(bot, chat_ai)
    
    # Patch get_db to return our test database during the cycle
    with patch("database.get_db", return_value=db_manager), \
         patch("database.connection.get_db", return_value=db_manager), \
         patch("core.processing.get_db", return_value=db_manager):
         
         await processing_service.process_cycle(enriched_listings)
         
    # Verify matches were received by users
    assert len(shir.notifications_received) >= 1, "Shir should have received Florentin listing match"
    assert len(arnon.notifications_received) >= 1, "Arnon should have received Kerem HaTeimanim listing match"
    print("Matches checked and delivered successfully to both users!")
    
    # 9. Generate User Reviews
    print("\n--- Generating User Reviews via LLM ---")
    reviews = {}
    for user in users:
        review = await user.generate_feedback(chat_ai)
        reviews[user.username] = review
        print(f"\nFeedback from {user.username}:\n{review}")
        
    # 10. Judge compiles Evaluation Report (using self-healing provider)
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
We completed an E2E test of the Israeli Apartment Search Bot using simulated LLM users.
Here is the raw conversation logs and feedback reviews compiled from the test:

{compiled_inputs}

Analyze this data and compile a comprehensive evaluation report in Markdown.
The report must include:
1. Executive Summary: Overall success rate and bot rating (out of 5 stars).
2. Onboarding Evaluation: How well did the bot parse Hebrew inputs into structured rules? Assess step-by-step onboarding vs direct multi-rule onboarding.
3. Notification & Matching Evaluation: Were listings correctly matched and formatted?
4. Tone & Persona Evaluation: Did the bot maintain its sassy (Barakush) or professional (Yekke) persona?
5. Identified Issues & Bugs: Highlight any bugs, awkward formatting, or issues reported by the users or visible in the logs.
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
    
    # Clean up database
    await db_manager.close()
    
    assert report_file.exists(), "Final report file was not written."
