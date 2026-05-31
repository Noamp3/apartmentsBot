# Israel Apartment Hunt Bot — AI-Assisted Full-Stack System

## AI Project Presentation — Claude Code

---

## 1. Executive Summary

### The Problem

Finding an apartment in Tel Aviv is, to put it bluntly, miserable. Listings are scattered across dozens of Hebrew-language Facebook groups where brokers and landlords post in colloquial slang, and across Yad2 — Israel's dominant classified portal — which deploys aggressive Cloudflare-grade anti-bot defenses. Prices are buried in unstructured text, often disguised or omitted entirely. Broker fees are legally regulated but routinely hidden. And the market moves so fast that by the time you've parsed a promising post, someone else has already signed the lease.

I wanted to solve this problem the way I'd want it solved for myself: a system that watches all the feeds I'd normally scroll through, understands what I'm actually looking for, and pings me on Telegram the moment something matches — with personality.

### What I Built

A production-grade, multi-source apartment aggregation system that:

- **Scrapes** listings from live Facebook groups and Yad2 using Playwright with stealth anti-detection, persistent browser sessions, and human-mimicking behaviors (randomized scrolling, mouse movements, variable delays).
- **Enriches** raw Hebrew text through a batch LLM pipeline that extracts structured metadata (price, rooms, neighborhood, parking, elevator, pets, broker fees) in a single pass — then never calls the LLM for that listing again.
- **Matches** users against enriched listings using a zero-AI deterministic matcher that runs in microseconds at zero API cost, scaling to thousands of users without a single additional token.
- **Notifies** users through a Telegram bot with a persistent Hebrew menu system and four distinct AI personas — from a sassy Tel Avivian drag queen (*Barakush*) to a strict German broker (*Yekke Hans*) — each with pre-cached greetings and dynamic sass.
- **Self-heals** when Facebook changes its DOM layout. An autonomous AI agent captures viewport screenshots, sends them alongside cleaned structural HTML to a multimodal Gemini model (`gemma-4-31b-it`), synthesizes repaired CSS selectors, validates them in Playwright, and caches them — all without human intervention.

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

The system runs in production on my personal machine, scraping three Facebook groups and Yad2 on a 30-minute interval with jitter. It has successfully processed thousands of listings, delivered matches to real users, and — during the development of the self-healing feature — autonomously recovered from deliberately sabotaged selectors using a live LLM call against real Facebook DOM. The test suite spans **82 test functions across 19 files**, including real-LLM integration tests that call live Gemini endpoints.

---

## 2. The Development Process: Working with AI Coding Agents

This project was built almost entirely through pair-programming with AI coding agents — primarily Antigravity (powered by Gemini) and Claude Code. Rather than treating the agent as an autocomplete tool, I developed a deliberate workflow that I refined over dozens of sessions. Here's how it actually worked.

### 2.1 How I Structured My Conversations

Early on, I learned that the quality of what an AI agent produces is directly proportional to how clearly you frame the problem. I adopted a pattern:

1. **Design Architecture Before Code.** Development began not with code, but with extensive markdown documentation. I brainstormed the project's requirements with the agent to establish a high-level `system_requirements.md` file. Then, we collaborated on a deeply detailed `technical_guide.md` specifying the exact data flow, LLM touchpoints, and SQLite caching mechanisms. Only after refining these architectural specifications to my exact standards did I give the agent the freedom to begin implementing, with a strict mandate that every component must be rigorously test-backed.

2. **Start with the "why," not the "what."** Instead of saying *"add a self-healing module,"* I'd describe the real-world failure: *"When Facebook updates its DOM, the scraper silently collects zero posts. I need a mechanism that detects this and repairs the broken selectors using an LLM — but the LLM should never be used to scrape content directly, only to fix the code."* That distinction — fix the code, don't use LLM to scrape — was a critical design constraint that emerged from a back-and-forth conversation with the agent.

3. **Use the agent's planning mode.** For significant features, I'd trigger planning mode and let the agent produce an implementation plan artifact before writing any code. I'd review the plan, push back on design decisions (e.g., *"Option A is safer than Option B because it avoids file-write concurrency issues"*), and only approve execution once the approach was sound. This prevented the agent from charging ahead with a fragile architecture.

4. **Iterate in layers.** A typical feature like self-healing evolved across multiple prompts:
   - First prompt: *"I want to create a self-healing mechanism based on LLM for the Facebook scraper."*
   - My refinement after seeing the plan: *"The idea is that the self-healing will fix the code, not use LLM to scrape."*
   - Deepening: *"Maybe we should also pass a few screenshots if healing is needed. We should also consider, what are the cases we think healing is needed — not always will it be obvious with an error."*
   - Configuration precision: *"In config we should also point exactly the LLM provider and model for the healing."*
   - Validation: *"Let's create a real test for the self-healing! Do that by building a test where you sabotage the scraping schema and let's see if the workflow works well."*

   Each of these features represented a cycle of: **identify a real-world failure → frame the problem for the AI agent → review and refine the proposed solution → execute → verify with tests → dogfood in production → discover the next failure.**

### 2.2 Where I Overrode the Agent's Judgment

AI coding agents are remarkably capable, but they have blind spots. Here are moments where my engineering judgment was essential:

- **Silent failures vs. loud errors.** The agent's initial self-healing implementation only triggered on exceptions — when selectors threw errors. I pointed out that Facebook layout changes often don't crash anything; they just silently return empty results. I pushed the agent to add heuristic anomaly detection: if 3 consecutive posts fail to extract a URL, a date, or an author name, that's a silent failure pattern that should trigger healing. The agent wouldn't have thought of this on its own.

- **Screenshot multimodality.** The agent initially captured screenshots purely as a developer audit trail — saving them to disk for human inspection. I asked: *"but were the screenshots sent to the model along with the rest of the data?"* They weren't. I directed the agent to extend the `generate_content` API to accept an optional `image_path`, load the screenshot bytes, and transmit them as multimodal `types.Part` objects alongside the structural DOM text. This gives the healing model both the raw HTML structure and the visual render, dramatically improving selector synthesis accuracy.

- **Windows encoding landmines.** The agent used emoji characters (`✅`, `❌`, `📋`, `🚀`) in log statements and test prints. These crash on Windows terminals using CP1252 encoding. I caught these in test runs and directed systematic replacement across the codebase — a platform-specific concern the agent consistently overlooked.

- **The "benefit of the doubt" matcher design.** When building the zero-AI attribute matcher, the question arose: what happens when a user defines a custom rule (like *"must have optical fiber internet"*) that doesn't map to any known attribute keyword? The naive approach would reject the listing. I chose the opposite: if we can't verify the rule, we grant the listing the benefit of the doubt and let it through. False positives are far less harmful than false negatives in apartment hunting.

### 2.3 Designing Logging to Serve Agentic Coding & Autonomous Debugging

A critical design pattern in this project is that the codebase was built to be read, debugged, and maintained by **AI coding agents** (like Claude Code and Antigravity) rather than just human eyes. To enable this "agent-native" development, I deliberately designed a comprehensive, highly-structured logging mechanism (`utils/logger.py`) that serves as a high-fidelity diagnostic stream for coding agents during automated debugging loops.

#### 1. Structured JSON for Tool Parsing vs. Colored Console for Humans
Standard text logs are notoriously difficult for AI parsing tools to filter and query programmatically. To solve this, the logging system deploys a dual-formatter architecture:
*   **The Console Formatter (`HebrewConsoleFormatter`)**: Emits human-readable, ANSI-colored terminal streams.
*   **The Machine Formatter (`JSONFormatter`)**: Writes complete execution logs directly to `logs/app.log` in structured, raw JSON. This ensures that when a coding agent uses tools like `grep_search` or `view_file` to audit the application, it can parse every line as a clean, standardized JSON dictionary with exact keys:
    ```json
    {
      "timestamp": "2026-05-31T17:42:45.123Z",
      "level": "ERROR",
      "logger": "apt_bot.scraper",
      "message": "Selector validation failed on target element",
      "module": "self_healing",
      "function": "verify_selector",
      "line": 164,
      "data": {
        "selector": "span.x4k7w5x",
        "scraped_count": 0,
        "url": "https://www.facebook.com/groups/..."
      },
      "exception": "Traceback (most recent call last):\n  File ..."
    }
    ```

#### 2. The Isolated Error Sink (`logs/errors.log`)
Coding agents have finite context windows. Forcing an AI to read through a 10MB file containing thousands of verbose `INFO` scroll messages just to locate a single parsing exception wastes tokens and introduces reasoning noise.
To accommodate this, I configured the system with a dedicated `RotatingFileHandler` that intercepts all `ERROR` and `CRITICAL` events and mirrors them into a separate `logs/errors.log` file. 
When the scraper fails, the agent doesn't need to scroll. It goes directly to `logs/errors.log`, reads the clean sequence of recent exceptions, and immediately gains an isolated, high-signal understanding of the crash.

#### 3. Contextual Richness via `extra_data`
In standard logging, developers often write flat strings like `logger.error(f"Failed to parse post {post_id}")`. If a coding agent reads this, it lacks the context to understand *why* it failed.
Our custom wrapper `StructuredLogger` forces contextual rich logging by accepting arbitrary keyword arguments:
```python
# utils/logger.py
def error(self, message: str, **extra):
    self._log(logging.ERROR, message, **extra)
```
When scraping fails, we don't just log the error; we dump the entire state of execution inside the `data` key: the exact HTML segment, raw price text, parsed variables, and target URL. When a debugging agent reads this structured entry, it doesn't need to ask questions or run the code locally — the entire context of the failure is already present inside the log record, ready for immediate code synthesis and repair.

#### 4. The Unmatched Listings / Rejections Database (`rejection_logs`) for Matching Verification
In a matching system, confirming that matching listings are sent to the user is only half of the validation challenge. The harder half is proving that the system is **not** incorrectly filtering out valid listings (false negatives) and confirming that rejected listings are filtered out for the exact correct reasons.
To serve this need, I designed a stateful, transparent **Rejection Logs Database** (`rejection_logs` table managed by `RejectionRepository`). 
*   **Granular Failure Data**: When the `ZeroAIUserMatcher` evaluates a listing and rejects it, it doesn't just return `False`. It compiles a structural list of `failed_rules` and human-readable, context-rich Hebrew explanations (`reasons`).
*   **The Log Entry**:
    ```python
    # database/repositories/rejection_repository.py
    async def log_rejection(
        self,
        listing_id: str,
        user_id: int,
        failed_rules: List[str],
        reasons: List[str],
        listing_url: Optional[str] = None,
        listing_price: Optional[int] = None,
        listing_location: Optional[str] = None,
        match_method: str = "rule",
    ):
        ...
    ```
*   **Autonomous Rule Verification & Agentic Debugging**: This database was incredibly useful during development. Instead of guessing why certain listings didn't trigger notifications, the AI coding agent queried the `rejection_logs` database directly. It could fetch recent records, inspect the exact rules that triggered the rejection (e.g., matching a listing priced at 7,000₪ against a user limit of 6,500₪), verify that the price regex parsed the number correctly, and prove that the `ZeroAIUserMatcher` was behaving with 100% mathematical accuracy.
*   **User Transparency**: In addition to helping the coding agent debug the code, this data is exposed to users in Telegram via the `/rejections` command (and the `"🗑️ דירות שנפסלו"` menu keyboard option), showing them exactly which apartments were filtered out and why. This transparent verification layer turns the typical "black box" matching logic into a fully transparent, highly auditable pipeline.


---


## 3. Prompt Engineering and Iterative Refinement

The LLM prompts in this system aren't static strings — they're engineering artifacts that went through multiple revision cycles, each driven by a specific failure observed in production.

### 3.1 The Enrichment Prompt Lifecycle

**Iteration 1 — Naive extraction.** The initial prompt asked the LLM to "extract the price and number of rooms from this listing." The model responded conversationally: *"Sure! The price appears to be 5,000 shekels."* Unusable for programmatic parsing.

**Iteration 2 — JSON schema enforcement.** I constrained the output to raw JSON with explicit type annotations. But a new bug emerged: 10-digit Israeli phone numbers starting with `05` (like `0522505694`) were being extracted as rental prices.

**Iteration 3 — Negative guardrails.** I added explicit warnings in Hebrew directly inside the prompt:
```
"price": מספר או null (שים לב: אל תחלץ מספר טלפון בן 10 ספרות כמחיר!)
```
Combined with upstream regex filtering to strip phone numbers before the text reaches the LLM. Two layers of defense.

**Iteration 4 — Range splitting.** Hebrew listings containing *"3-6 חדרים"* (3-6 rooms) need to become two separate rules: `bedrooms_min=3` and `bedrooms_max=6`. But both rules inherited the original text *"3-6 חדרים"* as their display label, creating identical-looking confirmation buttons in Telegram. I added a post-processing heuristic that rewrites the labels to *"מינימום 3 חדרים"* and *"מקסימום 6 חדרים"* — a UX fix that no amount of prompt tuning could solve.

**Iteration 5 — Persona isolation.** The LLM generates both structured rule objects and a creative persona response in a single JSON call. This saves a duplicate API call while keeping the structural parsing completely isolated from the conversational output. The creative text can't corrupt the rule extraction because they occupy separate keys in the response schema.

**Iteration 6 — Bulk caching.** Generating persona greetings and sassy remarks on every interaction is wasteful. I configured the prompts to batch-generate 15 welcome messages and 30 sass remarks in a single call, cached in an `ai_cache` database table for instant, zero-cost retrieval.

### 3.2 The Self-Healing Prompt Design

The self-healing prompts required a different kind of precision. The LLM receives a cleaned structural DOM snippet (stripped of scripts, styles, SVGs, and images to minimize token consumption) and must return a flat JSON object with exactly two keys: `selector` and `reason`.

Early attempts failed because conversational models would:
- Wrap the selector in nested keys like `{"post_url": {"selector": "..."}}`
- Add preamble text before the JSON block
- Suggest selectors that were syntactically valid CSS but matched zero elements on the actual page

I solved each problem with increasingly strict prompt constraints:
```
CRITICAL: The JSON object must have exactly two root-level keys: "selector" and "reason".
Do NOT nest the keys inside any other outer key.
Return ONLY a valid, raw JSON block. Your entire response must start with '{' and end with '}'.
```

And crucially, every healed selector is **verified in Playwright** before being cached — the LLM proposes, but the browser validates.

---

## 4. The Anti-Bot Evasion Layer & Self-Healing AI Agent

Scraping dynamic, high-value targets like Yad2 and Facebook requires overcoming two distinct but equally devastating challenges: **active bot detection** (Web Application Firewalls that block automation) and **passive layout drift** (A/B testing and DOM changes that break selectors). I built a two-tiered defense system to solve both.

### 4.1 Defeating Active Bot Detection (The Evasion Layer)

Yad2 employs aggressive Cloudflare and Perfdrive Web Application Firewalls (WAFs) that instantly block standard HTTP clients and naive Selenium/Playwright instances. Facebook similarly throttles accounts that exhibit mechanical behavior. 
To bypass this, I developed a dedicated `AntiDetectionModule` that injects comprehensive stealth behaviors at the browser level:
- **Fingerprint Spoofing**: It overrides `navigator.webdriver`, injects realistic `plugins` and `languages` arrays, and aligns `Sec-Ch-Ua` client hints perfectly with randomized user-agents.
- **Hardware & Rendering Evasion**: It masks the underlying automation environment by faking `deviceMemory`, CPU `hardwareConcurrency`, and spoofing WebGL vendor/renderer strings to simulate real Intel/Apple hardware. It even applies cryptographic noise to `HTMLCanvasElement.toDataURL` to defeat canvas fingerprinting tracking.
- **Human-Mimicking Interaction**: Crucially, the module completely overrides Playwright's native `.fill()` and `.click()` methods. It types characters with randomized intra-stroke delays (50-150ms), inserts rare cognitive pauses (0.8-1.5s as if the "user" is thinking), and executes randomized Bezier-curve mouse movements and scroll jitter. 

This layer successfully bypasses the active WAFs, getting the scraper through the front door. But once inside, we face the second problem: layout drift.

### 4.2 The Self-Healing Agent: Fixing Passive Layout Drift

This is the most technically ambitious component of the system. While the evasion layer defeats WAFs, the self-healing agent defeats DOM changes. It represents a genuine autonomous agent loop: detect anomaly → capture evidence → reason about the problem → synthesize a fix → verify the fix → persist and resume.

### 4.3 When Does Healing Trigger?

The system detects two categories of failure:

**Loud failures** — the scraper scrolls through a group page and collects zero posts. This is obvious: the container selector is broken.

**Silent failures** — the scraper collects posts successfully, but critical attributes are missing. If 3 consecutive posts fail to yield a URL, a date, or an author name, the system infers that the attribute selectors have drifted. These are the dangerous ones — without explicit detection heuristics, the scraper would happily produce incomplete data indefinitely.

### 4.4 What Happens During a Healing Cycle

1. **Screenshot capture.** Playwright takes a high-resolution viewport screenshot (for container failures) or a precise bounding-box element screenshot (for attribute failures). These are saved to `logs/` as an audit trail.

2. **DOM cleaning.** The raw page HTML is stripped of scripts, styles, SVGs, images, and metadata attributes to produce a compact structural skeleton that fits within the model's context window.

3. **Multimodal LLM call.** The cleaned HTML text and the screenshot image bytes are compiled into a multimodal request using `google.genai.types.Part.from_bytes` and sent together to the configured model (`gemma-4-31b-it`). The model sees both the structural markup and the visual render — giving it the full picture.

4. **Selector synthesis.** The model returns a proposed CSS selector with a reasoning explanation.

5. **Playwright verification.** The proposed selector is tested against the live page. For containers, `page.query_selector_all` must return at least one element. For attributes, `post_element.query_selector` must find a descendant. If verification fails, the selector is rejected and logged.

6. **Persistence.** Verified selectors are written to `data/healed_selectors.json`. All subsequent scraping runs load these overrides automatically, running at full native Playwright speed with zero LLM overhead.

### 4.5 Configuration

The healing agent has its own dedicated LLM provider and model configuration, completely independent of the main enrichment engine:

```python
# config.py
FACEBOOK_SELF_HEALING_ENABLED: bool = True
SELF_HEALING_PERSIST_PATH: str = "data/healed_selectors.json"
SELF_HEALING_AI_PROVIDER: Optional[AIProvider] = AIProvider.GEMINI
SELF_HEALING_MODEL: Optional[str] = "gemma-4-31b-it"
```

This lets you run the daily enrichment pipeline on a cheap, fast model (like `gemini-3.1-flash-lite`) while reserving a more capable model for the rare healing events where reasoning quality matters.

### 4.6 The Sabotage Test — Proving It Works

To validate the entire healing pipeline end-to-end, I built a sabotage integration test (`tests/test_self_healing_sabotage.py`) that:

1. Injects a mock HTML DOM representing a completely modified Facebook layout — no `div[role="article"]`, no standard permalink structure, no `<strong>` author tags.
2. Poisons the selector cache with deliberately broken selectors.
3. Calls the **real** Gemini API (not a mock) using the configured model.
4. Verifies that the LLM successfully synthesizes working selectors from the unfamiliar DOM structure.
5. Validates that Playwright can extract correct data using the healed selectors.

The test passes consistently. Here's a real execution trace:

```
13:24:51 [   INFO] | [SUCCESS] Verified healed container: 'div[data-testid="fb-post"]'
13:24:59 [   INFO] | [SUCCESS] Verified healed post_url: 'a.permalink-timestamp-link'
13:25:01 [   INFO] | [SUCCESS] Verified healed author: '.user-profile-name'

SUCCESS: Healed URL: '.../permalink/123456/', Healed Author: 'Johnathan Doe'
======================= 1 passed in 16.00s =======================
```

I also ran the healing against a **real Facebook group** (`scripts/test_facebook_self_healing_real.py`). The sabotaged scraper navigated to the live group, failed to find posts with the broken selector, captured a 1.16 MB viewport screenshot, sent it with the cleaned DOM to `gemma-4-31b-it`, and recovered `div[role="article"]` as the healed container — then successfully extracted 3 live posts from the group feed.

---

## 5. Critical Reflection: Evaluating and Improving AI Output

I don't trust model outputs by default. Every interaction point between an LLM and the rest of the system has a verification layer.

### 5.1 How I Verify AI Outputs

**Structural validation.** Every LLM response is parsed through `_parse_json_response`, which strips markdown code fences, attempts `json.loads`, and falls back to regex extraction of JSON objects from conversational text. If parsing fails entirely, the response is logged and discarded — never silently accepted.

**Playwright verification for selectors.** The self-healing agent doesn't trust the LLM's proposed selector just because the JSON is well-formed. It runs the selector against the live page and counts matched elements. A selector that matches zero elements is rejected regardless of how reasonable it looks.

**Downstream normalization.** When the LLM classifies a Hebrew location like *"פלורנטין או כרם התימנים"* as a `border_area` (geographic boundary) instead of a simple `area` (neighborhood list), the system detects the misclassification by checking for directional keywords (`מערב`, `צפון`, `דרום`, `מזרח`). If none are present, it automatically rewrites the rule type to `area`. The LLM's classification drift is corrected programmatically at the boundary.

**Negative constraints in prompts.** Rather than hoping the model won't confuse phone numbers with prices, I explicitly tell it not to — in Hebrew, in the prompt, with examples. Defense in depth: the upstream regex strips phone numbers before the text even reaches the model.

### 5.2 Real-World Failures I Caught

**The phone number price leak.** A 10-digit Israeli phone number (`0522505694`) was extracted as the apartment's monthly rent. Fixed with both upstream regex filtering and explicit prompt guardrails.

**The border area misclassification.** Compound neighborhood requests (*"לב תל אביב או כרם התימנים"*) were occasionally classified as geographic boundaries instead of simple area rules. Fixed with a downstream normalization check.

**The range formatting confusion.** When room ranges like *"3-6 חדרים"* were split into separate min/max rules, both displayed the identical original text in Telegram confirmation buttons. Fixed with a deterministic label-rewriting heuristic.

**The silent selector drift.** Facebook changed its DOM without breaking any selectors outright — posts were still found, but timestamps were no longer inside the expected elements. The scraper ran happily, producing listings with no dates, which bypassed the date filter and flooded users with old posts. Fixed by adding consecutive-failure counters for each attribute type.

---

## 6. Cost Optimization and Token-Saving Architecture

Running an AI-powered system on free-tier APIs requires deliberate architectural choices. Every design decision in this system was made with cost awareness.

### The Enrich-Once Pattern

A listing is scraped once, enriched by the LLM once, and cached permanently with its structured attributes. Adding 10,000 users costs zero additional tokens — matching runs entirely on pre-computed local data.

### Prompt Batching

Up to 30 listings are consolidated into a single structured prompt using the `ListingEnricher._enrich_batch` method. This eliminates ~85% of prompt overhead (system instructions, JSON schema, constraints) that would otherwise be repeated for each listing.

### Zero-AI Matching

The `ZeroAIUserMatcher` maps Hebrew keywords to pre-computed boolean attributes:

```python
self.keyword_to_attr = {
    "חניה": "has_parking",
    "מרפסת": "has_balcony",
    "מעלית": "has_elevator",
    "חיות": "allows_pets",
    "שותפים": "suitable_for_roommates",
}
```

If a user rule contains *"חניה"*, the system checks `listing.attributes["has_parking"]` — no LLM call, microsecond latency, infinite scaling at zero cost.

### Persona Caching

Welcome messages and sassy remarks are batch-generated (30 at a time) and stored in an `ai_cache` table. Telegram interactions serve cached content instantly — zero real-time token consumption.

### Model Rotation

The `GeminiAIEngine` maintains a list of models with per-model rate limiters. When one model hits its daily limit, the engine automatically rotates to the next (`gemini-3.1-flash-lite` → `gemma-4-31b-it` → `gemini-2.5-flash` → ...), maintaining system uptime without manual intervention.

---

## 7. Testing Strategy

### 7.1 Test Architecture Overview

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

### 7.2 What Each Tier Covers

**Unit tests** validate isolated logic: Hebrew currency parsing (`5000 ש"ח`, `5k`, `₪5,000` → `5000`), phone number exclusion from prices, bedroom extraction, geographic border lookups, auto-max room heuristics, and scheduler blackout windows.

**Integration tests** mount in-memory SQLite databases and verify stateful workflows: cross-source deduplication (same listing posted to Facebook and Yad2), Facebook post filtering (exchange posts, spam, promotional content), deleted Telegram user handling, and AI engine retry/rotation under simulated 429/500/503 errors.

**Real-LLM tests** call live Gemini endpoints with real Hebrew text and assert structural correctness of the parsed output. `test_hebrew_rules_llm.py` fires 6 real-world user queries through the full parsing pipeline across multiple personas and validates extracted rule types, values, and persona response quality. `test_self_healing_sabotage.py` sabotages selectors and verifies that the actual model heals them correctly.

### 7.3 What I Chose Not to Test (and Why)

**Live network requests to Facebook/Yad2.** Third-party web formats are volatile. A test that passes today might fail tomorrow because Facebook changed a class name — producing a false failure that has nothing to do with my code. I mock all network interactions in the main test suite and maintain separate diagnostic scripts (`scripts/test_scraper.py`, `scripts/test_facebook_self_healing_real.py`) for manual live verification.

**Persona tone quality.** I verify that persona responses are non-empty, contain Hebrew text, and respect length constraints. I don't attempt to evaluate whether *Barakush*'s sass is sufficiently witty — that's a subjective judgment that automated tests can't meaningfully capture.

**Multi-user concurrency.** The bot serves a small number of users on a single machine. I haven't load-tested concurrent Telegram message handling because the real-world usage pattern doesn't warrant it yet.

### 7.4 Bugs My Tests Caught

**The short listing skip bug.** A minimum-length filter (`len(text) < 30`) was silently discarding highly concise but valid listings like *"דירה להשכרה 3 חדרים"* (20 characters). Caught by `test_facebook_filtering.py`.

**The deduplication field gap.** The duplicate detection test was initializing mock listings without `extracted_bedrooms`, causing the `author + price + bedrooms` fingerprint to fail silently. Cross-posted listings slipped through. Caught by `test_duplicate_detection.py` after I noticed duplicates in production logs.

**The self-healing emoji crash.** Unicode emojis (`✅`, `❌`) in log statements crashed the entire test process on Windows terminals using CP1252 encoding. The test runner would exit with a `UnicodeEncodeError` after the LLM had already successfully healed the selector — making it look like the healing failed when it actually succeeded. Caught during the sabotage test run.

---

## 8. Interactive Demo and User Walkthrough

### 8.1 User Registration

The user opens the Telegram bot and hits `/start`. The bot auto-registers them, assigns the default *Barakush* persona, fetches a cached dynamic welcome, and presents a persistent Hebrew reply keyboard menu:

```
┌─────────────────────────────────────────┐
│  🔎 חיפוש התאמות  │  📊 סטטוס          │
│  📋 הכללים שלי    │  👤 החלפת נציג      │
│  🗑️ דירות שנפסלו  │  💅 קצת יחס         │
│  ℹ️ עזרה                                │
└─────────────────────────────────────────┘
```

### 8.2 Setting Search Rules

The user sends a free-form Hebrew message:

> **User:** "אני מחפש דירה בתל אביב, לפחות 3 חדרים, עד 6500 שקל, באזור פלורנטין. חייב חניה!"

The LLM parses this into structured rules and responds in-persona:

> **Barakush:** "3 חדרים עם חניה בפלורנטין? 💀 מאמי, באיזה סרט אתה חי, של דיסני? 🦄 אבל יאללה, רשמתי לי."

### 8.3 Live Match Notification

When a matching listing is scraped:

> **Barakush:** "🏠 מצאתי דירה הורסת בשבילך! 💅
> **מיקום**: פלורנטין, תל אביב
> **חדרים**: 3 | **מחיר**: 6,000₪ (+ תיווך)
> 💰 מחיר כולל תיווך מפורס: 6,500₪
> • יש חניה מסודרת! 🚗
> [לחץ כאן לצפייה בפוסט המקורי בפייסבוק]"

### 8.4 Self-Healing Demo

When Facebook changes its layout and the scraper stops finding posts:

```
13:28:04 [WARNING] | No posts collected. Attempting self-healing...
13:28:04 [   INFO] | Captured viewport screenshot: logs/healing_post_container.png
13:28:05 [   INFO] | Adding screenshot to Gemini for multimodal analysis
13:29:08 [   INFO] | [SUCCESS] Healed container: 'div[role="article"]'
13:29:08 [   INFO] | Retrying collection with healed selector...
13:29:14 [   INFO] | Collected 3 posts successfully
```

No human intervention. No downtime. The scraper heals itself and resumes.

---

## 9. Conclusion: What I Learned About AI-Assisted Development

Building this project taught me that working effectively with AI coding agents is its own skill — distinct from traditional programming and distinct from prompt engineering for chatbots.

**Frame the problem, not the solution.** The best results came when I described the real-world failure I was experiencing and let the agent propose an architecture. My job was to evaluate the proposal, push back on fragile designs, and add the edge cases the agent wouldn't anticipate.

**The agent writes the code; you own the design.** The self-healing system exists because I identified a category of failure (silent selector drift) and articulated a design constraint (fix the selectors, never use LLM to scrape). The agent implemented it. But the multimodal screenshot integration, the silent failure heuristics, the dedicated model configuration — those came from my direction after reviewing what the agent built.

**Verification is non-negotiable.** Every LLM output in this system passes through a verification layer — JSON parsing, Playwright selector validation, downstream normalization, negative prompt constraints. The system trusts the model's creativity but verifies its correctness.

**Test at the boundaries.** The most valuable tests aren't the ones that check happy paths — they're the ones that exercise the boundary between deterministic code and probabilistic AI output. The sabotage test, the real-LLM parsing tests, the fallback flow test — these are where regressions actually hide.

This project demonstrates that AI-assisted development isn't about delegating thinking to the model. It's about combining the model's ability to generate correct code at scale with your own ability to identify what "correct" means in the first place.
