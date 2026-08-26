# Chrono Core: Record Graph Export — Design (follow-up)

Date: 2026-08-26
Status: Implemented (branch `feat/record-graph-export`;
`chrono_core.export.graph`, `chrono export graph`) — session-hub model,
separate subcommand (decisions 2026-08-26, below)
Origin: raised while implementing `chrono export json` ("does chrono have a
graph DB? can it produce a graph of problems/solutions/decisions?")
Prerequisite: `chrono export json` (see
`2026-08-26-record-export-json-design.md`)

## Problem

Chrono holds the raw material of a problem/solution graph — decisions,
blockers, next actions, sessions — but exposes no way to consume it *as a
graph*. Consumers (ProjectA vault sync, `_MetaFactory` distillation) would
have to re-derive relationships themselves.

There is **no dedicated graph database**, by design (`docs/SYSTEM_DESIGN.md`:
"Start with SQLite, not a dedicated graph database"). The schema already has a
graph-shaped `edges` table, but nothing populates or reads it today.
Relationships exist implicitly:

- `session_id` on every record → records created in the same session are
  candidates for "decision addressed blocker" edges;
- `next_actions.supersedes_id` → explicit supersession chains;
- project/session foreign keys → containment edges.

## Goal

A derived, read-only graph view packaged as a reusable function (and later,
optionally, an MCP tool / CLI flag): nodes = records, edges = typed
relationships, emitted as plain JSON `{nodes, edges}`.

## Design sketch

- `build_record_graph(store, project_id) -> {"nodes": [...], "edges": [...]}`
  in a new module beside `export/json.py`.
- Node: `{"id", "type" (decision|blocker|next_action|session), "label",
  "status", "created_at"}`.
- Edges, in priority order:
  1. `supersedes` from explicit `supersedes_id`;
  2. `co_occurs_in_session` linking each record to its creating session
     (transitive problem↔solution pairs derivable client-side);
  3. future: explicit edges written into the `edges` table as capture grows
     richer (e.g., handoff payloads gain `resolves_blocker` references).
- No traversal engine: consumers get JSON; Kuzu/Neo4j stays out per the
  standing decision until traversal queries justify it.

## Non-goals

- No writes to the `edges` table in v1 (derived view only).
- No similarity/semantic edges (that is Phase 4 pattern-index territory).

## Resolved decisions (2026-08-26)

- **Session hub model.** Session co-occurrence produces only record→session
  edges (`relation: "captured_in"`); no direct blocker→decision edges. Clients
  derive problem↔solution pairs by walking the session hub. Keeps the edge
  count linear and avoids encoding a heuristic as data.
- **Separate subcommand** `chrono export graph` with its own payload
  (`project_id`, `project_name`, `project_path`, `exported_at`, `nodes`,
  `edges`) — the flat-record and graph views stay independently consumable.
- Graph is status-blind: closed records appear like any other node.
- Supersession edges run old→new: `{"source": <old action id>,
  "target": <new action id>, "relation": "superseded_by"}` from
  `next_actions.supersedes_id`.
- Project resolution and error semantics mirror `chrono export json`
  (exactly one of `--project-id`/`--cwd`; unregistered `--cwd` projects
  export an empty graph; unknown explicit ids fail non-zero).
- Nodes and edges are deterministically ordered — nodes by
  `(type, created_at, id)`, edges by `(source, relation, target)`.

## Open questions

None for v1; future edges written into the `edges` table should be appended
to the derived output once capture grows richer (e.g., explicit
`resolves_blocker` references).
