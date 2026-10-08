"""Persistent state: seen articles and atomic JSON writes."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

Seen = dict[str, dict[str, Any]]


class StateError(Exception):
    pass


def load_seen(path: Path) -> Seen:
    """Load seen.json. A missing file is an empty state; a corrupted one is fatal,
    because silently starting over would re-summarize everything already processed."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise StateError(f"{path}: expected a JSON object, got {type(data).__name__}")
    return data


def save_json_atomic(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def prune_seen(seen: Seen, now: datetime, days: int) -> Seen:
    cutoff = now - timedelta(days=days)
    return {
        item_id: entry
        for item_id, entry in seen.items()
        if datetime.fromisoformat(entry["first_seen"]) >= cutoff
    }
