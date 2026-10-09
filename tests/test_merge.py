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
        self.posts = tmp_path / "site" / "data" / "posts.json"
        self.hn = tmp_path / "site" / "data" / "hn.json"

    def write(self, name, data, raw=False, encoding="utf-8"):
        path = self.state / name
        path.write_text(data if raw else json.dumps(data, ensure_ascii=False), encoding=encoding)

    def setup(self, items, summaries, seen=None, news=None, posts=None, post_summaries=None, posts_store=None,
              discussions=None, discussion_summaries=None, hn_store=None):
        pending = {"generated_at": iso(NOW), "items": items, "errors": []}
        if posts is not None:
            pending["posts"] = posts
        if discussions is not None:
            pending["discussions"] = discussions
        self.write("pending.json", pending)
        if summaries is not None:
            data = {"items": summaries}
            if post_summaries is not None:
                data["posts"] = post_summaries
            if discussion_summaries is not None:
                data["discussions"] = discussion_summaries
            self.write("summaries.json", data)
        default_seen = {
            i["id"]: {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 0}
            for i in items + (posts or []) + (discussions or [])
        }
        self.write("seen.json", seen if seen is not None else default_seen)
        if news is not None:
            self.news.parent.mkdir(parents=True, exist_ok=True)
            self.news.write_text(json.dumps({"generated_at": "x", "items": news}), encoding="utf-8")
        if posts_store is not None:
            self.posts.parent.mkdir(parents=True, exist_ok=True)
            self.posts.write_text(json.dumps({"generated_at": "x", "items": posts_store}), encoding="utf-8")
        if hn_store is not None:
            self.hn.parent.mkdir(parents=True, exist_ok=True)
            self.hn.write_text(json.dumps({"generated_at": "x", "items": hn_store}), encoding="utf-8")

    def run(self, **kwargs):
        return merge(self.state, self.news, NOW, **kwargs)

    def news_items(self):
        return json.loads(self.news.read_text(encoding="utf-8"))["items"]

    def post_items(self):
        return json.loads(self.posts.read_text(encoding="utf-8"))["items"]

    def hn_items(self):
        return json.loads(self.hn.read_text(encoding="utf-8"))["items"]

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


POST_RU = "Модели неплохо знают географию: достаточно спросить координаты, и они ответят."


def pending_post(status_id, published=NOW - timedelta(hours=1)):
    return {
        "id": f"x:{status_id}",
        "url": f"https://x.com/karpathy/status/{status_id}",
        "author_handle": "karpathy",
        "author_name": "Andrej Karpathy",
        "published_at": iso(published),
        "text": "Models know geography.",
        "quote": None,
        "lang": "en",
    }


def test_post_merged_into_posts_json_with_pending_metadata(env):
    forged = {"id": "x:1", "status": "ok", "text": POST_RU, "url": "https://evil.example", "author_handle": "evil"}
    env.setup([], [], posts=[pending_post("1")], post_summaries=[forged])
    result = env.run()
    assert env.post_items() == [{
        "id": "x:1",
        "url": "https://x.com/karpathy/status/1",
        "author_handle": "karpathy",
        "author_name": "Andrej Karpathy",
        "published_at": iso(NOW - timedelta(hours=1)),
        "text": POST_RU,
    }]
    assert env.seen()["x:1"]["status"] == "done"
    assert result.posts.merged == 1 and result.posts.total == 1
    assert "posts: merged=1 skipped=0 invalid=0 missing=0 failed=0 | total=1" in result.summary()


def test_post_skip_and_invalid_attempts(env):
    seen = {
        "x:1": {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 0},
        "x:2": {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 2},
    }
    env.setup([], [], seen=seen, posts=[pending_post("1"), pending_post("2")], post_summaries=[
        {"id": "x:1", "status": "skip", "reason": "личное"},
        {"id": "x:2", "status": "ok", "text": "English only text that was not translated"},
    ])
    result = env.run()
    assert env.post_items() == []
    assert env.seen()["x:1"]["status"] == "skipped"
    assert env.seen()["x:2"] == {"first_seen": NOW.isoformat(), "status": "failed", "attempts": 3}
    assert result.posts.skipped == 1 and result.posts.failed == 1
    assert result.posts.invalid[0][0] == "x:2"


def test_posts_older_than_3_days_pruned(env):
    old = [
        {"id": "x:8", "url": "https://x.com/a/status/8", "author_handle": "a", "author_name": "A",
         "published_at": iso(NOW - timedelta(days=3, minutes=1)), "text": POST_RU},
        {"id": "x:9", "url": "https://x.com/a/status/9", "author_handle": "a", "author_name": "A",
         "published_at": iso(NOW - timedelta(days=2, hours=23)), "text": POST_RU},
    ]
    env.setup([], [], posts=[], post_summaries=[], posts_store=old)
    env.run()
    assert [p["id"] for p in env.post_items()] == ["x:9"]


def test_bare_list_summaries_still_merge_articles_only(env):
    env.setup([pending_item("a1")], None, posts=[pending_post("1")])
    env.write("summaries.json", json.dumps([ok_summary("a1")], ensure_ascii=False), raw=True)
    result = env.run()
    assert [r["id"] for r in env.news_items()] == ["a1"]
    assert result.posts.missing == 1
    assert env.seen()["x:1"]["attempts"] == 1


def test_corrupted_posts_json_aborts_without_overwrite(env):
    env.setup([pending_item("a1")], [ok_summary("a1")], posts=[pending_post("1")], post_summaries=[])
    env.posts.parent.mkdir(parents=True, exist_ok=True)
    env.posts.write_text("{oops", encoding="utf-8")
    with pytest.raises(StateError):
        env.run()
    assert env.posts.read_text(encoding="utf-8") == "{oops"
    assert not env.news.exists()


def test_missing_posts_summaries_count_attempts(env):
    env.setup([], [], posts=[pending_post("1"), pending_post("2")], post_summaries=[{"id": "x:1", "status": "ok", "text": POST_RU}])
    result = env.run()
    assert result.posts.merged == 1 and result.posts.missing == 1
    assert env.seen()["x:2"]["attempts"] == 1


def test_no_posts_key_in_pending_keeps_old_summary(env):
    env.setup([pending_item("a1")], [ok_summary("a1")])
    result = env.run()
    assert result.posts is None
    assert "posts:" not in result.summary()


DISCUSSION_RU = (
    "Участники спорят, можно ли доверять моделям в математических доказательствах. "
    "Большинство сходится на том, что без формальной проверки результатам верить рано."
)


def pending_discussion(story_id, published=NOW - timedelta(hours=2)):
    return {
        "id": f"hn:{story_id}",
        "hn_url": f"https://news.ycombinator.com/item?id={story_id}",
        "url": "https://example.com/article",
        "title": "Mathematicians call for boycott",
        "points": 420,
        "comments": 310,
        "published_at": iso(published),
        "story_text": "",
        "top_comments": ["c1", "c2", "c3"],
    }


def test_discussion_merged_into_hn_json_with_pending_metadata(env):
    forged = {"id": "hn:7", "status": "ok", "title": "Математики призывают к бойкоту", "summary": DISCUSSION_RU,
              "hn_url": "https://evil.example", "points": 99999}
    env.setup([], [], discussions=[pending_discussion(7)], discussion_summaries=[forged])
    result = env.run()
    assert env.hn_items() == [{
        "id": "hn:7",
        "hn_url": "https://news.ycombinator.com/item?id=7",
        "url": "https://example.com/article",
        "points": 420,
        "comments": 310,
        "published_at": iso(NOW - timedelta(hours=2)),
        "title": "Математики призывают к бойкоту",
        "summary": DISCUSSION_RU,
    }]
    assert env.seen()["hn:7"]["status"] == "done"
    assert "hn: merged=1 skipped=0 invalid=0 missing=0 failed=0 | total=1" in result.summary()


def test_discussions_older_than_3_days_pruned(env):
    old = [
        {"id": "hn:1", "hn_url": "https://news.ycombinator.com/item?id=1", "url": None, "points": 300, "comments": 100,
         "published_at": iso(NOW - timedelta(days=3, minutes=1)), "title": "Старое", "summary": DISCUSSION_RU},
        {"id": "hn:2", "hn_url": "https://news.ycombinator.com/item?id=2", "url": None, "points": 300, "comments": 100,
         "published_at": iso(NOW - timedelta(days=2)), "title": "Свежее", "summary": DISCUSSION_RU},
    ]
    env.setup([], [], discussions=[], discussion_summaries=[], hn_store=old)
    env.run()
    assert [d["id"] for d in env.hn_items()] == ["hn:2"]


def test_corrupted_hn_json_aborts_without_overwrite(env):
    env.setup([], [], discussions=[pending_discussion(1)], discussion_summaries=[])
    env.hn.parent.mkdir(parents=True, exist_ok=True)
    env.hn.write_text("{oops", encoding="utf-8")
    with pytest.raises(StateError):
        env.run()
    assert env.hn.read_text(encoding="utf-8") == "{oops"


def test_missing_discussion_summary_counts_attempt(env):
    env.setup([], [], discussions=[pending_discussion(3)], discussion_summaries=[])
    result = env.run()
    assert result.discussions.missing == 1
    assert env.seen()["hn:3"]["attempts"] == 1


def test_summaries_split_into_parts_are_combined_and_removed(env):
    env.setup([pending_item("a1"), pending_item("a2")], None, posts=[pending_post("1")])
    env.write("summaries.1.json", {"items": [ok_summary("a1")]})
    env.write("summaries.2.json", {"items": [ok_summary("a2")], "posts": [{"id": "x:1", "status": "ok", "text": POST_RU}]})
    result = env.run()
    assert sorted(r["id"] for r in env.news_items()) == ["a1", "a2"]
    assert result.posts.merged == 1
    assert not list(env.state.glob("summaries*.json"))


def test_broken_summaries_part_reported_others_used(env):
    env.setup([pending_item("a1"), pending_item("a2")], [ok_summary("a1")])
    env.write("summaries.2.json", "{not json", raw=True)
    result = env.run()
    assert [r["id"] for r in env.news_items()] == ["a1"]
    assert result.missing == 1
    assert "summaries.2.json" in (result.summaries_error or "")


# --- status.json: what happened to every collected material (hidden #/status page) ---

SOURCES = [{"name": "Example", "kind": "feed", "ok": True, "error": None, "entries": 9, "candidates": 4, "selected": 4}]


def add_stats(env, sources=SOURCES):
    pending = json.loads((env.state / "pending.json").read_text(encoding="utf-8"))
    pending["stats"] = {"sources": sources}
    env.write("pending.json", pending)


def status(env):
    return json.loads((env.news.parent / "status.json").read_text(encoding="utf-8"))


def materials(env):
    return {m["id"]: m for m in status(env)["materials"]}


def test_status_records_run_and_outcome_of_every_article(env):
    env.setup(
        [pending_item("a1"), pending_item("a2"), pending_item("a3"), pending_item("a4")],
        [ok_summary("a1"), {"id": "a2", "status": "skip", "reason": "реклама"}, ok_summary("a3", importance=7)],
    )
    add_stats(env)
    env.run()
    [run] = status(env)["runs"]
    assert run["collected_at"] == iso(NOW) and run["merged_at"] == iso(NOW)
    assert run["sources"] == SOURCES
    assert run["result"]["items"] == {"merged": 1, "skipped": 1, "invalid": 1, "missing": 1, "failed": 0}
    by_id = materials(env)
    assert by_id["a1"] == {
        "id": "a1", "kind": "article", "source": "Example", "title": "English title a1",
        "url": "https://news.example/a1", "published_at": iso(NOW - timedelta(hours=1)),
        "collected_at": iso(NOW), "processed_at": iso(NOW), "text_source": "article",
        "outcome": "published", "reason": None, "attempts": 1,
    }
    assert (by_id["a2"]["outcome"], by_id["a2"]["reason"]) == ("skipped", "реклама")
    assert by_id["a3"]["outcome"] == "invalid" and "importance" in by_id["a3"]["reason"]
    assert by_id["a4"]["outcome"] == "missing"


def test_status_gives_up_after_max_attempts(env):
    seen = {"a1": {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 2}}
    env.setup([pending_item("a1")], [], seen=seen)
    env.run()
    m = materials(env)["a1"]
    assert (m["outcome"], m["attempts"]) == ("failed", 3)
    assert m["reason"]


def test_status_reprocessed_material_updated_not_duplicated(env):
    earlier = iso(NOW - timedelta(hours=1))
    old = {"generated_at": earlier, "runs": [], "materials": [
        {"id": "a1", "kind": "article", "source": "Example", "title": "English title a1",
         "url": "https://news.example/a1", "published_at": earlier, "collected_at": earlier,
         "processed_at": earlier, "text_source": "article", "outcome": "missing", "reason": "нет выжимки", "attempts": 1},
    ]}
    env.news.parent.mkdir(parents=True, exist_ok=True)
    (env.news.parent / "status.json").write_text(json.dumps(old), encoding="utf-8")
    seen = {"a1": {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 1}}
    env.setup([pending_item("a1")], [ok_summary("a1")], seen=seen)
    env.run()
    [m] = status(env)["materials"]
    assert (m["outcome"], m["attempts"], m["collected_at"], m["processed_at"]) == ("published", 2, earlier, iso(NOW))


def test_status_keeps_only_last_48_hours(env):
    old_moment = iso(NOW - timedelta(hours=49))
    recent_moment = iso(NOW - timedelta(hours=47))
    old = {"generated_at": old_moment, "runs": [
        {"collected_at": old_moment, "merged_at": old_moment, "sources": [], "result": {}},
        {"collected_at": recent_moment, "merged_at": recent_moment, "sources": [], "result": {}},
    ], "materials": [
        {"id": "gone", "processed_at": old_moment, "outcome": "published"},
        {"id": "kept", "processed_at": recent_moment, "outcome": "skipped"},
    ]}
    env.news.parent.mkdir(parents=True, exist_ok=True)
    (env.news.parent / "status.json").write_text(json.dumps(old), encoding="utf-8")
    env.setup([], [])
    env.run()
    data = status(env)
    assert [r["merged_at"] for r in data["runs"]] == [iso(NOW), recent_moment]
    assert [m["id"] for m in data["materials"]] == ["kept"]


def test_status_lists_posts_and_discussions(env):
    env.setup([], [], posts=[pending_post("1")], post_summaries=[{"id": "x:1", "status": "ok", "text": POST_RU}],
              discussions=[pending_discussion(7)],
              discussion_summaries=[{"id": "hn:7", "status": "skip", "reason": "не про ИТ"}])
    env.run()
    by_id = materials(env)
    post = by_id["x:1"]
    assert (post["kind"], post["source"], post["outcome"]) == ("post", "@karpathy", "published")
    assert post["title"].startswith("Models know geography") and post["url"] == "https://x.com/karpathy/status/1"
    hn = by_id["hn:7"]
    assert (hn["kind"], hn["source"], hn["outcome"], hn["reason"]) == ("discussion", "HN discussions", "skipped", "не про ИТ")
    assert hn["url"] == "https://news.ycombinator.com/item?id=7"
    assert status(env)["runs"][0]["result"]["posts"]["merged"] == 1


def test_corrupted_status_is_started_afresh(env):
    env.news.parent.mkdir(parents=True, exist_ok=True)
    (env.news.parent / "status.json").write_text("{broken", encoding="utf-8")
    env.setup([pending_item("a1")], [ok_summary("a1")])
    env.run()
    assert [m["id"] for m in status(env)["materials"]] == ["a1"]
    assert [r["id"] for r in env.news_items()] == ["a1"]
