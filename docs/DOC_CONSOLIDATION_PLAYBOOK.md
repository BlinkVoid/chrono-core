# Doc Consolidation Playbook

A battle-tested approach for reconciling a project's scattered, partly-stale design
docs against canonical state (the code), distilled from a real multi-wave run in the
InternalProject project (June 2026). This is the concrete realization of
[Management Workflows](MANAGEMENT_WORKFLOWS.md) Workflow 4 (Documentation
Reconciliation) and a dedicated management session — captured here as an input to
Chrono Core's design.

## Why this is here

Chrono Core's whole premise is that project state drifts: README says Phase 1,
sessions say Phase 2; two design docs recommend incompatible approaches; a decision
lives in a handoff but never reached an ADR. The InternalProject run hit every one of these
and resolved them with a repeatable loop. The mechanics below are candidate behaviors
for Chrono Core's management session and documentation-reconciliation workflow.

## The problem it solved

InternalProject had ~25 design docs accumulated over months: overlapping, some describing
planned work that had since shipped (or shipped differently), some citing line numbers
that had drifted, some contradicting the code outright. Goal: one navigable design
reference — a refreshed architecture map, one verified doc per real subsystem, a single
live TODO, a clean archive — with **every claim traceable to code**.

## Core principles (the non-negotiables)

1. **Code wins.** Where a doc and the code disagree, the code is truth. The doc is
   corrected and the disagreement is *recorded explicitly*, never silently overwritten.
2. **Every claim traces to a `file:line`.** No invented APIs. Symbols verified with
   `rg` before being cited. This is what makes a doc *checkable* instead of *trusted*.
3. **Nothing is deleted.** Stale/historical docs move to `archive/` via `git mv` —
   reversible, auditable, never `rm`.
4. **Capture the choice and the why,** not just the what — one short "why" line per
   non-obvious decision.
5. **Findings are queued, not applied silently.** Discrepancies between doc and code go
   to a human-reviewable discrepancy log, mirroring Workflow 4's "review items" rule.

## The execution loop

Run as waves, each doc a discrete task, each task through a fixed gate:

```
implementer → verification gate → commit → review (spec + quality) → fix loop → ledger
```

- **Waves.** (0) mechanical triage — archive moves, TODO collapse, index, so the tree
  is clean first. (1–2) write the map + one verified doc per subsystem. (3) cross-link
  + final discrepancy sweep + index finalize.
- **One fresh worker per doc.** Each task gets an isolated worker with exactly the
  context it needs (its brief, the files it touches, decisions from prior tasks) — not
  the whole accumulated history. Keeps each worker focused and the coordinator's context
  lean.
- **Review every task.** A separate reviewer checks two things: spec compliance (did it
  document what was asked, nothing more/less) and quality (accurate refs, house style,
  discrepancies flagged). Critical/Important findings go back through a fix loop;
  Minor findings are recorded for a final triage pass.
- **Broad review at the end.** After all per-task gates, one whole-branch review on the
  most capable model catches cross-doc issues the per-task reviews couldn't see.

## The verification gate (the "test" for a doc)

A doc has no unit tests, so the gate *is* the test. Run before every commit:

```bash
# 1. No placeholders left behind
rg -n 'TBD|TODO:|FIXME|XXX|\?\?\?|<placeholder>|fill in|implement later' <doc>
# 2. Opens with a link to the spine/architecture doc (navigability)
rg -n '<spine-doc-name>' <doc>
# 3. Has file:line traceability (expect several hits)
rg -nc '\.py:[0-9]+|\.py`|`[a-z_]+\.py' <doc>
```

Expected: (1) no output, (2) ≥1 hit, (3) ≥3 hits. Fix before committing. A doc that
fails the gate is not done.

Internal-link integrity is its own gate — verify every `](*.md)` target resolves
before the run is declared complete.

## The durable ledger (the most important mechanic to steal)

A coordinator's conversation memory does not survive compaction or a session restart.
The single most expensive failure mode is re-doing completed work because the
coordinator lost its place. The fix: a **ledger file** on disk, updated in the same
step as each task's bookkeeping.

- One append-only line per completed task: `Task N: complete (commits <base>..<head>,
  review clean)` plus any discrepancies and deferred Minor findings.
- The commits it names exist in git even when the coordinator no longer remembers
  creating them. **On resume, trust the ledger + `git log` over recollection.**
- This is exactly Chrono Core's handoff/resume contract at the granularity of a
  single management run — the ledger is a session-handoff record for an in-flight job.

## The discrepancy log (Workflow 4 output, made concrete)

Every doc/code mismatch found during the run is collected into one dated archive file
for human review — grouped by subsystem, each with its `file:line` and a one-line
"code says X / doc said Y". Real examples from the InternalProject run:

- A docstring claimed a 3-tuple return; the protocol and all call-sites used a 4-tuple.
- A comment said "19 core tools"; the code registered 26 (a whole tool group added
  after the comment was written).
- A doc/handoff premise said a UI was "an empty stub"; it was actually fully functional
  end-to-end — only the *next* phase was unbuilt. (A stale **belief**, not stale code.)
- Function args appeared swapped against a signature, so a state transition may silently
  no-op — a latent bug surfaced purely by reconciling docs against code.

The log is the deliverable, not a side effect: it turns "the docs were wrong" into a
prioritized, evidence-backed worklist.

## Failure modes observed (design these out)

- **Stale beliefs outlive stale docs.** The "empty stub" premise was wrong and had been
  copied forward through handoffs. Reconciliation must check *carried-forward claims*
  against current code, not just doc-vs-doc.
- **Citations drift silently.** Line numbers rot every time code moves. Most review
  findings were off-by-a-few line refs. Implication for Chrono Core: prefer
  symbol/anchor references over raw line numbers where possible, or re-validate line
  refs mechanically.
- **A bad checker command poisons the gate.** A link-checker that omitted a flag emitted
  false positives and cost a worker ~an hour chasing phantom broken links. Gate commands
  themselves need to be correct and tested — ship them as verified tooling, not copied
  prose.
- **Long-running workers need liveness signals.** "Is it still working or hung?" was
  unanswerable without inspecting the worker's transcript timestamp and its file-edit
  mtimes. A management run should surface heartbeat/progress, not just start/finish.

## What Chrono Core should take from this

| Mechanic here | Chrono Core home |
|---|---|
| Durable ledger, resume from it | Session handoff + resume (the canonical write/read path) |
| Discrepancy log, queued for review | Workflow 4 documentation-drift report |
| "Code wins," every claim `file:line` | Facts-before-synthesis; evidence-backed advice |
| Per-doc verification gate | Automated doc-quality / staleness checks |
| Archive via `git mv`, never delete | "Database canonical, markdown useful" + reversible history |
| Wave 0 triage before writing | Management session: reconcile state before distilling |

The run proves the workflow by hand. The product's job is to make it cheap and
repeatable: capture the ledger automatically, generate the discrepancy log from a
doc-vs-code scan, and surface the drift report and evidence-backed advice without a
human driving each task.

## Source

InternalProject project, `feat/swap-layer-deepseek-uv` branch, plan
`docs/superpowers/plans/2026-06-27-docs-consolidation.md`, executed via the
subagent-driven-development loop. Run dated 2026-06-27/28.
