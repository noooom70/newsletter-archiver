# Newsletter Archiver - Project Guide

## Git Workflow
- Default branch: `master` (not main)
- Use feature branches for new work, PR back into master
- Commit messages: short summary line, detail in body
- Before creating a PR, verify README.md is up to date with any new/changed commands or features
- Before creating a PR, verify `.claude/settings.json` has any new permissions needed

## Project Structure
- **Source code**: `src/newsletter_archiver/`
- **Archive files** (md/html): configured in `Settings.archive_dir`, stored on Proton Drive
- **SQLite DB + auth tokens**: `~/.newsletter-archive/` (local filesystem, never cloud-synced)
- **Publications mapping**: `~/.newsletter-archive/publications.yaml` (sender email → publication name)

## Key Design Decisions
- Approved senders filtered by transactional subject patterns only (not full is_newsletter heuristic)
- is_newsletter heuristic used only for discovering new senders during `--scan`
- SQLite stays on local filesystem to avoid cloud sync corruption
- Publication-based archive directory naming via YAML mapping; falls back to slugified sender name
- Invisible Unicode chars (email preheader padding) stripped during HTML→Markdown conversion and at index time

## Common Commands
```bash
# Daily update
poetry run newsletter-archiver fetch -u --auto

# Backfill a date range
poetry run newsletter-archiver fetch --from YYYY-MM-DD --to YYYY-MM-DD --auto

# Audit what the transactional filter skips
poetry run newsletter-archiver fetch -d 30 --dry-run

# Rebuild search indexes
poetry run newsletter-archiver index build --reindex

# Run tests
poetry run pytest
```
