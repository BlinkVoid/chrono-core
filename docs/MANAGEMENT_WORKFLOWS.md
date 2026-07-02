# Management Workflows

## Workflow 1: Direct Session Handoff

An agent working in any project calls `continuity_core.session_handoff`.

The tool resolves the project from `cwd`, records raw facts, links changed files and git state, and updates the latest project state.

This is the lowest-friction write path and should work even for unknown projects.

## Workflow 2: Project Resume

A human or agent asks: "what is this project and what next?"

Continuity Core returns:

- one-paragraph project identity
- current phase
- last known good state
- recent sessions
- active blockers
- next actions
- key decisions
- docs to read first
- stale documentation warnings

## Workflow 3: Dedicated Management Session

A management session is a deeper maintenance run. It should not happen automatically after every project work session.

Inputs:

- recent handoffs
- current git/project state
- README/CONTEXT/PLAN/TODO/ADR docs
- workspace-intelligence project metadata
- MetaFactory patterns and insights

Outputs:

- distilled current project state
- updated task/blocker/decision records
- documentation drift report
- improvement advice
- recommended next work
- wiki export

## Workflow 4: Documentation Reconciliation

The system scans project docs and compares claims against canonical state.

Examples:

- README says Phase 1, latest sessions say Phase 2.
- TODO lists a blocker that a later session resolved.
- Two design docs recommend incompatible approaches.
- A major implementation decision exists in a handoff but not in an ADR/design doc.

Findings are queued as review items rather than silently overwritten.

## Workflow 5: Cross-Project Reuse

Continuity Core should connect current project problems to prior work.

Examples:

- "This provider abstraction resembles a collaborator's LLM client design."
- "Use Hub's ADR style for this architectural split."
- "This stale-doc problem appeared in ProjectX; run the same context cleanup."

Sources:

- MetaFactory consolidated patterns
- prior Continuity Core insights
- project/session graph relationships
- workspace-intelligence registry metadata

## Improvement Advice

A dedicated management session should generate advice based on current state and documentation quality.

Advice categories:

- missing docs
- stale docs
- missing ADRs
- unclear next actions
- unresolved blockers
- risky untested changes
- poor project phase definition
- reusable patterns not yet applied
- projects that should be paused, archived, or promoted

The advice should be evidence-backed and link to the observed records/docs that triggered it.
