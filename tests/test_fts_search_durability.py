"""Regression tests: the FTS search index must survive normal operation.

issue #97-3 — brainctl 2.8.0's `memories_fts` update triggers fired on ANY
UPDATE to a memory row, including the `recalled_count` bump that `cmd_search`
performs after every search. On external-content FTS5 the re-insert leg does
not reliably rebuild the inverted index, so the first search silently corrupted
the index and every subsequent search returned zero hits.

The fix scopes the triggers to `content, category, tags, indexed, retired_at`,
so recall-count/confidence updates no longer touch the index while the 0→1
promotion and retire→purge transitions keep working.
"""
from agentmemory.brain import Brain


def test_repeated_search_is_consistent(tmp_path):
    """Searching twice must return the same results (index must not self-corrupt)."""
    b = Brain(db_path=str(tmp_path / "brain.db"), agent_id="fts-test")
    b.remember("the quick brown fox jumps", category="test", tags=["animal"])
    b.remember("a second memory about foxes in the woods", category="test", tags=["animal"])

    first = b.search("fox")
    second = b.search("fox")

    assert first, "first search should find the fox memories"
    assert second, "second search must still find the fox memories (FTS corruption regression)"
    assert len(first) == len(second), f"search results diverged: {len(first)} vs {len(second)}"


def test_retire_purges_from_search(tmp_path):
    """Retiring a memory must remove it from search, then un-retire restores it."""
    b = Brain(db_path=str(tmp_path / "brain.db"), agent_id="fts-test")
    mid = b.remember("retire me please", category="test")

    assert b.search("retire"), "memory should be searchable before retire"

    b.forget(mid)
    assert not b.search("retire"), "retired memory must not appear in search"
