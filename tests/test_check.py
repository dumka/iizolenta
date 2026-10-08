from izolenta.merge import check

from tests.test_merge import POST_RU, Env, ok_summary, pending_item, pending_post


def snapshot(env):
    return {p.name: p.read_bytes() for p in sorted(env.state.iterdir())}


def test_check_passes_for_complete_valid_summaries(tmp_path):
    env = Env(tmp_path)
    env.setup(
        [pending_item("a1"), pending_item("a2")],
        [ok_summary("a1"), {"id": "a2", "status": "skip", "reason": "не по теме"}],
    )
    result = check(env.state)
    assert result.ok
    assert result.problems == []


def test_check_reports_invalid_and_missing_without_side_effects(tmp_path):
    env = Env(tmp_path)
    env.setup(
        [pending_item("a1"), pending_item("a2"), pending_item("a3")],
        [ok_summary("a1", title="English only title"), ok_summary("zzz"), ok_summary("a3"), ok_summary("a3")],
    )
    before = snapshot(env)
    result = check(env.state)
    assert not result.ok
    text = "\n".join(result.problems)
    assert "invalid a1" in text and "title" in text
    assert "missing a2" in text
    assert "unknown id zzz" in text
    assert "duplicate id a3" in text
    assert snapshot(env) == before  # nothing written, nothing deleted
    assert not env.news.exists()


def test_check_fails_on_unreadable_summaries(tmp_path):
    env = Env(tmp_path)
    env.setup([pending_item("a1")], summaries=None)
    env.write("summaries.json", "```json\n[]\n```", raw=True)
    result = check(env.state)
    assert not result.ok
    assert any("summaries.json" in p for p in result.problems)


def test_check_without_pending_is_ok(tmp_path):
    env = Env(tmp_path)
    result = check(env.state)
    assert result.ok
    assert result.nothing_to_check


def test_check_reports_post_problems(tmp_path):
    env = Env(tmp_path)
    env.setup(
        [pending_item("a1")],
        [ok_summary("a1")],
        posts=[pending_post("1"), pending_post("2"), pending_post("3")],
        post_summaries=[
            {"id": "x:1", "status": "ok", "text": "Not translated at all, sorry about that"},
            {"id": "x:3", "status": "ok", "text": POST_RU},
            {"id": "x:77", "status": "ok", "text": POST_RU},
        ],
    )
    result = check(env.state)
    text = "\n".join(result.problems)
    assert not result.ok
    assert "invalid post x:1" in text
    assert "missing post x:2" in text
    assert "unknown post id x:77" in text
    assert "a1" not in text  # the article is fine
