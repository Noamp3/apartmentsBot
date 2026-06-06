# Apartment Search Bot

טלגרם בוט לחיפוש דירות אוטומטי בישראל

## Setup

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy .env.example to .env and fill in your keys
copy .env.example .env

# Run the bot
python main.py
```

## Configuration

Create a `.env` file with:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
GEMINI_API_KEY=your_gemini_key
DATABASE_URL=sqlite:///apartment_bot.db
```

## Features

- 🏠 Automated apartment hunting from Facebook groups and Yad2
- 🤖 Natural Hebrew conversation for search rules
- 📍 Smart location matching with neighborhood support
- 💰 Broker fee calculation in price matching
- 📋 Rejection logging for transparency

## Running Tests

Test execution is separated so that tests requiring external/real LLM API calls are skipped by default.

```bash
# Run the core test suite (excludes live LLM calls)
.venv\Scripts\pytest

# Run all tests, including those calling live LLMs
.venv\Scripts\pytest --run-llm

# Run only the LLM integration tests
.venv\Scripts\pytest -m llm --run-llm
```

