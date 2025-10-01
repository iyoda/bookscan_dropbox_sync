# Repository Guidelines

## Project Structure & Module Organization
- Source code lives under `src/bds/` using a src-layout. Key modules: `cli.py` (Typer CLI), `config.py` (Pydantic settings), `bookscan_client.py`, `dropbox_client.py`, `sync_planner.py`, `transfer.py`, `state_store.py`, `failure_store.py`, and `util/`.
- Tests are in `tests/` with `test_*.py` files (pytest). Sample HTML lives in `samples/`.
- Entry point is `bds` (via `pyproject.toml`), or `python -m bds.cli` with `PYTHONPATH=src` during local dev.

## Build, Test, and Development Commands
- Setup: `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Lint/format: `ruff check .` (auto-fix: `ruff check --fix .`), `black .`
- Type check: `mypy src` (tests are excluded by config)
- Tests: `pytest` (coverage via `--cov=bds` is configured). Example: `pytest tests/test_cli_smoke.py::test_sync_dry_run_smoke -q`
- Run CLI locally: `bds --help`, `bds sync --dry-run` or `PYTHONPATH=src python -m bds.cli list`
- Pre-commit: `pre-commit install && pre-commit run --all-files`

## Coding Style & Naming Conventions
- Python 3.11, 4-space indentation, line length 100 (Black/Ruff enforce).
- Use type hints everywhere (mypy: `disallow_untyped_defs=True`). Prefer explicit `Optional[...]` and return types.
- Naming: modules/files `snake_case.py`; classes `PascalCase`; functions/vars `snake_case`.
- Imports are sorted (Ruff isort). Keep first‑party as `bds`.

## Testing Guidelines
- Framework: pytest. Place tests under `tests/` and name `test_*.py`.
- Use `typer.testing.CliRunner` for CLI tests; avoid network by using `BOOKSCAN_DEBUG_HTML_PATH` (e.g., `samples/bookscan_list_sample.html`).
- Aim to keep/add coverage; run `pytest -q` before pushing.

## Commit & Pull Request Guidelines
- Use Conventional Commits where possible: `feat:`, `fix:`, `docs:`, `test:`, `chore:`. Example: `feat: add SQLite state backend migration`.
- PRs should include: a clear description, linked issues, before/after notes or sample CLI output, and test coverage for changes.
- CI-like checklist before opening PR: `ruff`, `black`, `mypy`, `pytest`, and `pre-commit` all clean.

## Security & Configuration Tips
- Never commit secrets. Use `.env` or `.envrc`; see `.env.example`. Logs mask sensitive values.
- For local dry-run, set `BOOKSCAN_DEBUG_HTML_PATH=samples/bookscan_list_sample.html` to avoid real network calls.
- Optional audit: `pip-audit -l` (available via pre-commit).

