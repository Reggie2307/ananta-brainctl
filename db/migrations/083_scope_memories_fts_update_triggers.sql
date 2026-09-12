-- Migration 083: scope memories_fts update triggers to indexed columns + gate flags
--
-- The memories_fts update triggers (memories_fts_update_delete /
-- memories_fts_update_insert) originally fired on ANY UPDATE to a memory row.
-- The recall-count/confidence/labile bump that cmd_search performs after every
-- search therefore ran the delete leg (removing the row's tokens) followed by
-- the insert leg, which on external-content FTS5 does not reliably rebuild the
-- inverted index. Result: the first search silently corrupted the index and
-- every subsequent search returned zero hits (issue #97-3).
--
-- Scope both triggers to the columns that actually affect the index — content,
-- category, tags — plus the two gate flags (indexed, retired_at). Recall-count
-- updates no longer touch the index, while the 0→1 promotion, 1→0 de-index,
-- and retire→purge transitions still do.
--
-- Supersedes the unscoped forms created by migrations 031, 048, and 052.

DROP TRIGGER IF EXISTS memories_fts_update_delete;
DROP TRIGGER IF EXISTS memories_fts_update_insert;

CREATE TRIGGER memories_fts_update_delete AFTER UPDATE OF content, category, tags, indexed, retired_at ON memories WHEN old.indexed = 1 BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, category, tags)
    VALUES ('delete', old.id, old.content, old.category, old.tags);
END;

CREATE TRIGGER memories_fts_update_insert AFTER UPDATE OF content, category, tags, indexed, retired_at ON memories WHEN new.indexed = 1 AND new.retired_at IS NULL BEGIN
    INSERT INTO memories_fts(rowid, content, category, tags)
    VALUES (new.id, new.content, new.category, new.tags);
END;
