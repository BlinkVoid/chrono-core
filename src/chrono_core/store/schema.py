from __future__ import annotations

SCHEMA_VERSION = 6

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    phase TEXT,
    lifecycle_phase TEXT,
    summary TEXT,
    priority TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    owner TEXT,
    description_usage TEXT,
    current_progress TEXT,
    notes TEXT,
    other_factors TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_inventory (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    workspace_root TEXT NOT NULL,
    marker TEXT NOT NULL,
    depth INTEGER NOT NULL,
    last_seen_at TEXT,
    missing_since TEXT,
    status_before_missing TEXT,
    last_error_json TEXT,
    is_git INTEGER NOT NULL DEFAULT 0,
    branch TEXT,
    detached INTEGER NOT NULL DEFAULT 0,
    head_sha TEXT,
    head_subject TEXT,
    remote_name TEXT,
    remote_url TEXT,
    default_branch TEXT,
    dirty INTEGER NOT NULL DEFAULT 0,
    changed_count INTEGER NOT NULL DEFAULT 0,
    untracked_count INTEGER NOT NULL DEFAULT 0,
    collected_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    started_at TEXT,
    ended_at TEXT NOT NULL,
    agent_name TEXT,
    summary TEXT NOT NULL,
    git_branch TEXT,
    git_head TEXT,
    git_dirty INTEGER NOT NULL DEFAULT 0,
    raw_payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'accepted',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blockers (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    detail TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS next_actions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    title TEXT,
    doc_type TEXT,
    observed_at TEXT NOT NULL,
    freshness TEXT NOT NULL DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT,
    observed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE VIRTUAL TABLE IF NOT EXISTS observation_fts USING fts5(
    content,
    source,
    content='observations',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS observations_fts_insert
AFTER INSERT ON observations BEGIN
    INSERT INTO observation_fts (rowid, content, source)
    VALUES (new.rowid, new.content, new.source);
END;

CREATE TRIGGER IF NOT EXISTS observations_fts_delete
AFTER DELETE ON observations BEGIN
    INSERT INTO observation_fts (observation_fts, rowid, content, source)
    VALUES ('delete', old.rowid, old.content, old.source);
END;

CREATE TRIGGER IF NOT EXISTS observations_fts_update
AFTER UPDATE ON observations BEGIN
    INSERT INTO observation_fts (observation_fts, rowid, content, source)
    VALUES ('delete', old.rowid, old.content, old.source);
    INSERT INTO observation_fts (rowid, content, source)
    VALUES (new.rowid, new.content, new.source);
END;

CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    statement TEXT NOT NULL DEFAULT '',
    category TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    source TEXT NOT NULL DEFAULT 'authored',
    source_ref TEXT,
    projects_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS pattern_fts USING fts5(
    title, statement, content='patterns', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS patterns_fts_insert
AFTER INSERT ON patterns BEGIN
    INSERT INTO pattern_fts (rowid, title, statement) VALUES (new.rowid, new.title, new.statement);
END;

CREATE TRIGGER IF NOT EXISTS patterns_fts_delete
AFTER DELETE ON patterns BEGIN
    INSERT INTO pattern_fts (pattern_fts, rowid, title, statement)
    VALUES ('delete', old.rowid, old.title, old.statement);
END;

CREATE TRIGGER IF NOT EXISTS patterns_fts_update
AFTER UPDATE ON patterns BEGIN
    INSERT INTO pattern_fts (pattern_fts, rowid, title, statement)
    VALUES ('delete', old.rowid, old.title, old.statement);
    INSERT INTO pattern_fts (rowid, title, statement) VALUES (new.rowid, new.title, new.statement);
END;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""
