# Newsletter Archiver

A CLI tool that fetches email newsletters from Outlook via the Microsoft Graph API, converts them to Markdown, and archives them locally. Built for people who want a searchable, offline archive of their newsletter subscriptions.

## Features

- Fetches emails from Outlook (personal accounts) using device code authentication
- Sender approval workflow: discover newsletter senders, approve or deny them
- Per-sender archive mode: **auto** (archive immediately) or **review** (approve each email individually)
- Converts HTML newsletters to clean Markdown with YAML frontmatter
- Filters out transactional emails (receipts, confirmations, renewal notices)
- Deduplication: safe to re-run without creating duplicates
- Date range support for backfilling archives
- **Full-text keyword search** via SQLite FTS5 (porter stemming, ranked snippets)
- **Semantic search** via sentence-transformers (local, no API key needed)
- **RAG Q&A** — ask natural language questions and get AI-generated answers grounded in your archive (via Claude API)
- Auto-indexes new newsletters on fetch and review approval

## Installation

Requires Python 3.11+.

```bash
git clone https://github.com/noooom70/newsletter-archiver.git
cd newsletter-archiver
poetry install
```

## Quick Start

### 1. Discover newsletter senders

Scan your inbox for emails that look like newsletters:

```bash
poetry run newsletter-archiver fetch --scan -d 30
```

### 2. Approve senders

Review discovered senders and choose an archive mode for each:

```bash
poetry run newsletter-archiver senders review
```

- **auto**: all emails from this sender are archived immediately
- **review**: emails are queued for individual approval

### 3. Fetch and archive

Archive emails from approved senders:

```bash
poetry run newsletter-archiver fetch -d 30 --auto
```

### 4. Keep it updated

Fetch everything since the last archived email:

```bash
poetry run newsletter-archiver fetch --update --auto
```

## Commands

### fetch

Fetch and archive newsletters from Outlook.

```
newsletter-archiver fetch [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-d`, `--days-back` | Number of days back to fetch (default: 7) |
| `--from` | Start date (YYYY-MM-DD), overrides --days-back |
| `--to` | End date (YYYY-MM-DD), defaults to today |
| `-u`, `--update` | Fetch from the last archived email date to now |
| `-s`, `--sender` | Filter by sender email or domain |
| `--scan` | Discover new newsletter senders without archiving |
| `--auto` | Archive all emails immediately, ignoring sender mode |
| `--dry-run` | Show what the transactional filter would skip |

Examples:

```bash
# Daily update
poetry run newsletter-archiver fetch -u --auto

# Backfill a specific date range
poetry run newsletter-archiver fetch --from 2025-06-01 --to 2025-12-31 --auto

# Audit what gets filtered out
poetry run newsletter-archiver fetch -d 30 --dry-run

# Discover new senders from the last 90 days
poetry run newsletter-archiver fetch --scan -d 90
```

### senders

Manage newsletter senders.

```bash
# Interactively approve/deny pending senders
poetry run newsletter-archiver senders review

# List all senders and their status/mode
poetry run newsletter-archiver senders list

# Filter by status
poetry run newsletter-archiver senders list --status approved

# Manually add a sender
poetry run newsletter-archiver senders add user@example.com --name "Example" --mode auto

# Deny a sender
poetry run newsletter-archiver senders remove user@example.com

# Change a sender's archive mode
poetry run newsletter-archiver senders set-mode user@example.com auto
```

### search

Search your archived newsletters.

```bash
# Keyword search (supports FTS5 syntax: phrases, AND, OR, NOT)
poetry run newsletter-archiver search keyword "TSMC"
poetry run newsletter-archiver search keyword '"artificial intelligence" AND business'

# Semantic search (meaning-based, uses sentence-transformers locally)
poetry run newsletter-archiver search semantic "how AI changes business models"

# RAG Q&A (ask a question, get an answer with citations via Claude)
poetry run newsletter-archiver search ask "What has Ben Thompson written about TSMC?"
poetry run newsletter-archiver search ask "how do AI labs make money?" --sender "The Diff"
poetry run newsletter-archiver search ask "summarize the Economist's coverage of Iran" --model claude-haiku-4-5-20251001
```

Keyword and semantic search options:

| Option | Description |
|--------|-------------|
| `-n`, `--limit` | Maximum results to return (default: 10) |
| `-s`, `--sender` | Filter by sender name |

`search ask` options:

| Option | Description |
|--------|-------------|
| `-n`, `--limit` | Number of chunks to retrieve (default: 10) |
| `-s`, `--sender` | Filter by sender name |
| `-m`, `--model` | Override Claude model (default: claude-sonnet-4-5-20250929) |

The `ask` command requires an `ANTHROPIC_API_KEY` environment variable (or set in `.env`).

### index

Build and manage search indexes.

```bash
# Build both FTS and vector indexes
poetry run newsletter-archiver index build

# Rebuild from scratch
poetry run newsletter-archiver index build --reindex

# Build only one type
poetry run newsletter-archiver index build --fts-only
poetry run newsletter-archiver index build --vector-only

# Check indexing status
poetry run newsletter-archiver index status
```

New newsletters are auto-indexed when archived via `fetch` or `review`. Use `index build` to index existing newsletters or to rebuild after any issues.

### archive

Manage archive directory structure and file hygiene.

```bash
# Preview directory renames based on publications.yaml mapping
poetry run newsletter-archiver archive migrate --dry-run

# Execute the migration (moves files, updates DB paths, cleans empty dirs)
poetry run newsletter-archiver archive migrate

# Strip invisible Unicode padding from existing markdown files
poetry run newsletter-archiver archive clean --dry-run
poetry run newsletter-archiver archive clean
```

### review

Approve or deny individual queued emails (from review-mode senders).

```bash
poetry run newsletter-archiver review
```

For each email, choose:
- **a** - approve (archive the email)
- **d** - deny (discard)
- **s** - skip (leave for later)
- **q** - quit

## Archive Structure

Newsletters are saved as both Markdown and HTML:

```
archives/
  2025/
    06/
      stratechery/
        2025-06-15_article-title.md
        2025-06-15_article-title.html
      the-economist/
        2025-06-15_article-title.md
```

Directory names are determined by a **publications mapping** (`~/.newsletter-archive/publications.yaml`) that maps sender emails to publication names:

```yaml
email@stratechery.com: Stratechery
newsletters@e.economist.com: The Economist
noreply@e.economist.com: The Economist
```

Multiple sender emails can map to the same publication, so all emails land in one directory regardless of which address sent them. If a sender isn't in the mapping, the directory falls back to a slugified version of the sender name.

The Markdown files include YAML frontmatter with metadata (title, sender, date, word count, reading time).

## Storage

The archive is split across two locations:

- **Archive files** (Markdown + HTML): configurable, defaults to `~/.newsletter-archive/`. Can be placed on a cloud-synced drive for backup.
- **Database + auth tokens**: `~/.newsletter-archive/` on the local filesystem. SQLite should not be placed on a cloud-synced drive to avoid corruption.

## Transactional Email Filtering

Emails from approved senders are filtered by subject line to skip non-newsletter content like receipts and account notifications. Patterns include:

- Receipts ("your receipt", "your order", "your invoice")
- Account emails ("confirm your", "verify your", "password reset")
- Renewal notices ("will renew", "subscription renewal")
- Welcome emails ("welcome to")

Use `--dry-run` to audit what gets filtered.

## Development

```bash
# Run tests
poetry run pytest

# Run tests with verbose output
poetry run pytest -v
```

## Authentication

Uses Microsoft's device code flow for authentication. On first run, you'll be prompted to:

1. Open a URL in your browser
2. Enter a code
3. Sign in with your Microsoft account

The token is cached locally and refreshed automatically on subsequent runs.
