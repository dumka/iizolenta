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
