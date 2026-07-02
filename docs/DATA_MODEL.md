# Data Model

## Core Entities

- `Project` — workspace project, repo, sandbox, or concept folder.
- `Session` — one contiguous human/agent work session.
- `AgentRun` — a specific AI agent execution inside a session.
- `Task` — actionable unit of work.
- `Milestone` — larger project objective.
- `Blocker` — condition preventing progress.
- `Decision` — design/product/ops choice with rationale.
- `Spec` — expected behavior or design contract.
- `DesignDoc` — project documentation artifact.
- `Todo` — loose action extracted from docs or handoff.
- `Artifact` — changed file, generated doc, result, commit, test output.
- `CodeArea` — package/module/component affected by work.
- `Insight` — reusable lesson learned.
- `ReusablePattern` — distilled cross-project implementation/design pattern.
- `Question` — unresolved product/design/technical question.

## Relationship Types

Represent relationships through a generic edge table:

- `SESSION_FOR_PROJECT`
- `AGENT_RUN_IN_SESSION`
- `SESSION_PRODUCED_ARTIFACT`
- `TASK_BLOCKED_BY`
- `BLOCKER_RESOLVED_BY`
- `DECISION_AFFECTS_CODE_AREA`
- `DECISION_SUPERSEDES_DECISION`
- `SPEC_IMPLEMENTED_BY_TASK`
- `TODO_DERIVED_FROM_DOC`
- `INSIGHT_REUSED_IN_PROJECT`
- `PROJECT_SIMILAR_TO_PROJECT`
- `PATTERN_APPLIES_TO_PROJECT`
- `DOC_CONTRADICTS_DOC`
- `DOC_SUPERSEDED_BY_DOC`

## SQLite Shape

Initial tables:

- `projects`
- `sessions`
- `agent_runs`
- `tasks`
- `milestones`
- `blockers`
- `decisions`
- `documents`
- `artifacts`
- `insights`
- `patterns`
- `questions`
- `edges`
- `observations`

`observations` stores raw captured facts before distillation. This prevents management synthesis from overwriting original evidence.

## Canonical vs Derived

Canonical:

- SQLite records
- raw handoff observations
- explicit decisions/blockers/tasks

Derived:

- markdown wiki pages
- resume-context packs
- health review reports
- stale-doc warnings
- pattern recommendations

## Session Handoff Minimum Payload

```json
{
  "cwd": "~/workspace/example",
  "summary": "Implemented provider config and updated tests.",
  "files_changed": ["src/config.py", "tests/test_config.py"],
  "tests": ["uv run pytest -q: passed"],
  "decisions": [
    {
      "title": "Use provider-neutral LLM interface",
      "rationale": "Keeps Bedrock and OpenAI-compatible providers swappable."
    }
  ],
  "blockers": [
    {
      "title": "Live smoke requires credentials",
      "status": "open"
    }
  ],
  "next_actions": ["Run live smoke", "Update runbook"],
  "risks": ["No production credential path validated"]
}
```

## Resume Context Output

A resume context should be tiered:

1. 30-second summary.
2. Current status and phase.
3. Active blockers.
4. Next recommended actions.
5. Recent decisions.
6. Relevant docs/specs.
7. Stale or contradictory docs.
8. Reusable patterns from other projects.
