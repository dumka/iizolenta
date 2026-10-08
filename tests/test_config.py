from pathlib import Path

import pytest

from izolenta.config import ConfigError, load_config

ROOT = Path(__file__).resolve().parent.parent

SETTINGS = """
[settings]
max_items_per_run = 5
max_age_hours = 48
article_text_limit = 8000
http_timeout = 15
max_response_bytes = 1000000
seen_retention_days = 14
fetch_workers = 4
max_posts_per_run = 3
post_max_age_hours = 48
user_agent = "test"
"""


def write_config(tmp_path: Path, feeds: str) -> Path:
    path = tmp_path / "feeds.toml"
    path.write_text(SETTINGS + feeds, encoding="utf-8")
    return path


def test_project_feeds_toml_is_valid():
    config = load_config(ROOT / "feeds.toml")
    assert len(config.feeds) >= 10
    assert config.settings.max_items_per_run == 15


def test_valid_config_parsed(tmp_path):
    path = write_config(
        tmp_path,
        """
[[feeds]]
name = "A"
url = "https://a.example/feed"
default_category = "ai"
""",
    )
    config = load_config(path)
    assert config.feeds[0].name == "A"
    assert config.feeds[0].url == "https://a.example/feed"
    assert config.feeds[0].default_category == "ai"
    assert config.settings.fetch_workers == 4


def test_invalid_category_rejected(tmp_path):
    path = write_config(
        tmp_path,
        """
[[feeds]]
name = "A"
url = "https://a.example/feed"
default_category = "hardware"
""",
    )
    with pytest.raises(ConfigError, match="category"):
        load_config(path)


def test_empty_feed_list_rejected(tmp_path):
    path = write_config(tmp_path, "")
    with pytest.raises(ConfigError, match="feeds"):
        load_config(path)


def test_duplicate_feed_names_rejected(tmp_path):
    path = write_config(
        tmp_path,
        """
[[feeds]]
name = "A"
url = "https://a.example/feed"
default_category = "ai"

[[feeds]]
name = "A"
url = "https://b.example/feed"
default_category = "dev"
""",
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(path)


def test_non_http_feed_url_rejected(tmp_path):
    path = write_config(
        tmp_path,
        """
[[feeds]]
name = "A"
url = "file:///etc/passwd"
default_category = "ai"
""",
    )
    with pytest.raises(ConfigError, match="url"):
        load_config(path)


def test_malformed_toml_raises_config_error(tmp_path):
    path = tmp_path / "feeds.toml"
    path.write_text("[settings\nbroken", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


FEED = """
[[feeds]]
name = "A"
url = "https://a.example/feed"
default_category = "ai"
"""


def test_x_accounts_optional(tmp_path):
    config = load_config(write_config(tmp_path, FEED))
    assert config.x_accounts == ()


def test_x_accounts_parsed(tmp_path):
    config = load_config(write_config(tmp_path, FEED + '\n[[x_accounts]]\nhandle = "karpathy"\n\n[[x_accounts]]\nhandle = "bcherny"\n'))
    assert [a.handle for a in config.x_accounts] == ["karpathy", "bcherny"]
    assert config.settings.max_posts_per_run == 3


@pytest.mark.parametrize(
    "handles",
    [
        ["bad handle"],
        ["../evil"],
        ["way_too_long_handle_123"],
        ["karpathy", "Karpathy"],
    ],
)
def test_invalid_or_duplicate_handle_rejected(tmp_path, handles):
    accounts = "".join(f'\n[[x_accounts]]\nhandle = "{h}"\n' for h in handles)
    with pytest.raises(ConfigError, match="handle"):
        load_config(write_config(tmp_path, FEED + accounts))
