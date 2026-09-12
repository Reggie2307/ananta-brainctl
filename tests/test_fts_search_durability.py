"""Regression tests: FTS search index must survive normal operation (issue #97-3).

The bug: `memories_fts` update triggers fired on ANY UPDATE to a memory row,
including the recall-count/confidence/labile bump that `cmd_search` performs
after every search. On external-content FTS5 the re-insert leg does not
reliably rebuild the inverted index, so the first search silently corrupted the
index and every subsequent search returned zero hits.

The fix scopes the triggers to `content, category, tags, indexed, retired_at`.
These tests build the DB the way production does (init_schema.sql + migrations),
then assert (a) the triggers are actually scoped afterward, and (b) the
transitions the scoping must preserve — recall, retire, promotion, de-index,
and content edit — all behave.
"""
import sqlite3

from agentmemory import migrate
from agentmemory.brain import Brain


def _build_full_db(path, agent="fts-test"):
    """Build a DB the way production does: init_schema.sql + migrate.run()."""
    b = Brain(db_path=str(path), agent_id=agent)
    migrate.run(str(path))
    return b


def _trigger_sql(path, name):
    conn = sqlite3.connect(str(path))
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def test_triggers_are_scoped_after_full_init(tmp_path):
    """init_schema + migrations must leave the update triggers scoped to indexed columns."""
    db = tmp_path / "brain.db"
    _build_full_db(db)
    scoped = "UPDATE OF content, category, tags, indexed, retired_at"
    for name in ("memories_fts_update_delete", "memories_fts_update_insert"):
        sql = _trigger_sql(db, name)
        assert scoped in sql, f"{name} not scoped after full init: {sql[:120]}..."


def test_repeated_search_is_consistent(tmp_path):
    """Searching twice must return the same results (index must not self-corrupt)."""
    b = _build_full_db(tmp_path / "brain.db")
    b.remember("the quick brown fox jumps", category="test", tags=["animal"])
    b.remember("a second memory about foxes in the woods", category="test", tags=["animal"])

    first = b.search("fox")
    second = b.search("fox")

    assert first, "first search should find the fox memories"
    assert second, "second search must still find the fox memories (FTS corruption regression)"
    assert len(first) == len(second), f"search results diverged: {len(first)} vs {len(second)}"


def test_retire_purges_from_search(tmp_path):
    """Retiring a memory must remove it from search."""
    b = _build_full_db(tmp_path / "brain.db")
    mid = b.remember("retire me please", category="test")
    assert b.search("retire"), "memory should be searchable before retire"
    b.forget(mid)
    assert not b.search("retire"), "retired memory must not appear in search"


def test_promotion_0_to_1_indexes(tmp_path):
    """Flipping indexed 0->1 must add the memory to the search index."""
    db = tmp_path / "brain.db"
    _build_full_db(db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO memories (agent_id, category, scope, content, memory_type, indexed) "
        "VALUES ('fts-test','test','global','promotion uniqueterm','episodic', 0)"
    )
    conn.commit()
    mid = conn.execute("SELECT id FROM memories WHERE content LIKE 'promotion%'").fetchone()[0]
    conn.close()

    assert not b_search(db, "uniqueterm"), "indexed=0 memory should not be searchable"

    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE memories SET indexed = 1 WHERE id = ?", (mid,))
    conn.commit()
    conn.close()

    assert b_search(db, "uniqueterm"), "promoted (indexed=1) memory should become searchable"


def test_deindex_1_to_0_removes(tmp_path):
    """Flipping indexed 1->0 must remove the memory from the search index."""
    db = tmp_path / "brain.db"
    b = _build_full_db(db)
    mid = b.remember("deindex uniqueterm", category="test")
    assert b.search("deindex"), "memory should be searchable while indexed=1"

    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE memories SET indexed = 0 WHERE id = ?", (mid,))
    conn.commit()
    conn.close()

    assert not b_search(db, "deindex"), "de-indexed (indexed=0) memory should not be searchable"


def test_content_edit_reindexes(tmp_path):
    """Editing a memory's content must re-index it (new term appears, old term gone)."""
    db = tmp_path / "brain.db"
    _build_full_db(db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO memories (agent_id, category, scope, content, memory_type, indexed) "
        "VALUES ('fts-test','test','global','original alpha uniqueterm','episodic', 1)"
    )
    conn.commit()
    mid = conn.execute("SELECT id FROM memories WHERE content LIKE 'original%'").fetchone()[0]
    conn.close()

    assert b_search(db, "alpha"), "original term should be searchable before edit"

    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE memories SET content = 'edited beta uniqueterm' WHERE id = ?", (mid,))
    conn.commit()
    conn.close()

    assert b_search(db, "beta"), "edited-in term should be searchable"
    assert not b_search(db, "alpha"), "edited-out term should no longer be searchable"


def b_search(db_path, term):
    """Search via a fresh Brain handle against the given db (avoids stale-connection reads)."""
    b = Brain(db_path=str(db_path), agent_id="fts-test")
    return b.search(term)
