import json
from datetime import UTC, datetime, timedelta

import pytest

from izolenta.state import StateError, load_seen, prune_seen, save_json_atomic

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def test_missing_seen_file_is_empty_state(tmp_path):
    assert load_seen(tmp_path / "seen.json") == {}


def test_corrupted_seen_file_raises_state_error(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text('{"abc": {"status": "done"', encoding="utf-8")
    with pytest.raises(StateError):
        load_seen(path)


def test_seen_file_with_wrong_shape_raises_state_error(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text('["not", "a", "dict"]', encoding="utf-8")
    with pytest.raises(StateError):
        load_seen(path)


def test_prune_removes_only_old_entries():
    seen = {
        "old": {"first_seen": (NOW - timedelta(days=15)).isoformat(), "status": "done", "attempts": 1},
        "edge": {"first_seen": (NOW - timedelta(days=13)).isoformat(), "status": "skipped", "attempts": 1},
        "new": {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 0},
    }
    pruned = prune_seen(seen, NOW, days=14)
    assert set(pruned) == {"edge", "new"}


def test_atomic_write_preserves_unicode(tmp_path):
    path = tmp_path / "out.json"
    data = {"title": "«ИИ» обгоняет людей — 🚀 测试"}
    save_json_atomic(path, data)
    text = path.read_text(encoding="utf-8")
    assert "«ИИ» обгоняет людей" in text  # not \u-escaped
    assert json.loads(text) == data
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]  # no temp leftovers


def test_atomic_write_replaces_existing_file(tmp_path):
    path = tmp_path / "out.json"
    save_json_atomic(path, {"v": 1})
    save_json_atomic(path, {"v": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 2}
