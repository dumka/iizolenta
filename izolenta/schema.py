"""Validation of the summaries Claude writes into state/summaries.json."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from izolenta.config import CATEGORIES

CYRILLIC = re.compile("[А-Яа-яЁё]")
TITLE_LEN = (10, 200)
LEAD_LEN = (20, 400)
PARAGRAPH_LEN = (40, 1500)
BODY_PARAGRAPHS = (3, 5)
REASON_MAX = 300


class ValidationError(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Summary:
    id: str
    category: str
    importance: int
    title: str
    lead: str
    body: tuple[str, ...]


@dataclass(frozen=True)
class Skip:
    id: str
    reason: str


def normalize(value: str) -> str:
    return " ".join(value.split())


def _check_text(name: str, value: Any, bounds: tuple[int, int], errors: list[str]) -> str:
    if not isinstance(value, str):
        errors.append(f"{name}: must be a string")
        return ""
    text = normalize(value)
    low, high = bounds
    if not low <= len(text) <= high:
        errors.append(f"{name}: length {len(text)} not in {low}..{high}")
    elif not CYRILLIC.search(text):
        errors.append(f"{name}: no Russian text (not translated?)")
    elif "<" in text or ">" in text:
        errors.append(f"{name}: HTML is not allowed")
    return text


def validate_summary(raw: Any) -> Summary | Skip:
    if not isinstance(raw, dict):
        raise ValidationError(["entry: must be a JSON object"])

    errors: list[str] = []
    item_id = raw.get("id")
    if not isinstance(item_id, str) or not item_id:
        errors.append("id: must be a non-empty string")

    status = raw.get("status")
    if status == "skip":
        reason = raw.get("reason")
        reason = normalize(reason) if isinstance(reason, str) else ""
        if not reason or len(reason) > REASON_MAX:
            errors.append(f"reason: must be a non-empty string up to {REASON_MAX} chars")
        if errors:
            raise ValidationError(errors)
        return Skip(id=item_id, reason=reason)

    if status != "ok":
        raise ValidationError(errors + [f"status: must be 'ok' or 'skip', got {status!r}"])

    category = raw.get("category")
    if category not in CATEGORIES:
        errors.append(f"category: must be one of {CATEGORIES}, got {category!r}")

    importance = raw.get("importance")
    if type(importance) is not int or not 1 <= importance <= 3:
        errors.append(f"importance: must be an integer 1..3, got {importance!r}")

    title = _check_text("title", raw.get("title"), TITLE_LEN, errors)
    lead = _check_text("lead", raw.get("lead"), LEAD_LEN, errors)

    body_raw = raw.get("body")
    body: list[str] = []
    low, high = BODY_PARAGRAPHS
    if not isinstance(body_raw, list) or not low <= len(body_raw) <= high:
        errors.append(f"body: must be a list of {low}..{high} paragraphs")
    else:
        body = [
            _check_text(f"body[{index}]", paragraph, PARAGRAPH_LEN, errors)
            for index, paragraph in enumerate(body_raw)
        ]

    if errors:
        raise ValidationError(errors)
    return Summary(
        id=item_id,
        category=category,
        importance=importance,
        title=title,
        lead=lead,
        body=tuple(body),
    )
