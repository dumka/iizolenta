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
    assert 1 <= config.settings.max_items_per_run <= 100


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


def test_feed_kind_defaults_to_news(tmp_path):
    [feed] = load_config(write_config(tmp_path, FEED)).feeds
    assert feed.kind == "news"


def test_feed_kind_habr_parsed(tmp_path):
    [feed] = load_config(write_config(tmp_path, FEED + 'kind = "habr"\n')).feeds
    assert feed.kind == "habr"


def test_unknown_feed_kind_rejected(tmp_path):
    with pytest.raises(ConfigError, match="kind"):
        load_config(write_config(tmp_path, FEED + 'kind = "blog"\n'))


def test_project_habr_hubs_go_to_habr_block_and_habr_news_stays_news():
    kinds = {feed.name: feed.kind for feed in load_config(ROOT / "feeds.toml").feeds}
    assert kinds["Хабр: ИИ"] == kinds["Хабр: ML"] == "habr"
    assert kinds["Хабр Новости"] == "news"


WORLD_FEED = """
[[feeds]]
name = "Лента.ру: Мир"
url = "https://lenta.ru/rss/news/world"
kind = "world"
"""


def test_feed_kind_world_parsed_without_category(tmp_path):
    [feed] = load_config(write_config(tmp_path, WORLD_FEED)).feeds
    assert (feed.kind, feed.default_category) == ("world", None)


def test_news_feed_without_category_rejected(tmp_path):
    feed = """
[[feeds]]
name = "A"
url = "https://a.example/feed"
"""
    with pytest.raises(ConfigError, match="requires default_category"):
        load_config(write_config(tmp_path, feed))


def test_invalid_category_on_world_feed_rejected(tmp_path):
    with pytest.raises(ConfigError, match="category"):
        load_config(write_config(tmp_path, WORLD_FEED + 'default_category = "hardware"\n'))


def test_world_settings_have_defaults(tmp_path):
    settings = load_config(write_config(tmp_path, FEED)).settings
    assert (settings.max_world_per_run, settings.world_text_limit) == (25, 1200)


def test_project_world_feeds_configured():
    feeds = [feed for feed in load_config(ROOT / "feeds.toml").feeds if feed.kind == "world"]
    assert 1 <= len(feeds) <= 12, 'эпик 6 запрещает больше 12 лент kind = "world"'
    assert all(feed.default_category is None for feed in feeds)
    hosts = " ".join(feed.url for feed in feeds)
    assert "62info" in hosts and "lenta.ru" in hosts
