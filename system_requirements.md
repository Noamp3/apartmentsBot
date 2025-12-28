# 🏠 Apartment Search Bot - System Requirements

## Overview

A Telegram bot system for automated apartment hunting in Israel. The bot scrapes listings from Facebook groups and Yad2, filters them based on user-defined rules, and delivers matching apartments directly to users via Telegram.

---

## 🎯 Core Features

### 1. User Registration & Multi-User Support
- Each user/group chat gets independent search profiles
- Users can have multiple active search configurations
- All interactions in **Hebrew**

### 2. Search Rule Configuration

Users can define flexible search criteria through natural conversation:

| Rule Type | Examples |
|-----------|----------|
| **Price** | מקסימום 5000 ש"ח, בין 3000-4500 |
| **Bedrooms** | לפחות 3 חדרים, 2-4 חדרים |
| **Location** | תל אביב, פלורנטין, שכונת התקווה, אזור המרכז |
| **Custom Rules** | Any free-form requirement (see examples below) |

**Custom Rules - AI-Powered Flexibility**:

Users can state ANY requirement in natural Hebrew. The AI interprets and evaluates these dynamically:

| Category | Example Rules |
|----------|---------------|
| **Amenities** | עם מרפסת, יש מעלית, חניה כלולה, מזגן |
| **Floor** | קומה גבוהה, לא קומת קרקע, קומה 3 ומעלה |
| **Building** | בניין חדש, משופץ, לא ישן מ-2010 |
| **Roommates** | מתאים לשותפים, לא דירת סטודנטים |
| **Pets** | מותר כלבים, ידידותי לחיות מחמד |
| **Lifestyle** | שקט, ליד תחבורה ציבורית, קרוב לים |
| **Contract** | חוזה ארוך טווח, גמיש בתאריך כניסה |
| **Landlord** | ישירות מהבעלים, ללא תיווך |

> [!TIP]
> When users add rules the system doesn't recognize, AI automatically interprets their intent and evaluates listings accordingly. No code changes required for new rule types.
- Natural Hebrew conversation support

### 3. Listing Sources

| Source | Description |
|--------|-------------|
| **Facebook Groups** | Israeli apartment rental groups |
| **Yad2** | Israel's leading real estate platform |

### 4. Automated Scanning
- Continuous scanning every few minutes
- Stealth scraping methods to avoid detection/blocking
- Duplicate detection to prevent repeated notifications

### 5. Notification System
- Instant Telegram notifications for matching apartments
- Rich message format with:
  - Price
  - Location
  - Number of rooms
  - Link to original listing
  - Key details extracted by AI

### 6. Rejection Logging
- Clear log of apartments that **failed** to match rules
- Each rejection includes:
  - The listing details
  - Which rule(s) failed
  - Reason for rejection
- Allows users to verify filtering accuracy

---

## 👤 User Workflows

### Initial Setup
```
1. User starts bot → /start
2. Bot greets in Hebrew and asks for preferences
3. User states rules naturally: "אני מחפש דירה בתל אביב עד 5000 ש"ח, 3 חדרים לפחות"
4. Bot confirms understanding and begins monitoring
```

### Rule Modification
```
1. User sends update: "תשנה את המחיר המקסימלי ל-6000"
2. Bot confirms change
3. New rules take effect immediately
```

### Viewing Rejections
```
1. User requests: "הראה לי דירות שנפסלו"
2. Bot displays recent rejections with reasons
```

---

## 📋 Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-01 | Support multiple concurrent users with isolated search profiles |
| FR-02 | Parse and understand Hebrew rule definitions via AI |
| FR-03 | Scrape Facebook groups without triggering bot detection |
| FR-04 | Scrape Yad2 listings reliably |
| FR-05 | Match listings against user rules with AI judgment |
| FR-06 | Send formatted Telegram notifications for matches |
| FR-07 | Log all rejected listings with clear rejection reasons |
| FR-08 | Allow real-time rule modifications |
| FR-09 | Support area-based filtering using AI interpretation |
| FR-10 | Handle custom/freeform search rules |

---

## ⚡ Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| **Performance** | Scan cycle every 3-5 minutes |
| **Reliability** | Graceful handling of scraping failures |
| **Scalability** | Support 10-20 concurrent users |
| **Usability** | Natural Hebrew conversation interface |
| **Maintainability** | Clean Python OOP codebase |

---

## 🔒 Constraints

- Must use **Gemini 2.5 Flash** as the AI engine
- Must implement anti-detection measures for Facebook scraping
- All user-facing text must be in **Hebrew**
- Must comply with Telegram Bot API guidelines

---

## 📊 Success Criteria

1. Users receive relevant apartment notifications within 10 minutes of posting
2. Less than 10% false positive rate (irrelevant matches)
3. Less than 5% false negative rate (missed valid listings)
4. Zero detection/blocking incidents over 30-day period
5. Average response time < 2 seconds for rule changes
