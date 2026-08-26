# Security Policy

## Supported versions

Chrono Core is pre-1.0. Only the latest release on `main` receives fixes.

## Reporting a vulnerability

Please report security issues privately through
[GitHub Security Advisories](https://github.com/BlinkVoid/chrono-core/security/advisories/new)
rather than opening a public issue.

Expect an initial response within 7 days.

## Threat model

Chrono Core is a **local-first, single-user tool**. It reads and writes a SQLite
database on the local filesystem and speaks MCP over stdio to a local agent. It opens
no network listeners and sends no telemetry.

Things that are in scope:

- SQL injection or path traversal reachable from CLI or MCP arguments
- A crafted project directory or database causing arbitrary code execution
- Unintended writes outside the configured workspace root or database path

Things that are **not** in scope:

- The contents of your own database. Chrono Core records what agents and sessions tell
  it, including file paths and free text. If you point it at sensitive material, that
  material is in the database in plaintext. Protect it with filesystem permissions.
- Trusting the agent. Chrono Core assumes the MCP client on the other end of stdio is
  one you chose to run.
