from pathlib import Path

from izolenta.__main__ import main

ROOT = Path(__file__).resolve().parent.parent


def test_corrupted_seen_exits_2_and_keeps_file(tmp_path, capsys):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "seen.json").write_text("{broken", encoding="utf-8")
    code = main(["collect", "--config", str(ROOT / "feeds.toml"), "--state-dir", str(state_dir)])
    assert code == 2
    assert "seen.json" in capsys.readouterr().err
    assert (state_dir / "seen.json").read_text(encoding="utf-8") == "{broken"


def test_invalid_config_exits_2(tmp_path, capsys):
    config = tmp_path / "feeds.toml"
    config.write_text("[settings\n", encoding="utf-8")
    code = main(["collect", "--config", str(config), "--state-dir", str(tmp_path)])
    assert code == 2
    assert "config" in capsys.readouterr().err


def test_merge_corrupted_news_exits_2(tmp_path, capsys):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "pending.json").write_text('{"items": []}', encoding="utf-8")
    news = tmp_path / "news.json"
    news.write_text("{oops", encoding="utf-8")
    code = main(["merge", "--state-dir", str(state_dir), "--news", str(news)])
    assert code == 2
    assert "news.json" in capsys.readouterr().err
    assert news.read_text(encoding="utf-8") == "{oops"


def test_merge_without_pending_exits_0(tmp_path, capsys):
    code = main(["merge", "--state-dir", str(tmp_path), "--news", str(tmp_path / "news.json")])
    assert code == 0
    assert "nothing to merge" in capsys.readouterr().out


def _check_env(tmp_path, summaries):
    from tests.test_merge import Env, pending_item

    env = Env(tmp_path)
    env.setup([pending_item("a1")], summaries)
    return env


def test_check_exit_0_when_valid(tmp_path, capsys):
    from tests.test_merge import ok_summary

    env = _check_env(tmp_path, [ok_summary("a1")])
    assert main(["check", "--state-dir", str(env.state)]) == 0
    assert "ok" in capsys.readouterr().out


def test_check_exit_1_with_problems(tmp_path, capsys):
    env = _check_env(tmp_path, [])
    assert main(["check", "--state-dir", str(env.state)]) == 1
    assert "missing a1" in capsys.readouterr().out


def test_merge_writes_posts_to_given_path_and_reports_invalid(tmp_path, capsys):
    from tests.test_merge import POST_RU, Env, pending_post

    env = Env(tmp_path)
    env.setup([], [], posts=[pending_post("1"), pending_post("2")], post_summaries=[
        {"id": "x:1", "status": "ok", "text": POST_RU},
        {"id": "x:2", "status": "ok", "text": "English only, not translated"},
    ])
    posts_path = tmp_path / "out" / "posts.json"
    code = main(["merge", "--state-dir", str(env.state), "--news", str(env.news), "--posts", str(posts_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert posts_path.exists() and not env.posts.exists()
    assert "posts: merged=1" in out
    assert "invalid post x:2" in out


def test_merge_writes_hn_to_given_path(tmp_path, capsys):
    from tests.test_merge import DISCUSSION_RU, Env, pending_discussion

    env = Env(tmp_path)
    env.setup([], [], discussions=[pending_discussion(1)], discussion_summaries=[
        {"id": "hn:1", "status": "ok", "title": "Математики спорят о доказательствах", "summary": DISCUSSION_RU},
    ])
    hn_path = tmp_path / "out" / "hn.json"
    code = main(["merge", "--state-dir", str(env.state), "--news", str(env.news), "--hn", str(hn_path)])
    assert code == 0
    assert hn_path.exists() and not env.hn.exists()
    assert "hn: merged=1" in capsys.readouterr().out
