# Contributing to Chrono Core

Thanks for your interest. Chrono Core is a young project (0.x), so the process is
deliberately light.

## Before you start

Open an issue before writing a large change. Chrono Core stores project state in a
versioned SQLite schema, and changes that touch the schema, the CLI contract, or the
MCP tool surface need a design conversation first — see `docs/SYSTEM_DESIGN.md` and
`docs/MVP_CONTRACT.md`.

Small fixes (bugs, docs, tests) need no prior issue. Just send the PR.

## Development setup

```bash
git clone https://github.com/BlinkVoid/chrono-core
cd chrono-core
uv venv
uv pip install -e ".[dev]"
```

## Before you open a PR

```bash
ruff check .
pytest -q
```

Both must pass. CI runs the same two commands on Python 3.12 and 3.13.

## House rules

- **Tests use `tmp_path`.** Never write to a fixed path on disk — parallel runs and
  stale files from other branches will break the suite.
- **No absolute personal paths.** Nothing under `/home/<you>` or `/Users/<you>` should
  appear in code, tests, or docs. Use `~`, `tmp_path`, or an env var.
- **Schema changes need a migration.** Add it under `src/chrono_core/store/migrations.py`
  and bump `SCHEMA_VERSION`. Chrono Core refuses to open a database newer than the code,
  so a missing migration is a hard failure, not a warning.
- **Document functional changes in the same PR.** If a change alters architecture,
  control flow, or a design decision, update the relevant doc under `docs/` rather than
  leaving the reasoning in the commit message.

## Commit messages

Conventional-commit prefixes (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`) — one
logical change per commit.
