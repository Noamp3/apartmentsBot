# 🏠 Apartment Search Bot - System Requirements

## Overview

A Telegram bot system for automated apartment hunting in Israel. The bot scrapes listings from Facebook groups and Yad2, filters them based on user-defined rules, and delivers matching apartments directly to users via Telegram. It utilizes AI for natural language processing, rule extraction, roommate filtering, and listing enrichment.

---

## 🎯 Core Features

### 1. User Registration & Onboarding
*   **Multi-User Isolation**: Each user or group chat has an independent search profile and configuration saved in the SQLite database.
*   **Interactive Onboarding Wizard**: A step-by-step onboarding flow for new users:
    1.  **Welcome**: Dynamic welcome message asking for desired locations/neighborhoods.
    2.  **Budget**: Prompt asking for the maximum monthly budget in NIS.
    3.  **Rooms**: Prompt asking for bedroom requirements (e.g., minimum room count).
*   **Onboarding Bypass**: If a user inputs a composite message containing multiple requirements (e.g., *"דירה בפלורנטין עד 5000 ש"ח לפחות 3 חדרים"*), the AI parser extracts all rules simultaneously, bypasses the step-by-step flow, and immediately completes onboarding.
*   **Hebrew Interface**: All user-facing communications, commands, and options are in Hebrew.

### 2. Search Rule Configuration & AI Matching
Users define search criteria through natural language. The system splits rules into distinct types:

| Rule Type | DB Key | Examples & Hebrew Syntax | Description |
| :--- | :--- | :--- | :--- |
| **Price Max** | `price_max` | מקסימום 5000 ש"ח, עד 6000 שקלים | Upper limit for monthly rent (processed as NIS). |
| **Price Min** | `price_min` | לפחות 3000 ש"ח, מעל 4000 | Lower limit for monthly rent (processed as NIS). |
| **Bedrooms Min** | `bedrooms_min` | 3 חדרים ומעלה, לפחות 2.5 חדרים | Minimum number of rooms. |
| **Bedrooms Max** | `bedrooms_max` | מקסימום 4 חדרים, עד 3 חדרים | Maximum number of rooms. |
| **Location** | `area` | תל אביב, פלורנטין, שכונת התקווה | Target cities or neighborhoods. |
| **Border Area** | `border_area` | מערבית לאיילון, דרומית לארלוזורוב | Custom geofenced borders parsed by AI. |
| **Custom Rules** | `custom` | עם מרפסת, יש מעלית, חניה כלולה, מותר כלבים | Free-form amenities, contract types, or requirements. |

*   **AI-Powered Matcher**: Standard filters (price, rooms, location) are evaluated deterministically using database values. Custom rules (amenities, floor, building age, roommates, lifestyle) are evaluated using Gemini AI to read listing texts and determine compliance, providing explanations for any decisions.
*   **Neighboring Neighborhoods (שכונות גובלות)**: Users can toggle bordering neighborhood expansion. When enabled (`allow_bordering_neighborhoods = True`), location matches are automatically expanded to adjacent areas using predefined location mapping (e.g., matching Shapira when a user asks for Florentin).
*   **Roommate Listings Filter (דירות שותפים)**: Users can toggle roommate listings search (`allow_roomies = True/False`).
    *   *AI Roommate Enrichment*: The parser identifies if a listing is for a roommate search (e.g., room rental, flatmate wanted) and labels it `roomies: true`.
    *   *Strict Identification*: Descriptive terms like *"מתאים לשותפים"* (suitable for roommates) are classified as `roomies: false` (full apartment) unless the post explicitly seeks a new flatmate.
    *   *Filtering*: If `allow_roomies` is disabled, roommate listings are automatically filtered out.

### 3. Broker Fee Calculation (תיווך)
*   **Effective Price Matching**: The bot detects if a listing has a broker fee (`תיווך`).
*   **Amortization**: If a broker fee is present, the bot calculates an *effective monthly price* by distributing the standard 1-month fee over a 12-month period:
    $$\text{Effective Monthly Price} = \text{Rent} + \left(\frac{\text{Rent}}{12}\right)$$
*   **Price Threshold Validation**: The effective monthly price is matched against the user's maximum budget rule to prevent users from being surprised by hidden broker fees.
*   **Rich Notification Note**: Displays a breakdown of the calculation in matching notifications:
    *Example: `💰 מחיר כולל תיווך מפורס: 5,417₪ (שכירות 5,000₪ + 417₪/חודש דמי תיווך)`*

### 4. Supported AI Personas
Users can dynamically switch the bot's response and notification style using the `/persona` command. The bot supports four distinct, highly expressive personalities:

1.  **💅 Barakush (ברקוש)**: A sassy, dramatic, and humorous Tel Avivian. Uses heavy LGBT slang (*"נשמה", "חיים שלי", "לירלור", "וודג'"*), makes playful/provocative roasts about budgets, and leaves funny, sexually-suggestive notes or Grindr jokes.
2.  **💼 Yekke Broker (הברוקר הייקה)**: A strict, orderly, and highly-professional German agent. Demands structure (*"Ordnung muss sein!"*), speaks in clean, formal Hebrew mixed with German words (*"Sehr gut", "Nein", "Guten Tag"*), and criticizes shoddy Israeli renovations or bad financial planning.
3.  **👵 Grandma/Polish Mom (האמא הפולנייה)**: An overprotective, guilt-tripping, and dramatic Jewish mother. Focuses on security (bomb shelters/ממ"ד), building safety, eating hot meals, and constantly complains that the user doesn't call enough or spends too much money on Tel Aviv rent.
4.  **🤙 Chill Stoner (הסטלן השאנטי)**: A super-relaxed, friendly hipster. Speaks in a warm, slow vibe (*"אחי", "גבר", "סבבה", "אנרגיות טובות"*), values balconies, natural light for "plants", and hammocks, and tells users to take life easy.

### 5. Automated Scanning & Scraper Sources
*   **Sources**:
    *   **Facebook Groups**: Scrapes Israeli apartment rental and roommate groups.
    *   **Yad2**: Scrapes Israel's main real estate site.
*   **Deduplication**: Hashes URLs and listing details to log seen posts in `seen_listings`, preventing duplicate notifications.
*   **Anti-Blocking Measures**: Uses stealth browser configurations and headless crawling scripts to prevent rate limiting or blockades.

### 6. Rejection Logging (Transparency Tool)
*   **Log Verification**: Every scraped apartment that fails to match a user's criteria is recorded in the `rejection_logs` database table.
*   **Detailed Explanations**: Rejection logs store the failed listing, the specific rule that triggered the failure (e.g., budget exceeded, location mismatch), and a clear reason.
*   **Self-Calibration**: Users can type `/rejections` to view recent failed listings and see exactly why they did not receive them, helping them adjust rules if they are too restrictive.

### 7. Administrator Dashboards & Tools
Administrators (indicated by `is_admin = True` in the database) have access to a rich set of management commands:

*   **Interactive Panel (`/admin`)**: A dashboard showing general database stats (total users, active users, rule counts, database file size, scrape counts) with interactive menus:
    *   **User Auditing (`/admin_users`)**: Lists all registered users, their selected persona, active status, and lists all their defined search rules and matched count.
    *   **System Log Viewer (`/admin_logs`)**: Checks the server error log, prints an error count summary, displays details of the 5 most recent exceptions, and sends the full error log file as a `.txt` attachment.
    *   **Broadcast Tool (`/admin_broadcast [message]`)**: Sends a system-wide announcement to all registered active bot users.
    *   **Manual Crawler (`/admin_scrape`)**: Immediately triggers a manual scraping cycle.
    *   **Interactive Facebook Login (`/admin_fb_login`)**: Launches a Playwright browser session on the server in order to log into Facebook. The admin receives screenshots of the browser directly in Telegram and replies with commands (`click`, `tap`, `type`, `select`, `enter`, `done`, `cancel`) to bypass CAPTCHAs, enter 2FA codes, or select reCAPTCHA grid tiles (e.g., typing `2 5 6 9`).

---

## 👤 User Workflows

### 1. Initial Setup & Onboarding
```
1. User joins bot and triggers `/start`.
2. Bot prompts the user to select an AI persona (defaults to Barakush).
3. Bot greets in the persona's style and asks: "איפה תרצה לחפש דירה?" (onboarding_step: ask_location).
4. User responds: "פלורנטין או לב העיר".
5. Bot confirms, saves locations, and asks: "מה התקציב שלך?" (onboarding_step: ask_budget).
6. User responds: "5000 ש"ח".
7. Bot saves price_max=5000, and asks: "כמה חדרים?" (onboarding_step: ask_bedrooms).
8. User responds: "לפחות 2.5 חדרים".
9. Bot saves bedrooms_min=2.5, clears onboarding_step, and starts scanning.
```

### 2. Fast-Track Setup (Bypassing Onboarding)
```
1. User joins bot and triggers `/start`.
2. User immediately sends: "אני מחפש דירה בפלורנטין עד 6000 שקלים, לפחות 3 חדרים, עם מרפסת ומותר כלבים".
3. AI parser extracts rules: area=פלורנטין, price_max=6000, bedrooms_min=3, custom="עם מרפסת", custom="מותר כלבים".
4. Bot saves all rules, sets onboarding_step to None, and displays the active rules list.
```

### 3. Rule Customization
```
1. User types `/rules` to see active filters.
2. User types: "תמחק את הדרישה למרפסת ותשנה מחיר ל-5500".
3. AI parser updates rules: deletes custom="עם מרפסת", updates price_max=5500.
4. Bot prints the updated list of rules.
5. User clicks the inline button "❌ השבת דירות שותפים".
6. allow_roomies is set to False; roommate ads are now filtered.
```

---

## 📋 Functional Requirements

| ID | Description |
| :--- | :--- |
| **FR-01** | Support multiple concurrent users with isolated search profiles. |
| **FR-02** | Parse Hebrew rule definitions, extraction of ranges, price, bedrooms, locations, and custom filters. |
| **FR-03** | Auto-detect and bypass step-by-step onboarding if a multi-rule message is sent. |
| **FR-04** | Match apartments against user rules utilizing deterministic database checks and AI custom evaluations. |
| **FR-05** | Support area expansion through dynamic bordering/neighboring neighborhoods mapping. |
| **FR-06** | Enforce roommate/flatmate filtering using AI identification, distinguishing room rentals from roommate-friendly apartments. |
| **FR-07** | Detect broker fees and match listings using an amortized effective monthly price. |
| **FR-08** | Support four distinct AI personas (Barakush, Yekke, Polish Mom, Stoner) with custom welcome states, rules confirmation, and matching commentary. |
| **FR-09** | Log all rejected listings with failed rules and reasons, and allow users to view them via `/rejections`. |
| **FR-10** | Provide an admin dashboard displaying users count, rules count, database size, and logs. |
| **FR-11** | Allow administrators to review all users, their rules, and matched listings. |
| **FR-12** | Implement an interactive Facebook login session via Telegram screenshot feedback and browser control commands. |
| **FR-13** | Allow admins to trigger manual scrapes and broadcast messages to all active users. |

---

## ⚡ Non-Functional Requirements

*   **Reliability**: Scraper fails and database bottlenecks must be handled gracefully without crashing the bot service.
*   **Performance**: Scraper cycle triggers every 3-5 minutes. Notifications must arrive within 10 minutes of being scraped.
*   **Scalability**: Supports 20+ concurrent users with active search profiles on lightweight server instances.
*   **Maintainability**: Clean Python Object-Oriented design, separating scraper engines, AI parsers, repositories, and command handlers.

---

## 🔒 Constraints

*   Uses **Gemini 2.5 Flash** as the default LLM engine for text parsing and extraction.
*   Must comply with Telegram Bot API specifications (e.g., MarkdownV2 escaping, message length limits).
*   All user interaction must be in Hebrew.
*   Facebook scraping requires stealth web crawlers (Playwright/Stealth) to bypass login checkpoints.
