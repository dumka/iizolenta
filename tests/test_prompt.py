"""The routine prompt is a contract: a number that drifts from the code breaks every hourly run."""

from pathlib import Path

from izolenta.merge import WORLD_RETENTION_DAYS
from izolenta.schema import WORLD_SUMMARY_LEN

PROMPT = (Path(__file__).resolve().parent.parent / "routine" / "PROMPT.md").read_text(encoding="utf-8")


def test_prompt_documents_the_world_summary_bounds():
    low, high = WORLD_SUMMARY_LEN
    assert f"{low}-{high}" in PROMPT, f"PROMPT.md must document the summary bounds {low}-{high}"


def test_prompt_documents_the_world_list_and_id_shape():
    assert "`world`" in PROMPT
    assert "world:" in PROMPT


def test_prompt_names_every_data_file_the_merge_writes():
    for name in ("news.json", "posts.json", "hn.json", "habr.json", "world.json", "status.json"):
        assert name in PROMPT, f"PROMPT.md must name {name} in the publish step"


def test_prompt_documents_the_dedup_command_for_world_news():
    assert "recent --news site/data/world.json" in PROMPT


def test_prompt_states_that_low_significance_is_a_skip_reason_for_world_news():
    """Epic 6, R5: the rule is the opposite of the AI/IT one, so it must be spelled out."""
    assert "малозначимое событие" in PROMPT
    assert "значимость и есть фильтр" in PROMPT


def test_prompt_documents_the_world_retention():
    assert f"{WORLD_RETENTION_DAYS} суток" in PROMPT
