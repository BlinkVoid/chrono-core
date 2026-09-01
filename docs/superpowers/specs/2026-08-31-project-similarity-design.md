# Chrono Core: Project Similarity Search — Design

Date: 2026-08-31
Status: Approved implementation contract
Phase: 4 — Cross-project Intelligence
Related: `docs/ROADMAP.md` ("project similarity search"),
`docs/superpowers/specs/2026-08-26-pattern-index-design.md`

## Problem

Chrono Core can search individual observations and recommend reusable patterns,
but it cannot answer which other managed projects contain related operational
knowledge. Agents therefore need to know a project name in advance before they
can reuse its decisions, observations, or distilled state.

## Goal

Add a deterministic, local-only query that ranks other projects against a
selected project using the continuity data already in SQLite. Results must be
explainable, stable, read-only, and available through both the CLI and MCP.

## Decisions

1. **Corpus:** each project document combines its distilled `phase` and
   `summary` with its captured observation content. Project names and paths are
   display metadata, not ranking input.
2. **Scoring:** tokenize with `chrono_core.textutil.tokenize`, then compute
   cosine similarity over sublinear-TF/IDF term weights. Terms present in every
   project contribute little; repeated evidence has diminishing returns.
3. **Explainability:** every result includes up to eight `shared_terms`, ordered
   by their contribution to the cosine score and then alphabetically.
4. **Scope:** compare all registered projects except the selected project.
   Return only positive-score matches, ordered by score descending and then by
   stable project identity.
5. **Storage:** compute on demand. No schema migration, embedding index, network
   request, or model dependency is introduced in this slice.
6. **Safety:** opening and querying an existing database is read-only. An
   unknown project returns a structured error and must not register it as a
   side effect.

Scores are rounded for a stable JSON contract. A zero or negative limit returns
an empty result set. Empty project evidence also returns no matches.

## Interfaces

### Store

`Store.find_similar_projects(project_id, *, limit=5) -> list[dict]`

Each result contains:

```json
{
  "project_id": "...",
  "project_name": "...",
  "project_path": "...",
  "phase": "...",
  "summary": "...",
  "score": 0.742381,
  "shared_terms": ["continuity", "sqlite"]
}
```

### Shared service

Resolve the project at `cwd` within `workspace_root`, verify that its physical
path already exists in the continuity database, call the Store query, and
return:

```json
{
  "ok": true,
  "project_id": "...",
  "count": 1,
  "results": []
}
```

### CLI

`chrono similar --cwd PATH [--workspace-root PATH] [--limit 5] [--db-path PATH]`

The command prints the stable JSON service envelope and exits non-zero for a
missing database or unknown project.

### MCP

`chrono_core_find_similar_projects(cwd, workspace_root=None, db_path=None,
limit=5)` exposes the same service envelope.

## Non-goals

- Semantic embeddings, LLM classification, or remote vector services.
- Persisted similarity edges or automatic project grouping.
- Mixing reusable-pattern promotion into similarity ranking.
- Mutating project state during a query.

## Testing

1. Stronger overlap ranks ahead of weaker overlap.
2. The selected project and zero-overlap projects are excluded.
3. Distilled phase/summary can establish similarity without observations.
4. Shared terms are deterministic and explain the score ordering.
5. Empty evidence, unknown projects, and non-positive limits are safe.
6. CLI parsing/output and MCP handler/registration follow the service contract.
7. The full existing suite remains green and schema version remains unchanged.
