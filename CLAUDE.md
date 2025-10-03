# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python CLI tool that syncs downloadable PDFs from Bookscan (ブックスキャン) to Dropbox. It performs incremental synchronization to avoid duplicate uploads and is designed for scheduled execution (cron/launchd).

**Language:** Python 3.11+
**CLI Framework:** Typer
**Main Entry Point:** `bds` command (via `src/bds/cli.py`)

## Development Setup

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies (including dev tools)
pip install -e ".[dev]"

# Setup pre-commit hooks
pre-commit install
pre-commit run --all-files  # Initial formatting
```

## Common Commands

### Running the CLI

```bash
# Run via installed command
bds --help
bds sync --dry-run
bds list

# Run without installation (development)
PYTHONPATH=src python -m bds.cli sync --dry-run
PYTHONPATH=src python -m bds.cli list
```

### Testing

```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/test_cli_smoke.py

# Run with verbose output
pytest -v

# Run without coverage report
pytest --no-cov
```

### Linting & Formatting

```bash
# Run all pre-commit checks
pre-commit run --all-files

# Individual tools
ruff check src/ tests/
black src/ tests/
mypy src/
```

### CI/CD

The project uses GitHub Actions (`.github/workflows/ci.yml`) which runs:
- Pre-commit hooks (ruff, black, mypy)
- Pytest with coverage
- pip-audit security scan

## Architecture

### Core Components

**BookscanClient** ([src/bds/bookscan_client.py](src/bds/bookscan_client.py))
- Handles authentication (email/password/TOTP)
- Scrapes downloadable item list from Bookscan HTML
- Downloads PDF files
- Supports debug mode via `BOOKSCAN_DEBUG_HTML_PATH` for development without real HTTP access
- Parses multiple HTML formats: `.download-item` format, showbook.php pages, bookshelf_all_list.php

**DropboxClient** ([src/bds/dropbox_client.py](src/bds/dropbox_client.py))
- File upload with chunked session upload for large files (>8MB by default)
- Folder creation and metadata retrieval
- Supports both fixed access token and OAuth refresh token workflows
- Uses `dropbox` SDK with automatic retry handling for rate limits

**StateStore** ([src/bds/state_store.py](src/bds/state_store.py))
- Tracks synchronized items to enable incremental sync
- Supports both JSON (`.state/state.json`) and SQLite (`.state/state.db`) backends
- Auto-migrates from JSON to SQLite on first run if JSON file exists
- Stores: book_id, updated_at, size, hash, dropbox_path

**SyncPlanner** ([src/bds/sync_planner.py](src/bds/sync_planner.py))
- Compares Bookscan items against StateStore to determine what needs uploading
- Applies safe filename normalization via `util.safe_filename()`
- Handles update detection based on timestamp and size changes

**TransferEngine** ([src/bds/transfer.py](src/bds/transfer.py))
- Orchestrates download → temporary storage → Dropbox upload flow
- Implements retry logic with exponential backoff using tenacity
- Verifies file integrity using Dropbox content hash
- Resolves naming conflicts by appending version suffixes (v2, v3, etc.)
- Supports concurrent transfers via ThreadPoolExecutor

**FailureStore** ([src/bds/failure_store.py](src/bds/failure_store.py))
- Logs failed operations to `.logs/failures.jsonl`
- Classifies exceptions as retryable or permanent
- Enables analysis of sync failures

### Configuration

All settings are managed via [src/bds/config.py](src/bds/config.py) using pydantic-settings. Configuration is loaded from environment variables or `.env` file.

Key environment variables:
- `BOOKSCAN_EMAIL`, `BOOKSCAN_PASSWORD`, `BOOKSCAN_TOTP_SECRET`
- `DROPBOX_ACCESS_TOKEN` (simple) or `DROPBOX_REFRESH_TOKEN` + `DROPBOX_APP_KEY` (recommended)
- `DROPBOX_DEST_ROOT` (default: `/Apps/bookscan-sync`)
- `STATE_BACKEND` (`json` or `sqlite`)
- `RATE_LIMIT_QPS` (default: 0.5 = 2 seconds between requests)
- `RETRY_MAX_ATTEMPTS`, `RETRY_BACKOFF_MULTIPLIER`, `RETRY_BACKOFF_MAX`

See `.env.example` for full reference.

### Data Flow

1. **Authenticate** - Login to Bookscan and Dropbox
2. **Fetch** - Retrieve list of downloadable items from Bookscan
3. **Plan** - Compare with StateStore to determine delta (new/updated items)
4. **Transfer** - Download to temp directory → verify → upload to Dropbox
5. **Record** - Update StateStore with successful transfers

### CLI Commands

- `bds sync` - Perform synchronization
  - `--dry-run` - Show planned actions without uploading
  - `--since YYYY-MM-DD` - Only sync items updated after date
  - `--exclude-ext EXT` - Exclude file extensions
  - `--min-size N`, `--max-size N` - Filter by file size (bytes)
  - `--exclude-keyword WORD` - Exclude items by keyword in title
  - `--json-log` - Output logs in JSON format
  - `--log-file PATH` - Write logs to file (can be directory or file path)

- `bds list` - Display items from Bookscan or StateStore
  - `--source [bookscan|state]` - Choose source (default: bookscan)

- `bds login dropbox` - OAuth PKCE flow helper for Dropbox authentication
- `bds logout dropbox` - Revoke Dropbox access token

### Exit Codes

- `0` - Success
- `1` - Runtime error (initialization, transfer, I/O)
- `2` - Configuration error (e.g., missing required credentials)

## Development Workflows

### Debug Mode (No Real HTTP)

Use `BOOKSCAN_DEBUG_HTML_PATH` to test sync logic without accessing real Bookscan:

```bash
# Use sample HTML file
export BOOKSCAN_DEBUG_HTML_PATH=samples/bookscan_list_sample.html
python -m bds.cli sync --dry-run

# Use directory (merges all *.html files)
export BOOKSCAN_DEBUG_HTML_PATH=samples/
python -m bds.cli list

# Use glob pattern
export BOOKSCAN_DEBUG_HTML_PATH="samples/*.html"
python -m bds.cli sync --dry-run
```

### Testing Strategy

Tests are in `tests/` directory:
- Unit tests for parsing, naming, filters, retry logic
- Integration tests mocking Bookscan/Dropbox clients
- CLI smoke tests for exit codes and command behavior
- See `TODO.md` for test coverage goals (80% target)

### Adding New Features

When adding features that require environment variables:
1. Add field to `Settings` class in [src/bds/config.py](src/bds/config.py)
2. Update `.env.example`
3. Document in README.md (if user-facing)
4. Add validation in `Settings.validate_for_m1()` if required for operation

When adding new CLI commands:
1. Add command to [src/bds/cli.py](src/bds/cli.py) (may use sub-apps like `login_app`, `logout_app`)
2. Add corresponding tests in `tests/test_cli_*.py`
3. Update README.md usage section

## Important Notes

### Secret Masking

The CLI automatically masks sensitive values in logs via `SecretMaskFilter`. Masked fields include:
- `DROPBOX_ACCESS_TOKEN`, `DROPBOX_REFRESH_TOKEN`, `DROPBOX_APP_SECRET`
- `BOOKSCAN_PASSWORD`, `BOOKSCAN_TOTP_SECRET`

### Rate Limiting

This tool respects service terms by implementing rate limiting:
- `RATE_LIMIT_QPS` controls global request rate (default: 0.5 QPS = 2s between requests)
- Service-specific: `BOOKSCAN_RATE_LIMIT_QPS`, `DROPBOX_RATE_LIMIT_QPS`
- Implemented via `RateLimiter` class
- Never set rate limits too high to avoid violating service terms

### Retry Logic

Uses tenacity with exponential backoff:
- Configured via `RETRY_MAX_ATTEMPTS`, `RETRY_BACKOFF_MULTIPLIER`, `RETRY_BACKOFF_MAX`
- Only retries errors classified as retryable (429, 5xx, network errors)
- Permanent failures (4xx except 429) are logged to FailureStore

### File Naming

`util.safe_filename()` normalizes titles:
- Removes/replaces unsafe characters for filesystems
- Handles Japanese characters, spaces, special symbols
- Truncates overly long names

### Conflict Resolution

When uploading to Dropbox:
1. Check if file exists with same content hash → skip
2. If different content → append version suffix `(v2)`, `(v3)`, etc.
3. Uses Dropbox WriteMode.add to prevent overwrites

## Project Structure

```
src/bds/
  ├── __init__.py
  ├── cli.py              # CLI entry point (Typer app)
  ├── config.py           # Settings (pydantic-settings)
  ├── bookscan_client.py  # Bookscan scraping & download
  ├── dropbox_client.py   # Dropbox SDK wrapper
  ├── state_store.py      # JSON/SQLite state persistence
  ├── sync_planner.py     # Diff calculation
  ├── transfer.py         # Download/upload orchestration
  ├── failure_store.py    # Failure logging
  └── util/               # Utilities (filename, hash, TOTP, etc.)

tests/                    # pytest tests
samples/                  # Sample HTML for debug mode
.state/                   # State files (gitignored)
.cache/                   # Download temp files (gitignored)
.logs/                    # Log files (gitignored)
```

## Milestones & Progress

See [TODO.md](TODO.md) for detailed milestone tracking:
- **M0** (Design & Foundation) - ✅ Complete
- **M1** (Minimum Viable Sync) - ✅ Complete
- **M2** (Practical CLI) - ✅ Complete
- **M3** (Reliability & Scale) - ✅ Complete
- **M4** (OAuth & 2FA) - 🚧 In Progress
- **M5** (Distribution & Operations) - 📋 Planned

Current status: M3 complete with retry, chunked uploads, concurrent transfers, and failure tracking. M4 OAuth implementation is partially complete.
