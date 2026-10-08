import json
from datetime import UTC, datetime, timedelta

import pytest

from izolenta.merge import merge
from izolenta.state import StateError

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
PARAGRAPH = "Компания представила новую модель, которая работает быстрее и стоит дешевле предыдущей."


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def pending_item(item_id, published=NOW - timedelta(hours=1), image=None):
    return {
        "id": item_id,
        "url": f"https://news.example/{item_id}",
        "source": "Example",
        "title": f"English title {item_id}",
        "snippet": "snippet",
        "text": "text",
        "text_source": "article",
        "published_at": iso(published),
        "image": image,
        "default_category": "ai",
    }


def ok_summary(item_id, **overrides):
    summary = {
        "id": item_id,
        "status": "ok",
        "category": "ai",
        "importance": 2,
        "title": f"Русский заголовок {item_id}",
        "lead": "Короткий лид новости на русском языке для ленты.",
        "body": [PARAGRAPH, PARAGRAPH, PARAGRAPH],
    }
    summary.update(overrides)
    return summary


def news_record(item_id, published):
    return {
        "id": item_id,
        "url": f"https://news.example/{item_id}",
        "source": "Example",
        "published_at": iso(published),
        "category": "dev",
        "importance": 1,
        "title": f"Старая новость {item_id}",
        "lead": "Лид старой новости.",
        "body": [PARAGRAPH, PARAGRAPH, PARAGRAPH],
        "image": None,
    }


class Env:
    def __init__(self, tmp_path):
        self.state = tmp_path / "state"
        self.state.mkdir()
        self.news = tmp_path / "site" / "data" / "news.json"

    def write(self, name, data, raw=False, encoding="utf-8"):
        path = self.state / name
        path.write_text(data if raw else json.dumps(data, ensure_ascii=False), encoding=encoding)

    def setup(self, items, summaries, seen=None, news=None):
        self.write("pending.json", {"generated_at": iso(NOW), "items": items, "errors": []})
        if summaries is not None:
            self.write("summaries.json", {"items": summaries})
        default_seen = {
            i["id"]: {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 0}
            for i in items
        }
        self.write("seen.json", seen if seen is not None else default_seen)
        if news is not None:
            self.news.parent.mkdir(parents=True, exist_ok=True)
            self.news.write_text(json.dumps({"generated_at": "x", "items": news}), encoding="utf-8")

    def run(self, **kwargs):
        return merge(self.state, self.news, NOW, **kwargs)

    def news_items(self):
        return json.loads(self.news.read_text(encoding="utf-8"))["items"]

    def seen(self):
        return json.loads((self.state / "seen.json").read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_valid_summary_added_to_news_with_pending_metadata(env):
    item = pending_item("a1", image="https://cdn.example/a1.jpg")
    forged = ok_summary("a1", url="https://evil.example", source="Evil", image="javascript:x")
    env.setup([item], [forged])
    result = env.run()
    [record] = env.news_items()
    assert record == {
        "id": "a1",
        "url": "https://news.example/a1",
        "source": "Example",
        "published_at": item["published_at"],
        "category": "ai",
        "importance": 2,
        "title": "Русский заголовок a1",
        "lead": "Короткий лид новости на русском языке для ленты.",
        "body": [PARAGRAPH, PARAGRAPH, PARAGRAPH],
        "image": "https://cdn.example/a1.jpg",
    }
    assert env.seen()["a1"]["status"] == "done"
    assert env.seen()["a1"]["attempts"] == 1
    assert result.merged == 1


def test_skip_marks_seen_skipped_and_not_in_news(env):
    env.setup([pending_item("a1")], [{"id": "a1", "status": "skip", "reason": "не про AI"}])
    result = env.run()
    assert env.news_items() == []
    assert env.seen()["a1"]["status"] == "skipped"
    assert result.skipped == 1


def test_invalid_summary_not_in_news_and_attempt_counted(env):
    env.setup([pending_item("a1")], [ok_summary("a1", title="English only title here")])
    result = env.run()
    assert env.news_items() == []
    assert env.seen()["a1"] == {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 1}
    [(bad_id, reasons)] = result.invalid
    assert bad_id == "a1" and any("title" in r for r in reasons)


def test_third_failed_attempt_marks_failed(env):
    seen = {"a1": {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 2}}
    env.setup([pending_item("a1")], [ok_summary("a1", category="nope")], seen=seen)
    result = env.run()
    assert env.seen()["a1"]["status"] == "failed"
    assert env.seen()["a1"]["attempts"] == 3
    assert result.failed == 1


def test_missing_summary_counts_attempt(env):
    env.setup([pending_item("a1"), pending_item("a2")], [ok_summary("a1")])
    result = env.run()
    assert env.seen()["a2"] == {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 1}
    assert result.missing == 1


def test_missing_summaries_file_counts_attempt_for_all(env):
    env.setup([pending_item("a1"), pending_item("a2")], summaries=None)
    result = env.run()
    assert [env.seen()[i]["attempts"] for i in ("a1", "a2")] == [1, 1]
    assert result.missing == 2
    assert result.summaries_error is not None


def test_markdown_wrapped_summaries_counts_as_failure(env):
    env.setup([pending_item("a1")], summaries=None)
    env.write("summaries.json", "```json\n{\"items\": []}\n```", raw=True)
    result = env.run()
    assert env.seen()["a1"]["attempts"] == 1
    assert result.summaries_error is not None


def test_summaries_with_bom_and_bare_list_accepted(env):
    env.setup([pending_item("a1")], summaries=None)
    env.write("summaries.json", json.dumps([ok_summary("a1")], ensure_ascii=False), raw=True, encoding="utf-8-sig")
    env.run()
    assert [r["id"] for r in env.news_items()] == ["a1"]


def test_unknown_and_duplicate_ids_reported_and_ignored(env):
    first = ok_summary("a1", title="Первый вариант заголовка")
    second = ok_summary("a1", title="Второй вариант заголовка")
    env.setup([pending_item("a1")], [first, second, ok_summary("zzz")])
    result = env.run()
    assert [r["title"] for r in env.news_items()] == ["Первый вариант заголовка"]
    assert result.unknown_ids == ["zzz"]
    assert result.duplicate_ids == ["a1"]


def test_existing_news_preserved_and_same_id_replaced(env):
    old = [news_record("old1", NOW - timedelta(days=1)), news_record("a1", NOW - timedelta(hours=2))]
    env.setup([pending_item("a1")], [ok_summary("a1")], news=old)
    env.run()
    by_id = {r["id"]: r for r in env.news_items()}
    assert set(by_id) == {"old1", "a1"}
    assert by_id["a1"]["title"] == "Русский заголовок a1"


def test_news_older_than_retention_pruned(env):
    old = [
        news_record("expired", NOW - timedelta(days=7, minutes=1)),
        news_record("kept", NOW - timedelta(days=6, hours=23)),
    ]
    env.setup([], [], news=old)
    env.run()
    assert [r["id"] for r in env.news_items()] == ["kept"]


def test_news_sorted_newest_first(env):
    items = [
        pending_item("mid", NOW - timedelta(hours=2)),
        pending_item("new", NOW - timedelta(hours=1)),
    ]
    old = [news_record("old", NOW - timedelta(days=1))]
    env.setup(items, [ok_summary("mid"), ok_summary("new")], news=old)
    env.run()
    assert [r["id"] for r in env.news_items()] == ["new", "mid", "old"]


def test_no_pending_file_is_noop(env):
    result = env.run()
    assert result.nothing_to_merge
    assert not env.news.exists()


def test_corrupted_news_json_aborts_without_overwrite(env):
    env.setup([pending_item("a1")], [ok_summary("a1")])
    env.news.parent.mkdir(parents=True)
    env.news.write_text("{oops", encoding="utf-8")
    with pytest.raises(StateError):
        env.run()
    assert env.news.read_text(encoding="utf-8") == "{oops"
    assert env.seen()["a1"]["attempts"] == 0  # state untouched too


def test_corrupted_pending_json_aborts(env):
    env.write("pending.json", "{oops", raw=True)
    with pytest.raises(StateError):
        env.run()


def test_work_files_removed_after_merge(env):
    env.setup([pending_item("a1")], [ok_summary("a1")])
    env.run()
    assert not (env.state / "pending.json").exists()
    assert not (env.state / "summaries.json").exists()


def test_pending_id_without_seen_entry_does_not_crash(env):
    env.setup([pending_item("a1")], [ok_summary("a1")], seen={})
    env.run()
    assert env.seen()["a1"]["status"] == "done"
    assert env.seen()["a1"]["attempts"] == 1


def test_summary_line(env):
    items = [pending_item(i) for i in ("a1", "a2", "a3", "a4")]
    summaries = [
        ok_summary("a1"),
        {"id": "a2", "status": "skip", "reason": "не по теме"},
        ok_summary("a3", importance=7),
    ]
    env.setup(items, summaries)
    result = env.run()
    assert result.summary() == "merged=1 skipped=1 invalid=1 missing=1 failed=0 | news total=1"
