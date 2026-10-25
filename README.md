# Daily Tech Brief — Personal AI News Automation System

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](pyproject.toml)
[![Tests: 68 Passing](https://img.shields.io/badge/tests-68%20passed-brightgreen.svg)](tests/)

An autonomous personal tech news aggregator, ranker, and multi-channel delivery system built for computer science students and engineers. It collects stories from research repositories, official engineering blogs, cybersecurity agencies, startup feeds, and student opportunity platforms, filters and ranks them using an explainable multi-factor scoring model, optionally enriches them with LLM summaries, and delivers a formatted daily digest to **both Telegram and Email** at **9:00 AM India Standard Time (IST)** via GitHub Actions without requiring a laptop or dedicated server to run.

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Key Features](#key-features)
3. [Architecture Overview](#architecture-overview)
4. [Project Structure](#project-structure)
5. [Prerequisites](#prerequisites)
6. [Local Setup Instructions](#local-setup-instructions)
   - [Windows PowerShell](#windows-powershell)
   - [macOS and Linux](#macos-and-linux)
7. [Environment Variable Configuration](#environment-variable-configuration)
8. [Channel Setup Guides](#channel-setup-guides)
   - [Telegram Bot Setup](#telegram-bot-setup)
   - [Email SMTP (Gmail) Setup](#email-smtp-gmail-setup)
   - [Optional AI LLM Setup](#optional-ai-llm-setup)
9. [Command-Line Interface (CLI)](#command-line-interface-cli)
10. [Automated GitHub Actions Deployment](#automated-github-actions-deployment)
11. [Scheduling and Timezone Verification](#scheduling-and-timezone-verification)
12. [Deduplication, Persistence, and Retention](#deduplication-persistence-and-retention)
13. [Failure Isolation and Independent Retries](#failure-isolation-and-independent-retries)
14. [Cost Optimization and Free Tier Operation](#cost-optimization-and-free-tier-operation)
15. [Security and Privacy Safeguards](#security-and-privacy-safeguards)
16. [Troubleshooting & Debugging](#troubleshooting--debugging)
17. [Roadmap](#roadmap)

---

## Project Overview

Modern software engineering and computer science move fast. Keeping up with arXiv preprints, major model weights releases, critical zero-day CVE advisories, open-source milestones, and student program deadlines is overwhelming.

**Daily Tech Brief** automates this entirely:
- **Zero Ongoing Cost**: Runs 100% free by default using RSS/Atom feeds, GitHub Actions free minutes, Telegram Bot API, Gmail SMTP, and SQLite with local extractive summarization.
- **Explainable Multi-Factor Ranking**: Ranks candidate stories across 5 dimensions: Topic Relevance (35%), Freshness (25%), Importance/Impact (20%), Source Credibility (15%), and Novelty (5%).
- **Strict Grounding**: Never fabricates deadlines, benchmark claims, or publication dates.
- **Fail-Safe & Idempotent**: Feed failures never break the entire pipeline. Retries never re-send to channels that already succeeded.

---

## Key Features

- **Multi-Source Ingestion**: Preconfigured with arXiv (`cs.AI`, `cs.LG`, `cs.CL`), Hugging Face Blog, GitHub Engineering Blog, Hacker News (HNRSS), CISA Cybersecurity Advisories, The Hacker News, TechCrunch, Simon Willison, and Google Open Source.
- **Conditional HTTP GET**: Caches `ETag` and `Last-Modified` in SQLite, returning `304 Not Modified` to eliminate redundant data transfer.
- **Multi-Level Deduplication**:
  1. Exact canonical URL matching (strips UTM and tracking parameters while preserving query arguments).
  2. Normalized title matching (punctuation removal, lowercase).
  3. Token similarity near-duplicate detection (Jaccard similarity with stemming and stop-word filtering).
  4. Cross-day deduplication suppressing previously delivered stories for up to 90 days.
- **Explainable Scoring**: Calculates scores from 0–100 with a detailed breakdown reason for each selected story.
- **Source & Category Diversity**: Prevents any single publisher or single topic from dominating the 8–10 selected daily stories.
- **Low-News Fallback Window**: Broadens coverage from 24h to 48h if news volume is low, but refuses to pad digests with clickbait.
- **Provider-Neutral Summaries**: Supports Google Gemini, OpenAI, Groq, and Anthropic Claude, with automatic extractive fallback and SHA-256 content caching.
- **Multi-Channel Delivery**:
  - **Telegram**: Clean HTML formatting, automated chunking (respecting Telegram's 4096 character limit), and plain-text fallback.
  - **Email**: Multipart MIME delivering clean plain text and a responsive, mobile-ready HTML card layout via SMTP (STARTTLS / SSL).
- **Scheduled 9:00 AM IST Execution**: GitHub Actions workflow cron set to `30 3 * * *` (03:30 UTC = 09:00 AM IST) with database state caching.

---

## Architecture Overview

```
                                  +----------------------+
                                  |   config/feeds.yaml  |
                                  +----------+-----------+
                                             |
                                             v
+------------------+             +-----------+-----------+
| RSS / Atom Feeds | ----------> |     FeedCollector     | (ETag / Last-Modified 304,
| (11+ Sources)    |             |  (requests / backoff) |  timeouts, size limits)
+------------------+             +-----------+-----------+
                                             |
                                             v
                                 +-----------+-----------+
                                 |   ArticleNormalizer   | (HTML entity decode, tag strip,
                                 |  & ArticleCategorizer |  URL canonicalization)
                                 +-----------+-----------+
                                             |
                                             v
                                 +-----------+-----------+
                                 |  ArticleDeduplicator  | (Exact URL, normalized title,
                                 |   & SQLite Storage    |  token Jaccard, 90d history)
                                 +-----------+-----------+
                                             |
                                             v
                                 +-----------+-----------+
                                 |     ArticleRanker     | (Relevance, Freshness, Impact,
                                 |  & Diversity Filter   |  Credibility, Novelty)
                                 +-----------+-----------+
                                             |
                                             v
                                 +-----------+-----------+
                                 | SummarizationPipeline | (Cached / Extractive Fallback /
                                 |   (Optional LLM)      |  Gemini / OpenAI / Anthropic)
                                 +-----------+-----------+
                                             |
                                             v
                                 +-----------+-----------+
                                 |     DigestRenderer    | (Plain Text, Telegram HTML,
                                 |   & DeliveryService   |  Responsive Email HTML)
                                 +-----------+-----------+
                                             |
                      +----------------------+----------------------+
                      |                                             |
                      v                                             v
         +------------+------------+                   +------------+------------+
         |   Telegram Bot API      |                   |    SMTP Email Server    |
         | (HTML chunks / retries) |                   | (Gmail / STARTTLS / SSL)|
         +-------------------------+                   +-------------------------+
```

---

## Project Structure

```
news-automation-bot/
├── .github/
│   └── workflows/
│       └── daily.yml          # GitHub Actions 9:00 AM IST schedule & manual trigger
├── config/
│   └── feeds.yaml             # External feeds, categories, weights, and excluded topics
├── src/
│   └── daily_tech_brief/
│       ├── __init__.py        # Package exports
│       ├── models.py          # Typed dataclasses (Article, OpportunityMetadata, etc.)
│       ├── config.py          # Settings, env parsing, validation, weights
│       ├── sources.py         # Feed registry and YAML loader
│       ├── normalizer.py      # HTML sanitation, canonical URLs, opportunity extraction
│       ├── categorizer.py     # Multi-category classification and keyword relevance
│       ├── collector.py       # Resilient HTTP RSS/Atom fetcher with 304 & retry
│       ├── deduplication.py   # Token Jaccard similarity & cross-day suppression
│       ├── ranking.py         # Multi-factor scoring, diversity caps, fallback window
│       ├── summarizer.py      # LLM adapters, structured output, extractive fallback
│       ├── digest.py          # Plain text, Telegram HTML, and Email HTML renderers
│       ├── storage.py         # SQLite persistence, delivery logs, summary cache
│       ├── delivery.py        # Telegram Bot API and SMTP delivery engines
│       ├── scheduler.py       # Workflow coordinator & end-to-end execution pipeline
│       └── main.py            # CLI entry point implementation
├── tests/
│   ├── conftest.py            # Pytest fixtures and mock objects
│   ├── test_normalizer.py     # HTML cleaning, canonicalization, date parsing tests
│   ├── test_categorizer.py    # Categorization and keyword relevance tests
│   ├── test_collector.py     # RSS/Atom fetch, 304, 429, timeouts, and error isolation
│   ├── test_deduplication.py  # Exact & token-similarity deduplication tests
│   ├── test_ranking.py        # Multi-factor ranking and diversity constraint tests
│   ├── test_storage.py        # SQLite persistence, transaction rollback, retention
│   ├── test_summarizer.py     # LLM and extractive fallback tests
│   ├── test_digest.py         # Format rendering and message splitting tests
│   ├── test_delivery.py       # Telegram and SMTP delivery failure/retry tests
│   └── test_scheduler.py      # Timezone conversion, midnight UTC, and run prevention
├── scripts/
│   └── test_delivery.py       # Quick delivery verification script
├── .env.example               # Safe environment variable template
├── .gitignore                 # Secrets, virtual environments, and SQLite database ignores
├── pyproject.toml             # Build system, package dependencies, and pytest config
├── requirements.txt           # Pinned production and test dependencies
├── LICENSE                    # MIT License
├── main.py                    # Root CLI shortcut
└── README.md                  # Comprehensive operational documentation
```

---

## Prerequisites

- **Python**: Version 3.12 or 3.13.
- **Git**: Installed and available in your terminal.
- **Telegram Account**: To create a free bot and receive messages.
- **Email Account**: Any standard SMTP account (e.g., Gmail with an App Password).

---

## Local Setup Instructions

### Windows PowerShell

1. Clone or navigate to the repository:
   ```powershell
   cd d:\projects\news-automation-bot
   ```

2. Create and activate a Python virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
   *(If script execution is disabled on your system, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` first).*

3. Upgrade pip and install dependencies:
   ```powershell
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Create your `.env` configuration file:
   ```powershell
   Copy-Item .env.example .env
   ```

### macOS and Linux

1. Clone or navigate to the repository:
   ```bash
   cd news-automation-bot
   ```

2. Create and activate virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Upgrade pip and install dependencies:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Create your `.env` configuration file:
   ```bash
   cp .env.example .env
   ```

---

## Environment Variable Configuration

Edit your local `.env` file with your settings:

```ini
# ==============================================================================
# Telegram Settings
# ==============================================================================
TELEGRAM_BOT_TOKEN=123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=987654321

# ==============================================================================
# Email Delivery Settings (SMTP)
# ==============================================================================
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USERNAME=your.email@gmail.com
EMAIL_PASSWORD=your_16_character_app_password
EMAIL_SENDER=your.email@gmail.com
EMAIL_RECIPIENT=your.personal@domain.com

# ==============================================================================
# Timezone & Scheduling
# ==============================================================================
TIMEZONE=Asia/Kolkata

# ==============================================================================
# Digest & Selection Rules
# ==============================================================================
DIGEST_LIMIT=10
LOOKBACK_HOURS=24
FALLBACK_LOOKBACK_HOURS=48
MAX_ARTICLES_PER_SOURCE=2
ENABLE_OPPORTUNITIES=true

# ==============================================================================
# Persistence & Logging
# ==============================================================================
DATABASE_PATH=data/daily_tech_brief.db
LOG_LEVEL=INFO

# ==============================================================================
# Optional AI Summarization (Free by default: set to false)
# ==============================================================================
ENABLE_LLM_SUMMARIES=false
LLM_PROVIDER=gemini
LLM_API_KEY=
LLM_MODEL=gemini-1.5-flash
```

---

## Channel Setup Guides

### Telegram Bot Setup

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts to choose a display name and username (e.g. `MyDailyTechBriefBot`).
3. Copy the HTTP API token provided by BotFather into `TELEGRAM_BOT_TOKEN`.
4. Start a conversation with your new bot by clicking `Start` in Telegram.
5. Retrieve your Chat ID:
   - Message [@userinfobot](https://t.me/userinfobot) on Telegram to get your numeric user ID, or
   - Send any message to your new bot, then open:
     `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in your browser and copy `message.chat.id`.
6. Set `TELEGRAM_CHAT_ID` to this number.
7. Test the integration:
   ```bash
   python main.py test-telegram
   ```

### Email SMTP (Gmail) Setup

1. Log into your Google Account and navigate to **Security** ([myaccount.google.com/security](https://myaccount.google.com/security)).
2. Ensure **2-Step Verification** is turned ON.
3. In the search bar at the top of the Google Account page, search for **App passwords**.
4. Generate a new app password named `Daily Tech Brief`.
5. Google will generate a 16-character code (e.g., `abcd efgh ijkl mnop`).
6. Paste this code (without spaces) into `EMAIL_PASSWORD`.
7. Configure:
   - `EMAIL_HOST=smtp.gmail.com`
   - `EMAIL_PORT=587`
   - `EMAIL_USERNAME=your_gmail_address@gmail.com`
   - `EMAIL_SENDER=your_gmail_address@gmail.com`
   - `EMAIL_RECIPIENT=your_destination_address@domain.com`
8. Test the integration:
   ```bash
   python main.py test-email
   ```

### Optional AI LLM Setup

The application works out-of-the-box in **100% Free Mode** (`ENABLE_LLM_SUMMARIES=false`) using clean extractive summarization.

If you wish to enable AI summaries:
- **Google Gemini** (Recommended for free tier):
  1. Get a free API key from [Google AI Studio](https://aistudio.google.com/).
  2. In `.env`:
     ```ini
     ENABLE_LLM_SUMMARIES=true
     LLM_PROVIDER=gemini
     LLM_API_KEY=AIzaSy...
     LLM_MODEL=gemini-1.5-flash
     ```
- **OpenAI or Groq**:
  ```ini
  ENABLE_LLM_SUMMARIES=true
  LLM_PROVIDER=groq
  LLM_API_KEY=gsk_...
  LLM_MODEL=llama-3.3-70b-versatile
  ```

---

## Command-Line Interface (CLI)

The CLI provides subcommands for every stage of operation:

| Command | Description |
|---|---|
| `python main.py health` | Validate configuration, database path, and feeds without sending messages |
| `python main.py sources` | List all configured news feeds and reliability weights |
| `python main.py collect` | Fetch all feeds and display article counts and fetch times |
| `python main.py preview` | Fetch live feeds, run scoring, and print a formatted terminal preview |
| `python main.py run` | Execute the full scheduled digest workflow and deliver to both channels |
| `python main.py run --dry-run` | Execute complete ranking workflow without sending messages |
| `python main.py run --force` | Force execution even if already completed today |
| `python main.py test-telegram` | Send a test message to Telegram |
| `python main.py test-email` | Send a test email via SMTP |
| `python main.py test-delivery` | Test both Telegram and Email delivery |
| `python main.py retry-failed` | Retry only channels that failed on the last run |

---

## Automated GitHub Actions Deployment

The system is designed to run automatically on GitHub Actions without needing your local computer on.

### 1. Push Repository to GitHub
```bash
git init
git add .
git commit -m "Initial release of Daily Tech Brief"
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/daily-tech-brief.git
git push -u origin main
```

### 2. Configure Repository Secrets
In your GitHub repository, navigate to:
**Settings** &rarr; **Secrets and variables** &rarr; **Actions** &rarr; **New repository secret**.

Add the following secrets:

| Secret Name | Required? | Example Value |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | `123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ` |
| `TELEGRAM_CHAT_ID` | Yes | `987654321` |
| `EMAIL_USERNAME` | Yes | `your.email@gmail.com` |
| `EMAIL_PASSWORD` | Yes | `abcdefghijklmnop` (App Password) |
| `EMAIL_SENDER` | Yes | `your.email@gmail.com` |
| `EMAIL_RECIPIENT` | Yes | `your.recipient@gmail.com` |
| `EMAIL_HOST` | Optional | `smtp.gmail.com` (default) |
| `EMAIL_PORT` | Optional | `587` (default) |
| `ENABLE_LLM_SUMMARIES`| Optional | `false` (default) or `true` |
| `LLM_PROVIDER` | Optional | `gemini` |
| `LLM_API_KEY` | Optional | Google Gemini API Key |
| `LLM_MODEL` | Optional | `gemini-1.5-flash` |

### 3. Trigger a Manual Run in GitHub Actions
1. Go to the **Actions** tab in your GitHub repository.
2. Under "All workflows", click **Daily Tech Brief Digest**.
3. Click the **Run workflow** dropdown on the right.
4. Optionally check `dry_run` for a test without delivery.
5. Click **Run workflow**.

---

## Scheduling and Timezone Verification

The target schedule is **9:00 AM India Standard Time (IST)**, UTC+05:30.

### The GitHub Actions Constraint
GitHub Actions workflow `schedule` syntax **only accepts standard 5-part UTC cron expressions**. It does **not** support timezone attributes (e.g. `timezone: Asia/Kolkata` is rejected by the GitHub Actions workflow validator).

### The Exact Conversion
$$\text{Target IST Time} = \text{09:00 AM IST}$$
$$\text{IST Offset} = \text{UTC}+05:30$$
$$\text{UTC Time} = 09:00 - 05:30 = \text{03:30 AM UTC}$$

Hence, the cron trigger in `.github/workflows/daily.yml` is:
```yaml
schedule:
  - cron: '30 3 * * *'
```

### Operational Note on GitHub Actions Cron
GitHub runs scheduled workflows based on overall runner availability. Runs typically trigger within 0 to 15 minutes of the scheduled time. The Python application uses timezone-aware timestamps (`Asia/Kolkata`) internally to calculate coverage windows and digest dates regardless of the runner machine's local time.

---

## Deduplication, Persistence, and Retention

### Persistent State
The application stores state in a local SQLite database (`data/daily_tech_brief.db`):
- `articles`: Normalized articles, computed scores, summaries, and delivery flags.
- `feed_runs`: Source fetch latency, HTTP status code, ETag, and Last-Modified headers.
- `digest_runs`: Digest execution dates, statuses, and story counts.
- `digest_articles`: Mapping between daily digests and selected articles.
- `deliveries`: Per-channel delivery attempts, statuses (`SUCCESS`, `FAILED`), and message IDs.
- `summary_cache`: SHA-256 content hashes mapped to summaries.

### Multi-Level Deduplication
1. **Canonical URL Matching**: Tracking parameters (`utm_*`, `fbclid`, `gclid`, `ref`, etc.) are stripped while preserving content IDs.
2. **Normalized Title Matching**: Punctuation removed, whitespace collapsed, case-insensitive comparison.
3. **Stemmed Token Jaccard Similarity**: Common stop-words are eliminated, word endings are stemmed, and Jaccard similarity is computed. If two sources report the same story (similarity $\ge 0.82$), the higher-credibility article is retained and the second source is credited under `corroborating_sources`.
4. **Cross-Day Suppression**: Stories previously delivered within the configured retention window (default 90 days) are suppressed from future digests.

### Serverless Database State in GitHub Actions
In `.github/workflows/daily.yml`, the `actions/cache@v4` action automatically restores the `data/` directory before execution and saves the updated SQLite state upon workflow completion.

---

## Failure Isolation and Independent Retries

- **Feed Isolation**: If one feed times out or returns HTTP 500, the collector records the failure in `feed_runs` and continues processing the remaining feeds.
- **Channel Independence**:
  - If Telegram succeeds and Email fails, `deliveries` records `telegram=SUCCESS` and `email=FAILED`.
  - The workflow reports `PARTIAL_FAILURE`.
  - Running `python main.py retry-failed` will check the latest digest and **only retry Email**, preventing Telegram from receiving duplicate messages.

---

## Cost Optimization and Free Tier Operation

| Component | Service | Cost |
|---|---|---|
| **News Feeds** | Public RSS/Atom Feeds | **$0.00** |
| **Scheduler & Runner** | GitHub Actions (Ubuntu runner) | **$0.00** (Uses ~1 minute/day from 2,000 free monthly minutes) |
| **Telegram Delivery** | Telegram Bot API | **$0.00** (Free, unlimited bot messages) |
| **Email Delivery** | Gmail SMTP (Personal Account) | **$0.00** (Free up to 500 emails/day) |
| **Database** | SQLite + GitHub Cache | **$0.00** |
| **Summarization** | Local Extractive / Gemini Flash | **$0.00** (Gemini 1.5 Flash free tier allows 15 RPM) |

**Estimated Monthly Operating Cost: $0.00 / month.**

---

## Security and Privacy Safeguards

1. **Zero Committed Secrets**: `.gitignore` strictly excludes `.env`, credentials, and `data/` directory.
2. **Secret Masking**: Bot tokens and SMTP passwords are never printed in plain text in logs or console output.
3. **HTML Sanitization**: All external article titles and descriptions are stripped of raw HTML and escaped before embedding into Telegram messages or email bodies, preventing script injection.
4. **Prompt Injection Hardening**: All feed content is delimited as untrusted input with strict system instructions prohibiting tool calls or instruction execution based on article text.
5. **Least Privilege**: GitHub Actions workflow runs with `contents: read` permissions.

---

## Troubleshooting & Debugging

### 1. `UnicodeEncodeError` in Windows PowerShell
- **Symptom**: Console throws charmap encoding error on special characters.
- **Fix**: The application automatically configures UTF-8 standard output. You can also run:
  ```powershell
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  ```

### 2. Telegram `Unauthorized` or `Chat not found`
- **Symptom**: Telegram returns 401 Unauthorized or 400 Bad Request.
- **Fix**:
  1. Verify you messaged `/start` to your bot from your Telegram client.
  2. Double-check `TELEGRAM_CHAT_ID` matches your numeric ID (not your @username).

### 3. SMTP `535 Authentication Credentials Invalid`
- **Symptom**: Gmail SMTP rejects connection.
- **Fix**:
  1. Ensure 2-Step Verification is enabled on your Google account.
  2. Generate a dedicated 16-character **App password** (do NOT use your standard Gmail password).

### 4. Feed Timeouts or Rate Limits
- **Symptom**: A feed reports `TIMEOUT` or `HTTP 429`.
- **Fix**: The collector automatically retries with exponential backoff and isolates failed feeds. To adjust timeouts, edit `timeout_seconds` for that feed in `config/feeds.yaml`.

---

## Roadmap

1. **GitHub Releases & Student Programs Adapter**: Ingest selected repository releases via GitHub REST API and student developer pack updates.
2. **Web Reader View / Weekly Archive**: Generate a static Markdown or HTML archive of weekly digests.
3. **Personalized Keyword Weight Tuning**: Allow custom keyword boosts via a lightweight terminal preferences wizard.
