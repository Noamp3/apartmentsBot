# Israel Apartment Hunt Bot — AI-Assisted Full-Stack System

## AI Project Presentation

---

## 1. Executive Summary

### The Problem

Finding an apartment in Tel Aviv is miserable. Listings are scattered across dozens of Hebrew-language Facebook groups where brokers and landlords post in colloquial slang, and across Yad2 — Israel's dominant classified portal — which deploys aggressive anti-bot defenses. Prices are buried in unstructured text, often disguised or omitted entirely. Broker fees are legally regulated but routinely hidden. And the market moves so fast that by the time you've parsed a promising post, someone else has already signed the lease.

I wanted a system that watches all the feeds I'd normally scroll through, understands what I'm actually looking for, and pings me on Telegram the moment something matches — with personality.

### What I Built

A production-grade, multi-source apartment aggregation system that:

- **Scrapes** listings from live Facebook groups and Yad2 using Playwright with stealth anti-detection, persistent browser sessions, and human-mimicking behaviors (randomized scrolling, mouse movements, variable delays).
- **Enriches** raw Hebrew text through a batch LLM pipeline that extracts structured metadata (price, rooms, neighborhood, parking, elevator, pets, broker fees) in a single pass — then never calls the LLM for that listing again.
- **Matches** users against enriched listings using a zero-AI deterministic matcher that runs in microseconds at zero API cost, scaling to thousands of users without a single additional token.
- **Notifies** users through a Telegram bot with a persistent Hebrew menu system and four distinct AI personas — from a sassy Tel Avivian drag queen (*Barakush*) to a strict German broker (*Yekke Hans*) — each with pre-cached greetings and dynamic sass.
- **Self-heals** when Facebook changes its DOM layout. An autonomous AI agent captures viewport screenshots, sends them alongside cleaned structural HTML to a multimodal Gemini model, synthesizes repaired CSS selectors, validates them in Playwright, retries with progressive negative feedback if the fix fails, and caches working selectors — all without human intervention.

### Architecture at a Glance

```
Facebook Groups ──► Playwright Stealth Scraper ──► Deduplication Engine ──► Batch LLM Enricher
     Yad2       ──► Playwright + Anti-Detection ──┘                              │
                                                                    Enriched Listing Cache (SQLite)
                                                                                 │
                                                              ┌──────────────────┴──────────────────┐
                                                              │                                     │
                                                    Deterministic Pre-Filter              Self-Healing Agent
                                                    (price, rooms, location)         (multimodal LLM + screenshots)
                                                              │
                                                    Zero-AI Attribute Matcher
                                                    (parking, pets, elevator...)
                                                              │
                                                    Telegram Multi-Persona Bot
                                                    (menu system + cached sass)
```

### Outcome

The system runs in production on an OCI cloud instance, scraping three Facebook groups and Yad2 on a 30-minute interval with jitter. It has successfully processed thousands of listings and delivered matches to real users. The test suite spans **82 test functions across 19 files**, including real-LLM integration tests that call live Gemini endpoints.

---

## 2. Development Process: Prompts, Iterations, and Decision Points

This project was built almost entirely through pair-programming with AI coding agents — primarily Antigravity (powered by Gemini) and Claude Code. Rather than treating the agent as an autocomplete tool, I developed a deliberate workflow.

### 2.1 How I Framed Problems for the Agent

Early on, I learned that the quality of what an AI agent produces is directly proportional to how clearly you frame the problem. I adopted a pattern:

1. **Design architecture before code.** Development began with extensive markdown documentation. I brainstormed project requirements with the agent to establish a high-level `system_requirements.md`, then collaborated on a deeply detailed `technical_guide.md` specifying exact data flows, LLM touchpoints, and SQLite caching mechanisms. Only after refining these architectural specs did I give the agent freedom to implement.

2. **Start with the "why," not the "what."** Instead of saying *"add a self-healing module,"* I'd describe the real-world failure: *"When Facebook updates its DOM, the scraper silently collects zero posts. I need a mechanism that detects this and repairs broken selectors using an LLM — but the LLM should never be used to scrape content directly, only to fix the code."* That distinction — fix the code, don't use LLM to scrape — was a critical design constraint that emerged from a back-and-forth conversation with the agent.

3. **Use the agent's planning mode.** For significant features, I'd trigger planning mode and let the agent produce an implementation plan before writing code. I'd review the plan, push back on design decisions, and only approve execution once the approach was sound.

### 2.2 Iterating on Prompts and Outputs

A typical feature evolved across multiple prompts. Self-healing is a representative example:

- First prompt: *"I want to create a self-healing mechanism based on LLM for the Facebook scraper."*
- My refinement after seeing the plan: *"The idea is that the self-healing will fix the code, not use LLM to scrape."*
- Deepening: *"Maybe we should also pass a few screenshots if healing is needed. We should also consider, what are the cases we think healing is needed — not always will it be obvious with an error."*
- Configuration precision: *"In config we should also point exactly the LLM provider and model for the healing."*
- Verification demand: *"I want the self-healing to verify it solved the problem before continuing and repeat until the problem is solved — stop after 10 tries and print an error."*
- Context enrichment: *"Is the prompt for the LLM fixer optimized? Does he get enough context about the page and elements?"*
- Validation: *"Let's create a real test for the self-healing! Do that by building a test where you sabotage the scraping schema and let's see if the workflow works well."*

Each cycle followed the same pattern: **identify a real-world failure → frame the problem → review and refine the proposed solution → execute → verify with tests → dogfood in production → discover the next failure.**

### 2.3 The Enrichment Prompt Lifecycle

The LLM prompts aren't static strings — they're engineering artifacts refined through production failures:

**Iteration 1 — Naive extraction.** The initial prompt asked the LLM to "extract the price and number of rooms from this listing." The model responded conversationally: *"Sure! The price appears to be 5,000 shekels."* Unusable for programmatic parsing.

**Iteration 2 — JSON schema enforcement.** I constrained the output to raw JSON with explicit type annotations. But a new bug emerged: 10-digit Israeli phone numbers starting with `05` (like `0522505694`) were being extracted as rental prices.

**Iteration 3 — Negative guardrails.** I added explicit warnings in Hebrew directly inside the prompt:
```
"price": מספר או null (שים לב: אל תחלץ מספר טלפון בן 10 ספרות כמחיר!)
```
Combined with upstream regex filtering to strip phone numbers before the text reaches the LLM. Two layers of defense.

**Iteration 4 — Range splitting.** Hebrew listings containing *"3-6 חדרים"* (3-6 rooms) need to become two separate rules: `bedrooms_min=3` and `bedrooms_max=6`. But both rules inherited the original text *"3-6 חדרים"* as their display label, creating identical-looking confirmation buttons in Telegram. I added a post-processing heuristic that rewrites labels to *"מינימום 3 חדרים"* and *"מקסימום 6 חדרים"* — a UX fix that no amount of prompt tuning could solve.

**Iteration 5 — Persona isolation.** The LLM generates both structured rule objects and a creative persona response in a single JSON call. This saves a duplicate API call while keeping structural parsing completely isolated from conversational output — they occupy separate keys in the response schema.

### 2.4 Where I Overrode the Agent's Judgment

AI coding agents are remarkably capable, but they have blind spots. Here are moments where my engineering judgment was essential:

- **Silent failures vs. loud errors.** The agent's initial self-healing triggered only on exceptions. I pointed out that Facebook layout changes often don't crash anything; they silently return empty results. I pushed the agent to add heuristic anomaly detection: if 3 consecutive posts fail to extract a URL, date, or author, that's a silent failure pattern that should trigger healing.

- **Screenshot multimodality.** The agent initially captured screenshots purely as a developer audit trail. I asked: *"but were the screenshots sent to the model along with the rest of the data?"* They weren't. I directed the agent to extend the `generate_content` API to accept an optional `image_path` and transmit screenshots as multimodal `types.Part` objects alongside the structural DOM text — dramatically improving selector synthesis accuracy.

- **Verification before caching.** After implementing the self-healing loop, I noticed the system would accept the first LLM-suggested selector without verifying it actually worked. I directed a redesign: the system now validates every proposed selector against the live page, retries up to 10 times with progressive negative feedback (telling the LLM which selectors already failed), and only then caches a proven-working selector.

- **The "benefit of the doubt" matcher design.** When building the zero-AI attribute matcher, the question arose: what happens when a user's custom rule doesn't map to any known attribute keyword? The naive approach would reject the listing. I chose the opposite: if we can't verify the rule, grant the listing the benefit of the doubt and let it through. False positives are far less harmful than false negatives in apartment hunting.

---

## 3. Critical Reflection: Evaluating and Improving AI Output

I don't trust model outputs by default. Every interaction point between an LLM and the rest of the system has a verification layer.

### 3.1 How I Verify AI Outputs

**Structural validation.** Every LLM response is parsed through `_parse_json_response`, which strips markdown code fences, attempts `json.loads`, and falls back to regex extraction of JSON objects from conversational text. If parsing fails entirely, the response is logged and discarded — never silently accepted.

**Playwright verification for selectors.** The self-healing agent doesn't trust the LLM's proposed selector just because the JSON is well-formed. It runs the selector against the live page, counts matched elements, and for date selectors, additionally validates that the matched element's text content actually looks like a timestamp (matching Hebrew and English date patterns). A selector that matches zero elements — or matches the wrong kind of content — is rejected regardless of how reasonable it looks, and the LLM is re-prompted with the failure history.

**Downstream normalization.** When the LLM classifies a Hebrew location like *"פלורנטין או כרם התימנים"* as a `border_area` (geographic boundary) instead of a simple `area` (neighborhood list), the system detects the misclassification by checking for directional keywords (`מערב`, `צפון`, `דרום`, `מזרח`). If none are present, it automatically rewrites the rule type to `area`.

**Negative constraints in prompts.** Rather than hoping the model won't confuse phone numbers with prices, I explicitly tell it not to — in Hebrew, in the prompt, with examples. Defense in depth: the upstream regex strips phone numbers before the text even reaches the model.

### 3.2 Real-World Failures I Caught

- **The phone number price leak.** A 10-digit Israeli phone number (`0522505694`) was extracted as the apartment's monthly rent. Fixed with both upstream regex filtering and explicit prompt guardrails.

- **The border area misclassification.** Compound neighborhood requests (*"לב תל אביב או כרם התימנים"*) were occasionally classified as geographic boundaries instead of simple area rules. Fixed with a downstream normalization check.

- **The silent selector drift.** Facebook changed its DOM without breaking any selectors outright — posts were still found, but timestamps were no longer inside the expected elements. The scraper ran happily, producing listings with no dates, which bypassed the date filter and flooded users with old posts. Fixed by adding consecutive-failure counters for each attribute type.

- **The self-healing prompt format drift.** Early self-healing attempts failed because conversational models would wrap selectors in nested keys like `{"post_url": {"selector": "..."}}` or add preamble text before the JSON block. Fixed with increasingly strict prompt constraints specifying exactly two root-level keys and requiring the response to start with `{` and end with `}`.

---

## 4. Testing Strategy

### 4.1 Test Architecture

The test suite comprises **82 test functions across 19 test files**, organized in three tiers:

```
┌─────────────────────────────────────────────────────────────┐
│                     Pytest Harness                          │
│              asyncio_mode = auto (pytest.ini)               │
├──────────────────┬──────────────────┬───────────────────────┤
│   Unit Tests     │  Integration     │  Real-LLM & E2E      │
│                  │  Tests           │  Tests                │
│  Hebrew regex    │  Deduplication   │  Live Gemini parsing  │
│  Price parsing   │  (in-memory DB)  │  Self-healing sabotage│
│  Location maps   │  Facebook filter │  MessageHandler flow  │
│  Auto-max rooms  │  User lifecycle  │  Real FB group healing│
│  Border regions  │  Date filtering  │                       │
│  Captcha detect  │  AI retry/rotate │                       │
└──────────────────┴──────────────────┴───────────────────────┘
```

**Unit tests** validate isolated logic: Hebrew currency parsing (`5000 ש"ח`, `5k`, `₪5,000` → `5000`), phone number exclusion from prices, bedroom extraction, geographic border lookups, auto-max room heuristics, and scheduler blackout windows.

**Integration tests** mount in-memory SQLite databases and verify stateful workflows: cross-source deduplication (same listing posted to Facebook and Yad2), Facebook post filtering (exchange posts, spam, promotional content), deleted Telegram user handling, and AI engine retry/rotation under simulated 429/500/503 errors.

**Real-LLM tests** call live Gemini endpoints with real Hebrew text and assert structural correctness. `test_hebrew_rules_llm.py` fires 6 real-world user queries through the full parsing pipeline across multiple personas and validates extracted rule types, values, and persona response quality. `test_self_healing_sabotage.py` sabotages selectors and verifies that the actual model heals them correctly — including the retry loop and verification logic.

### 4.2 What I Chose Not to Test (and Why)

**Live network requests to Facebook/Yad2.** Third-party web formats are volatile. A test that passes today might fail tomorrow because Facebook changed a class name — producing a false failure that has nothing to do with my code. I mock all network interactions in the main test suite and maintain separate diagnostic scripts for manual live verification.

**Persona tone quality.** I verify that persona responses are non-empty, contain Hebrew text, and respect length constraints. I don't attempt to evaluate whether *Barakush*'s sass is sufficiently witty — that's a subjective judgment that automated tests can't meaningfully capture.

**Multi-user concurrency.** The bot serves a small number of users on a single machine. I haven't load-tested concurrent Telegram message handling because the real-world usage pattern doesn't warrant it yet.

### 4.3 Bugs My Tests Caught

**The short listing skip bug.** A minimum-length filter (`len(text) < 30`) was silently discarding highly concise but valid listings like *"דירה להשכרה 3 חדרים"* (20 characters). Caught by `test_facebook_filtering.py`.

**The deduplication field gap.** The duplicate detection test was initializing mock listings without `extracted_bedrooms`, causing the `author + price + bedrooms` fingerprint to fail silently. Cross-posted listings slipped through. Caught by `test_duplicate_detection.py` after I noticed duplicates in production logs.

**The self-healing emoji crash.** Unicode emojis (`✅`, `❌`) in log statements crashed the entire test process on Windows terminals using CP1252 encoding. The test runner would exit with a `UnicodeEncodeError` after the LLM had already successfully healed the selector — making it look like healing failed when it actually succeeded. Caught during the sabotage test run.

---

## 5. Demo

### User Registration & Search Rules

The user opens the Telegram bot, hits `/start`, and gets auto-registered with the default *Barakush* persona. They send a free-form Hebrew message:

> **User:** "אני מחפש דירה בתל אביב, לפחות 3 חדרים, עד 6500 שקל, באזור פלורנטין. חייב חניה!"

The LLM parses this into structured rules and responds in-persona:

> **Barakush:** "3 חדרים עם חניה בפלורנטין? 💀 מאמי, באיזה סרט אתה חי, של דיסני? 🦄 אבל יאללה, רשמתי לי."

### Live Match Notification

When a matching listing is scraped:

> **Barakush:** "🏠 מצאתי דירה הורסת בשבילך! 💅
> **מיקום**: פלורנטין, תל אביב
> **חדרים**: 3 | **מחיר**: 6,000₪ (+ תיווך)
> 💰 מחיר כולל תיווך מפורס: 6,500₪
> • יש חניה מסודרת! 🚗
> [לחץ כאן לצפייה בפוסט המקורי בפייסבוק]"

### Self-Healing in Action

When Facebook changes its layout and the scraper stops finding posts:

```
13:28:04 [WARNING] | No posts collected. Attempting self-healing...
13:28:04 [   INFO] | Captured viewport screenshot: logs/healing_post_container.png
13:28:05 [   INFO] | Adding screenshot to Gemini for multimodal analysis
13:28:05 [   INFO] | Attempt 1/10 to heal post_container selector...
13:28:08 [WARNING] | [FAILED] Suggested selector 'div.x1abc2de' failed verification on attempt 1
13:28:08 [   INFO] | Attempt 2/10 to heal post_container selector...
13:28:12 [   INFO] | [SUCCESS] Verified healed container on attempt 2: 'div[role="article"]'
13:28:12 [   INFO] | Retrying collection with healed selector...
13:28:18 [   INFO] | Collected 3 posts successfully
```

No human intervention. No downtime. If the first suggestion fails, the system retries with the failed selector history fed back into the prompt — up to 10 attempts before giving up with a clear error.

---

## 6. Conclusion: How I Think About AI-Assisted Development

Building this project taught me that working effectively with AI coding agents is its own skill — distinct from traditional programming and distinct from prompt engineering for chatbots.

**Frame the problem, not the solution.** The best results came when I described the real-world failure I was experiencing and let the agent propose an architecture. My job was to evaluate the proposal, push back on fragile designs, and add the edge cases the agent wouldn't anticipate.

**The agent writes the code; you own the design.** The self-healing system exists because I identified a category of failure (silent selector drift) and articulated a design constraint (fix the selectors, never use LLM to scrape). The agent implemented it. But the multimodal screenshot integration, the silent failure heuristics, the verification-before-caching loop, the dedicated model configuration — those came from my direction after reviewing what the agent built.

**Verification is non-negotiable.** Every LLM output in this system passes through a verification layer — JSON parsing, Playwright selector validation, downstream normalization, negative prompt constraints. The system trusts the model's creativity but verifies its correctness.

**Test at the boundaries.** The most valuable tests aren't the ones that check happy paths — they're the ones that exercise the boundary between deterministic code and probabilistic AI output. The sabotage test, the real-LLM parsing tests, the fallback flow test — these are where regressions actually hide.

This project demonstrates that AI-assisted development isn't about delegating thinking to the model. It's about combining the model's ability to generate correct code at scale with your own ability to identify what "correct" means in the first place.
