# Раздел «Новости»: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** добавить в ИИзоЛенту пятый тип материала — сжатые общие новости (мир, Россия, Рязань, наука, культура) на отдельной странице `#/world` с пунктом меню «Новости», с фильтром, который отсекает кликбейт и жёлтую прессу.

**Architecture:** повторяется путь, которым в эпике 5 добавили Хабр. Ленты с `kind = "world"` собираются в отдельный список `world` в `state/pending.json` со своим лимитом и своим лимитом текста; routine пишет к каждой записи заголовок и один абзац; `merge` проверяет их через `validate_world` и складывает в `site/data/world.json`; дашборд рисует страницу `#/world`. Главная страница не меняется.

**Tech Stack:** Python 3.14 (uv, pytest, feedparser, trafilatura), ванильный ES-модульный JavaScript без сборки, `node --test`, GitHub Actions, Claude Code routine.

**Spec:** `docs/plans/epic-6-world-news.md`

## Global Constraints

- Ветка работы — `epic-6-world-news`. В `main` ничего не пушить до задачи 7.
- Сообщения коммитов — на английском, последняя строка `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Из вывода модели берутся только `title` и `summary`. Ссылка, источник и дата — всегда от сборщика (R7).
- `summary` — один абзац 80–400 знаков, обязательна кириллица, символы `<` и `>` запрещены (R2).
- `max_world_per_run = 25`, `world_text_limit = 1200` (R9).
- Лент с `kind = "world"` не больше 12. Добавление ленты сверх этого — только вместе с подъёмом лимита (анти-паттерн эпика).
- Хранение `world.json` — 2 суток. Сокращать нельзя: дедупликация опирается на `recent --hours 48`.
- Малая значимость — законный повод для `skip` только у этого типа. В `validate_summary` запрет `LOW_IMPORTANCE_SKIP` остаётся как есть (R5).
- Блока «Новости» на главной нет. Главная остаётся про AI и IT (R8).
- Форматы `news.json`, `posts.json`, `hn.json`, `habr.json` не меняются.
- Тесты запускаются так: `uv run pytest` и `node --test "tests/js/*.test.mjs"`.

## Review Focus

Пять входных условий, которые спецификация подразумевает, но прямо не описывает. Для каждого в плане есть тест в той задаче, которая владеет кодом.

1. `world.json` отсутствует, отдаёт 404 или содержит битый JSON — страница показывает состояние «Лента порвалась», главная и остальные страницы работают. → задача 5, шаг 8 (проверка в браузере).
2. Один и тот же URL пришёл из двух лент `world` (Лента.ру «Россия» и «Мир» регулярно дублируют друг друга) — заметка берётся один раз. → задача 2, шаг 6.
3. Заголовок и анонс приходят в CDATA (так отдают РБК, Коммерсантъ и N+1) — парсер извлекает текст, а не обёртку. → задача 2, шаг 8.
4. `summary` ровно на границах: 80 и 400 знаков принимаются, 79 и 401 отклоняются. → задача 3, шаг 6.
5. Одна лента `world` упала (404 или таймаут) — сбор продолжается, остальные ленты обрабатываются. → задача 2, шаг 10.

---

### Task 1: Конфигурация — третий вид ленты

**Files:**
- Modify: `izolenta/config.py` (`FEED_KINDS`, `Feed`, `Settings`, `load_config`)
- Modify: `izolenta/feeds.py:30` (`FeedItem.default_category`)
- Modify: `feeds.toml` (`[settings]` и 11 новых лент)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: ничего из предыдущих задач.
- Produces: `FEED_KINDS = ("news", "habr", "world")`; `Feed(name: str, url: str, default_category: str | None = None, kind: str = "news")`; `Settings.max_world_per_run: int = 25`; `Settings.world_text_limit: int = 1200`.

- [ ] **Step 1: Создать ветку**

```bash
git checkout epic-6-world-news
git status --porcelain
```

Ожидание: ветка уже существует (создана вместе со спецификацией), рабочая копия чистая.

- [ ] **Step 2: Написать падающие тесты конфигурации**

Добавить в конец `tests/test_config.py`:

```python
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
    with pytest.raises(ConfigError, match="default_category"):
        load_config(write_config(tmp_path, feed))


def test_invalid_category_on_world_feed_rejected(tmp_path):
    with pytest.raises(ConfigError, match="category"):
        load_config(write_config(tmp_path, WORLD_FEED + 'default_category = "hardware"\n'))


def test_world_settings_have_defaults(tmp_path):
    settings = load_config(write_config(tmp_path, FEED)).settings
    assert (settings.max_world_per_run, settings.world_text_limit) == (25, 1200)


def test_project_world_feeds_configured():
    feeds = [feed for feed in load_config(ROOT / "feeds.toml").feeds if feed.kind == "world"]
    assert 1 <= len(feeds) <= 12, "эпик 6 запрещает больше 12 лент kind = \"world\""
    assert all(feed.default_category is None for feed in feeds)
    hosts = " ".join(feed.url for feed in feeds)
    assert "62info" in hosts and "lenta.ru" in hosts
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_config.py -k world -v`
Ожидание: FAIL. `test_feed_kind_world_parsed_without_category` падает с `ConfigError: feed Лента.ру: Мир: kind must be one of ('news', 'habr')`.

- [ ] **Step 4: Разрешить вид `world` и сделать рубрику необязательной**

В `izolenta/config.py` заменить объявление видов и класс `Feed`:

```python
CATEGORIES = ("ai", "dev", "business")
# news: summaries in the main feed; habr: author articles retold in the «Пишут на Хабре» block;
# world: general news compressed into one paragraph for the «Новости» page
FEED_KINDS = ("news", "habr", "world")
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    default_category: str | None = None
    kind: str = "news"
```

В `Settings` добавить две настройки последними (значения по умолчанию обязательны: без них существующие тесты и `feeds.toml` перестанут читаться):

```python
    max_habr_per_run: int = 10
    max_world_per_run: int = 25
    world_text_limit: int = 1200
```

В `load_config` заменить проверку рубрики:

```python
        if feed.default_category is not None and feed.default_category not in CATEGORIES:
            raise ConfigError(
                f"feed {feed.name}: category must be one of {CATEGORIES}, "
                f"got {feed.default_category!r}"
            )
        if feed.kind == "news" and feed.default_category is None:
            raise ConfigError(f"feed {feed.name}: kind = \"news\" requires default_category")
```

В `izolenta/feeds.py` разрешить отсутствие рубрики у записи ленты:

```python
@dataclass(frozen=True)
class FeedItem:
    id: str
    url: str
    source: str
    title: str
    snippet: str
    published_at: datetime
    image: str | None
    default_category: str | None
    author: str | None = None
```

- [ ] **Step 5: Добавить ленты в `feeds.toml`**

В блок `[settings]` после `max_habr_per_run = 10` добавить:

```toml
max_world_per_run = 25
world_text_limit = 1200
```

В конец файла, перед блоком `# Posts from X`, добавить ленты общих новостей. Все адреса проверены живым запросом 2026-10-13:

```toml
# General news for the «Новости» page (kind = "world"): one paragraph per item, no category.
# Topics and the skip list are in docs/plans/epic-6-world-news.md; at most 12 feeds (round-robin budget).

[[feeds]]
name = "Лента.ру: Россия"
url = "https://lenta.ru/rss/news/russia"
kind = "world"

[[feeds]]
name = "Лента.ру: Мир"
url = "https://lenta.ru/rss/news/world"
kind = "world"

[[feeds]]
name = "Лента.ру: Экономика"
url = "https://lenta.ru/rss/news/economics"
kind = "world"

[[feeds]]
name = "Лента.ру: Наука"
url = "https://lenta.ru/rss/news/science"
kind = "world"

[[feeds]]
name = "РИА Новости"
url = "https://ria.ru/export/rss2/archive/index.xml"
kind = "world"

[[feeds]]
name = "РБК"
url = "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"
kind = "world"

[[feeds]]
name = "Коммерсантъ"
url = "https://www.kommersant.ru/RSS/main.xml"
kind = "world"

[[feeds]]
name = "N+1"
url = "https://nplus1.ru/rss"
kind = "world"

[[feeds]]
name = "62info"
url = "https://62info.ru/news/rss/"
kind = "world"

[[feeds]]
name = "YA62"
url = "https://ya62.ru/rss/"
kind = "world"

[[feeds]]
name = "Рязанские ведомости"
url = "https://rv-ryazan.ru/feed/"
kind = "world"
```

- [ ] **Step 6: Запустить все тесты Python**

Run: `uv run pytest -q`
Ожидание: PASS, включая пять новых тестов. Если падает `test_project_feeds_toml_is_valid` — проверить TOML на опечатку в именах лент (имена должны быть уникальными).

- [ ] **Step 7: Коммит**

```bash
git add izolenta/config.py izolenta/feeds.py feeds.toml tests/test_config.py
git commit -m "$(printf 'feat: allow kind = "world" feeds without a category\n\nGeneral-news feeds have no ai|dev|business rubric, so default_category\nbecomes optional and is required only for kind = "news". Adds the 11\nverified feeds and the two spend limits.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 2: Сбор — список `world` в `pending.json`

**Files:**
- Modify: `izolenta/collect.py` (`WORLD_PREFIX`, `CollectResult`, `_state_id`, `collect`)
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `Feed.kind == "world"`, `Settings.max_world_per_run`, `Settings.world_text_limit` из задачи 1.
- Produces: `WORLD_PREFIX = "world:"`; `CollectResult.world: list[dict] | None`; `CollectResult.world_candidates: int`; ключ `world` в `state/pending.json`, где каждая запись содержит ровно `id`, `url`, `source`, `title`, `snippet`, `text`, `text_source`, `published_at`.

- [ ] **Step 1: Расширить фабрику конфигурации в тестах**

В `tests/test_collect.py` заменить сигнатуру и тело `make_config`:

```python
def make_config(feeds, max_items=15, max_age_hours=48, accounts=(), max_posts=10, hn=False,
                habr_feeds=(), max_habr=10, world_feeds=(), max_world=10, world_text_limit=1200):
    return Config(
        settings=Settings(
            max_items_per_run=max_items,
            max_age_hours=max_age_hours,
            article_text_limit=8000,
            http_timeout=5,
            max_response_bytes=1_000_000,
            seen_retention_days=14,
            fetch_workers=4,
            user_agent="test",
            max_posts_per_run=max_posts,
            post_max_age_hours=48,
            hn_discussions=hn,
            hn_min_points=200,
            hn_min_comments=80,
            hn_max_age_hours=36,
            max_discussions_per_run=2,
            hn_top_comments=5,
            max_habr_per_run=max_habr,
            max_world_per_run=max_world,
            world_text_limit=world_text_limit,
        ),
        feeds=tuple(Feed(name, f"https://{name.lower()}.example/feed", "ai") for name in feeds)
        + tuple(Feed(name, f"https://{name.lower()}.example/feed", "ai", "habr") for name in habr_feeds)
        + tuple(Feed(name, f"https://{name.lower()}.example/feed", None, "world") for name in world_feeds),
        x_accounts=tuple(XAccount(h) for h in accounts),
    )
```

- [ ] **Step 2: Написать падающий тест отбора**

Добавить в конец `tests/test_collect.py`:

```python
def test_world_feed_items_go_to_world_list_with_own_limit(tmp_path):
    web = FakeWeb({feed_url("News"): rss(entries("News", 2)), feed_url("Mir"): rss(entries("Mir", 3))})
    result, pending, seen = run(tmp_path, make_config(["News"], world_feeds=["Mir"], max_world=2), web)
    assert [i["source"] for i in pending["items"]] == ["News", "News"]
    world = pending["world"]
    assert [w["title"] for w in world] == ["Mir post 0", "Mir post 1"]
    assert all(w["id"].startswith("world:") and len(w["id"]) == 22 for w in world)
    assert set(world[0]) == {"id", "url", "source", "title", "snippet", "text", "text_source", "published_at"}
    assert all(seen[w["id"]]["status"] == "pending" for w in world)
    stats = next(s for s in pending["stats"]["sources"] if s["name"] == "Mir")
    assert (stats["candidates"], stats["selected"]) == (3, 2)
    assert "world: candidates=3 selected=2" in result.summary()


def test_world_list_absent_without_world_feeds(tmp_path):
    web = FakeWeb({feed_url("News"): rss(entries("News", 1))})
    result, pending, _ = run(tmp_path, make_config(["News"]), web)
    assert result.world is None
    assert pending["world"] == []
    assert "world:" not in result.summary()
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_collect.py -k world -v`
Ожидание: FAIL с `KeyError: 'world'` в первом тесте.

- [ ] **Step 4: Реализовать сбор общих новостей**

В `izolenta/collect.py` после `HABR_PREFIX` добавить префикс и таблицу:

```python
HABR_PREFIX = "habr:"  # Habr articles live in their own id space: the same URL is a different job
WORLD_PREFIX = "world:"  # general news lives in its own id space too
PREFIX_BY_KIND = {"habr": HABR_PREFIX, "world": WORLD_PREFIX}
```

Заменить `_state_id`:

```python
def _state_id(feed: Feed, item: FeedItem) -> str:
    return PREFIX_BY_KIND.get(feed.kind, "") + item.id
```

В `CollectResult` добавить поля после `habr`:

```python
    world_candidates: int = 0
    world: list[dict[str, Any]] | None = None  # None when no feed has kind = "world"
```

Дописать `summary` и новый метод:

```python
    def summary(self) -> str:
        from_article = sum(1 for i in self.items if i["text_source"] == "article")
        hn = "" if self.discussions is None else f" | hn: selected={len(self.discussions)}"
        return (
            f"feeds ok={self.feeds_ok} failed={self.feeds_failed} | "
            f"candidates={self.candidates} | selected={len(self.items)} "
            f"(article={from_article}, snippet={len(self.items) - from_article})"
        ) + self._posts_summary() + hn + self._habr_summary() + self._world_summary()

    def _world_summary(self) -> str:
        if self.world is None:
            return ""
        return f" | world: candidates={self.world_candidates} selected={len(self.world)}"
```

В `collect` после строки с `habr_lists` добавить третий список и отбор:

```python
    news_lists = [fresh for feed, fresh in zip(config.feeds, per_feed) if feed.kind == "news"]
    habr_lists = [fresh for feed, fresh in zip(config.feeds, per_feed) if feed.kind == "habr"]
    world_lists = [fresh for feed, fresh in zip(config.feeds, per_feed) if feed.kind == "world"]
    result.candidates = sum(len(items) for items in news_lists)

    selected = _round_robin(news_lists, settings.max_items_per_run)
    habr_selected = _round_robin(habr_lists, settings.max_habr_per_run)
    world_selected = _round_robin(world_lists, settings.max_world_per_run)
    picked = {item.id for item in selected + habr_selected + world_selected}
```

Заменить блок извлечения текстов (общие новости берут свой лимит — абзац из 2–3 предложений не требует 5000 знаков):

```python
    with ThreadPoolExecutor(max_workers=settings.fetch_workers) as pool:
        articles = list(
            pool.map(lambda item: article_text(item, fetch, settings.article_text_limit), selected + habr_selected)
        )
        world_articles = list(
            pool.map(lambda item: article_text(item, fetch, settings.world_text_limit), world_selected)
        )
    habr_articles = articles[len(selected):]
```

После блока `if any(feed.kind == "habr" ...)` добавить такой же блок для общих новостей:

```python
    if any(feed.kind == "world" for feed in config.feeds):
        result.world_candidates = sum(len(items) for items in world_lists)
        result.world = []
        for item, article in zip(world_selected, world_articles):
            result.world.append(
                {
                    "id": WORLD_PREFIX + item.id,
                    "url": item.url,
                    "source": item.source,
                    "title": item.title,
                    "snippet": item.snippet,
                    "text": article.text,
                    "text_source": article.text_source,
                    "published_at": iso_z(item.published_at),
                }
            )
            entry = seen.setdefault(
                WORLD_PREFIX + item.id, {"first_seen": now.isoformat(), "status": "pending", "attempts": 0}
            )
            entry["status"] = "pending"
```

В вызове `save_json_atomic` для `pending.json` добавить ключ после `habr`:

```python
            "habr": result.habr or [],
            "world": result.world or [],
```

- [ ] **Step 5: Запустить тесты**

Run: `uv run pytest tests/test_collect.py -v`
Ожидание: PASS, все тесты файла.

- [ ] **Step 6: Тест на дубль URL между двумя лентами (Review Focus 2)**

```python
def test_same_url_in_two_world_feeds_taken_once(tmp_path):
    shared = [("https://shared.example/one", "Одно событие", NOW)]
    web = FakeWeb({feed_url("Mir"): rss(shared), feed_url("Ria"): rss(shared)})
    _, pending, _ = run(tmp_path, make_config([], world_feeds=["Mir", "Ria"]), web)
    assert [w["url"] for w in pending["world"]] == ["https://shared.example/one"]
```

Run: `uv run pytest tests/test_collect.py -k two_world_feeds -v`
Ожидание: PASS сразу — отбор уже отбрасывает повторный id через `taken_ids`. Тест закрепляет это поведение.

- [ ] **Step 7: Тест на свой лимит текста**

```python
def test_world_items_get_their_own_text_limit(tmp_path, monkeypatch):
    from izolenta.extract import ArticleContent

    limits = {}

    def fake_article_text(item, fetch, limit):
        limits[item.url] = limit
        return ArticleContent(text="Текст заметки.", text_source="article", image=None)

    monkeypatch.setattr("izolenta.collect.article_text", fake_article_text)
    web = FakeWeb({feed_url("News"): rss(entries("News", 1)), feed_url("Mir"): rss(entries("Mir", 1))})
    config = make_config(["News"], world_feeds=["Mir"], world_text_limit=1200)
    run(tmp_path, config, web)
    assert limits["https://news.example/post-0"] == 8000
    assert limits["https://mir.example/post-0"] == 1200
```

Run: `uv run pytest tests/test_collect.py -k own_text_limit -v`
Ожидание: PASS.

- [ ] **Step 8: Тест на заголовки в CDATA (Review Focus 3)**

```python
def test_cdata_title_and_snippet_are_unwrapped(tmp_path):
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
        "<item><title><![CDATA[В России утвердили ГОСТ на овощные полуфабрикаты]]></title>"
        "<link>https://rbc.example/1</link>"
        "<pubDate>Thu, 08 Oct 2026 10:00:00 +0000</pubDate>"
        "<description><![CDATA[Документ вступает в силу с 1 января.]]></description></item>"
        "</channel></rss>"
    ).encode()
    web = FakeWeb({feed_url("Rbc"): feed})
    _, pending, _ = run(tmp_path, make_config([], world_feeds=["Rbc"]), web)
    [item] = pending["world"]
    assert item["title"] == "В России утвердили ГОСТ на овощные полуфабрикаты"
    assert "вступает в силу" in item["snippet"]
    assert "CDATA" not in item["title"] + item["snippet"]
```

Run: `uv run pytest tests/test_collect.py -k cdata -v`
Ожидание: PASS. `feedparser` раскрывает CDATA сам; тест фиксирует это, потому что так отдают РБК, Коммерсантъ и N+1.

- [ ] **Step 9: Тест на повторную обработку**

```python
def test_processed_world_items_not_selected_again(tmp_path):
    from izolenta.feeds import canonical_url, item_id

    world_entries = entries("Mir", 2)
    done = "world:" + item_id(canonical_url(world_entries[0][0]))
    web = FakeWeb({feed_url("Mir"): rss(world_entries)})
    _, pending, _ = run(tmp_path, make_config([], world_feeds=["Mir"]), web, seen={done: seen_entry("skipped")})
    assert [w["title"] for w in pending["world"]] == ["Mir post 1"]
```

Run: `uv run pytest tests/test_collect.py -k not_selected_again -v`
Ожидание: PASS.

- [ ] **Step 10: Тест на падение одной ленты (Review Focus 5)**

```python
def test_failing_world_feed_does_not_stop_the_others(tmp_path):
    web = FakeWeb({feed_url("Mir"): rss(entries("Mir", 1))})  # лента Ria отвечает 404
    result, pending, _ = run(tmp_path, make_config([], world_feeds=["Mir", "Ria"]), web)
    assert [w["title"] for w in pending["world"]] == ["Mir post 0"]
    assert (result.feeds_ok, result.feeds_failed) == (1, 1)
    assert any(e["feed"] == "Ria" for e in pending["errors"])
```

Run: `uv run pytest tests/test_collect.py -v`
Ожидание: PASS, все тесты файла.

- [ ] **Step 11: Коммит**

```bash
git add izolenta/collect.py tests/test_collect.py
git commit -m "$(printf 'feat: collect kind = "world" feeds into pending.world\n\nOwn round-robin budget (max_world_per_run), own id space (world:<hex>)\nand a tighter text limit (world_text_limit): one paragraph does not need\n5000 characters every hour.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 3: Схема — `validate_world`

**Files:**
- Modify: `izolenta/schema.py` (в конец файла)
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: существующий `_validate_retelling(raw, is_valid_id, id_hint, summary_len, result_type)` из `izolenta/schema.py`.
- Produces: `WORLD_SUMMARY_LEN = (80, 400)`; `WORLD_ID = re.compile(r"world:[0-9a-f]{16}")`; `WorldSummary(id: str, title: str, summary: str)`; `validate_world(raw: Any) -> WorldSummary | Skip`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_schema.py`:

```python
from izolenta.schema import WorldSummary, validate_world  # noqa: E402

WORLD_ID_OK = "world:0123456789abcdef"
WORLD_SUMMARY = (
    "Совет директоров Банка России снизил ключевую ставку на один процентный пункт, до 14 процентов. "
    "Регулятор объяснил решение замедлением инфляции до 6,2 процента в годовом выражении."
)


def test_valid_world_accepted():
    raw = {"id": WORLD_ID_OK, "status": "ok", "title": "ЦБ снизил ключевую ставку до 14 процентов",
           "summary": WORLD_SUMMARY}
    assert validate_world(raw) == WorldSummary(
        id=WORLD_ID_OK, title="ЦБ снизил ключевую ставку до 14 процентов", summary=WORLD_SUMMARY
    )


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"summary": "Коротко о событии."}, "summary"),
        ({"summary": "А" * 401}, "summary"),
        ({"summary": WORLD_SUMMARY + "\n\n" + WORLD_SUMMARY}, "summary"),
        ({"summary": "A" * 120}, "summary"),
        ({"summary": "Событие <b>важное</b>, подробности и цифры приведены в источнике, читайте оригинал."}, "summary"),
        ({"title": "Short"}, "title"),
        ({"id": "0123456789abcdef"}, "id"),
        ({"id": "habr:0123456789abcdef"}, "id"),
        ({"id": "world:XYZ"}, "id"),
    ],
)
def test_invalid_world_rejected(overrides, field):
    raw = {"id": WORLD_ID_OK, "status": "ok", "title": "Заголовок общей новости", "summary": WORLD_SUMMARY, **overrides}
    with pytest.raises(ValidationError) as info:
        validate_world(raw)
    assert any(field in reason for reason in info.value.reasons)


def test_world_skip_accepted():
    assert validate_world({"id": WORLD_ID_OK, "status": "skip", "reason": "заявление без решения"}) == Skip(
        id=WORLD_ID_OK, reason="заявление без решения"
    )


def test_world_skip_for_low_importance_allowed():
    """Epic 6, R5: here significance IS the filter, unlike the AI/IT feed."""
    assert validate_world({"id": WORLD_ID_OK, "status": "skip", "reason": "малозначимое событие"}) == Skip(
        id=WORLD_ID_OK, reason="малозначимое событие"
    )
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_schema.py -k world -v`
Ожидание: FAIL на импорте — `ImportError: cannot import name 'WorldSummary' from 'izolenta.schema'`.

- [ ] **Step 3: Реализовать `validate_world`**

Добавить в конец `izolenta/schema.py`:

```python
# General news: {"id": "world:<16 hex>", "status": "ok", "title": "...", "summary": "..."} or a skip.
# A tighter summary than Habr or HN on purpose: the «Новости» page shows one compressed paragraph.
# Unlike validate_summary, a skip here may cite low significance: for general news significance is the filter.

WORLD_SUMMARY_LEN = (80, 400)
WORLD_ID = re.compile(r"world:[0-9a-f]{16}")


@dataclass(frozen=True)
class WorldSummary:
    id: str
    title: str
    summary: str


def validate_world(raw: Any) -> WorldSummary | Skip:
    def is_world_id(value: Any) -> bool:
        return isinstance(value, str) and WORLD_ID.fullmatch(value) is not None

    return _validate_retelling(raw, is_world_id, "'world:<16 hex>'", WORLD_SUMMARY_LEN, WorldSummary)
```

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_schema.py -v`
Ожидание: PASS.

- [ ] **Step 5: Проверить, что запрет для ленты AI/IT не задет**

Run: `uv run pytest tests/test_schema.py -k low_importance -v`
Ожидание: PASS обоих тестов — `test_skip_for_low_importance_rejected` (лента AI/IT, запрет остаётся) и `test_world_skip_for_low_importance_allowed` (общие новости, разрешено). Если первый упал, значит правка задела `validate_summary` — откатить её.

- [ ] **Step 6: Тесты на границы длины (Review Focus 4)**

```python
def world_summary_of(length):
    """Ровно length знаков после normalize: пробел в тексте один."""
    head = "Событие. "
    return head + "а" * (length - len(head))


@pytest.mark.parametrize("length", [80, 400])
def test_world_summary_boundaries_accepted(length):
    summary = world_summary_of(length)
    raw = {"id": WORLD_ID_OK, "status": "ok", "title": "Заголовок общей новости", "summary": summary}
    assert validate_world(raw).summary == summary


@pytest.mark.parametrize("length", [79, 401])
def test_world_summary_outside_boundaries_rejected(length):
    raw = {"id": WORLD_ID_OK, "status": "ok", "title": "Заголовок общей новости",
           "summary": world_summary_of(length)}
    with pytest.raises(ValidationError, match="summary"):
        validate_world(raw)
```

Run: `uv run pytest tests/test_schema.py -k boundaries -v`
Ожидание: PASS.

- [ ] **Step 7: Коммит**

```bash
git add izolenta/schema.py tests/test_schema.py
git commit -m "$(printf 'feat: validate world news summaries (80-400 chars, one paragraph)\n\nReuses _validate_retelling. A skip may cite low significance here: for\ngeneral news significance is the filter, unlike the AI/IT feed where\nLOW_IMPORTANCE_SKIP rejects that reason.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 4: Слияние — `world.json` и страница состояния

**Files:**
- Modify: `izolenta/merge.py` (`WORLD_RETENTION_DAYS`, `_world_record`, `WORLD`, `OPTIONAL_KINDS`, `SUMMARY_KEYS`, `MergeResult`, `merge`)
- Modify: `izolenta/__main__.py` (аргумент `--world`, перечень видов в `run_merge`)
- Create: `site/data/world.json`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: `validate_world`, `WorldSummary` из задачи 3; ключ `world` в `pending.json` из задачи 2.
- Produces: `merge(..., world_path: Path | None = None)`; `MergeResult.world: KindResult | None`; файл `site/data/world.json` вида `{"generated_at": ..., "items": [...]}`, где запись содержит ровно `id`, `url`, `source`, `published_at`, `title`, `summary`; материал вида `world` в `status.json`.

- [ ] **Step 1: Подготовить тестовое окружение**

В `tests/test_merge.py` в классе `Env` в `__init__` добавить путь после `self.habr`:

```python
        self.world = tmp_path / "site" / "data" / "world.json"
```

В `Env.setup` расширить сигнатуру и тело:

```python
    def setup(self, items, summaries, seen=None, news=None, posts=None, post_summaries=None, posts_store=None,
              discussions=None, discussion_summaries=None, hn_store=None, habr=None, habr_summaries=None,
              world=None, world_summaries=None):
        pending = {"generated_at": iso(NOW), "items": items, "errors": []}
        if posts is not None:
            pending["posts"] = posts
        if discussions is not None:
            pending["discussions"] = discussions
        if habr is not None:
            pending["habr"] = habr
        if world is not None:
            pending["world"] = world
        self.write("pending.json", pending)
        if summaries is not None:
            data = {"items": summaries}
            if post_summaries is not None:
                data["posts"] = post_summaries
            if discussion_summaries is not None:
                data["discussions"] = discussion_summaries
            if habr_summaries is not None:
                data["habr"] = habr_summaries
            if world_summaries is not None:
                data["world"] = world_summaries
            self.write("summaries.json", data)
        default_seen = {
            i["id"]: {"first_seen": NOW.isoformat(), "status": "pending", "attempts": 0}
            for i in items + (posts or []) + (discussions or []) + (habr or []) + (world or [])
        }
```

Остальное тело `setup` не менять.

- [ ] **Step 2: Написать падающий тест слияния**

Добавить в конец `tests/test_merge.py`:

```python
# --- General news: compressed into world.json for the «Новости» page ---

WORLD_RU = (
    "Совет директоров Банка России снизил ключевую ставку на один процентный пункт, до 14 процентов. "
    "Регулятор объяснил решение замедлением инфляции."
)


def pending_world(n, published=NOW - timedelta(hours=3)):
    return {
        "id": f"world:{n:016x}",
        "url": f"https://lenta.ru/news/2026/10/08/{n}/",
        "source": "Лента.ру: Экономика",
        "title": "ЦБ снизил ставку",
        "snippet": "snippet",
        "text": "text",
        "text_source": "article",
        "published_at": iso(published),
    }


def test_world_item_merged_with_collector_metadata(env):
    forged = {"id": "world:0000000000000001", "status": "ok",
              "title": "ЦБ снизил ключевую ставку до 14 процентов", "summary": WORLD_RU,
              "url": "https://evil.example", "source": "evil", "published_at": iso(NOW)}
    env.setup([], [], world=[pending_world(1), pending_world(2)],
              world_summaries=[forged, {"id": "world:0000000000000002", "status": "skip",
                                        "reason": "заявление без решения"}])
    result = env.run()
    assert (result.world.merged, result.world.skipped) == (1, 1)
    [record] = json.loads(env.world.read_text(encoding="utf-8"))["items"]
    assert record == {
        "id": "world:0000000000000001",
        "url": "https://lenta.ru/news/2026/10/08/1/",
        "source": "Лента.ру: Экономика",
        "published_at": iso(NOW - timedelta(hours=3)),
        "title": "ЦБ снизил ключевую ставку до 14 процентов",
        "summary": WORLD_RU,
    }
    assert "world: merged=1 skipped=1" in result.summary()
```

- [ ] **Step 3: Убедиться, что тест падает**

Run: `uv run pytest tests/test_merge.py -k world_item_merged -v`
Ожидание: FAIL с `AttributeError: 'MergeResult' object has no attribute 'world'`.

- [ ] **Step 4: Реализовать слияние общих новостей**

В `izolenta/merge.py` добавить импорт `WorldSummary` и `validate_world` в существующий блок `from izolenta.schema import (...)`, затем срок хранения рядом с остальными:

```python
HABR_RETENTION_DAYS = 7
WORLD_RETENTION_DAYS = 2  # general news ages faster than AI/IT news; the dedup window is the same 48 hours
```

После `_habr_record` добавить запись общей новости:

```python
def _world_record(item: dict[str, Any], summary: WorldSummary) -> dict[str, Any]:
    # link, source and date come from the collector; Claude writes only the title and the paragraph
    return {
        "id": item["id"],
        "url": item["url"],
        "source": item["source"],
        "published_at": item["published_at"],
        "title": summary.title,
        "summary": summary.summary,
    }
```

После объявления `HABR` добавить вид и обновить перечни:

```python
WORLD = Kind(
    "world",
    "world ",
    validate_world,
    _world_record,
    lambda item: item.get("title", ""),
    "world",
    _article_material,
)
OPTIONAL_KINDS = (POSTS, DISCUSSIONS, HABR, WORLD)
```

В `MergeResult` добавить поле после `habr`:

```python
    world: KindResult | None = None  # None when pending.json has no world list
```

Дописать `MergeResult.summary` перед `return line`:

```python
        if self.world is not None:
            line += f" | world: {self.world.counts()} | total={self.world.total}"
```

Расширить `SUMMARY_KEYS`:

```python
SUMMARY_KEYS = ("items", "posts", "discussions", "habr", "world")
```

В сигнатуру `merge` добавить параметр последним:

```python
    habr_path: Path | None = None,
    world_path: Path | None = None,
) -> MergeResult:
```

И в двух словарях внутри `merge`:

```python
    store_paths = {
        POSTS.key: Path(posts_path) if posts_path else news_path.parent / "posts.json",
        DISCUSSIONS.key: Path(hn_path) if hn_path else news_path.parent / "hn.json",
        HABR.key: Path(habr_path) if habr_path else news_path.parent / "habr.json",
        WORLD.key: Path(world_path) if world_path else news_path.parent / "world.json",
    }
    retention = {
        POSTS.key: POST_RETENTION_DAYS,
        DISCUSSIONS.key: DISCUSSION_RETENTION_DAYS,
        HABR.key: HABR_RETENTION_DAYS,
        WORLD.key: WORLD_RETENTION_DAYS,
    }
```

- [ ] **Step 5: Запустить тест**

Run: `uv run pytest tests/test_merge.py -k world -v`
Ожидание: PASS.

- [ ] **Step 6: Тесты на хранение, статус и `check`**

```python
def test_world_items_kept_for_two_days(env):
    old = {"id": "world:00000000000000aa", "url": "https://lenta.ru/news/old/", "source": "Лента.ру: Мир",
           "published_at": iso(NOW - timedelta(days=3)), "title": "Старая общая новость", "summary": WORLD_RU}
    recent = {**old, "id": "world:00000000000000bb", "published_at": iso(NOW - timedelta(days=1))}
    env.world.parent.mkdir(parents=True, exist_ok=True)
    env.world.write_text(json.dumps({"generated_at": "x", "items": [old, recent]}, ensure_ascii=False),
                         encoding="utf-8")
    env.setup([], [], world=[])
    env.run()
    kept = json.loads(env.world.read_text(encoding="utf-8"))["items"]
    assert [r["id"] for r in kept] == ["world:00000000000000bb"]


def test_world_outcomes_recorded_on_status_page(env):
    env.setup([], [], world=[pending_world(1)],
              world_summaries=[{"id": "world:0000000000000001", "status": "skip",
                                "reason": "частное происшествие"}])
    env.run()
    entry = materials(env)["world:0000000000000001"]
    assert (entry["kind"], entry["outcome"], entry["reason"]) == ("world", "skipped", "частное происшествие")
    assert entry["source"] == "Лента.ру: Экономика"


def test_check_reports_missing_world_summary(env):
    from izolenta.merge import check

    env.setup([], [], world=[pending_world(1)], world_summaries=[])
    result = check(env.state)
    assert any("world" in problem and "world:0000000000000001" in problem for problem in result.problems)
```

Run: `uv run pytest tests/test_merge.py -v`
Ожидание: PASS, все тесты файла.

- [ ] **Step 7: Провести путь до CLI**

В `izolenta/__main__.py` в `run_merge` передать путь и добавить вид в перечень:

```python
def run_merge(args: argparse.Namespace) -> None:
    result = merge(
        args.state_dir,
        args.news,
        datetime.now(UTC),
        posts_path=args.posts,
        hn_path=args.hn,
        status_path=args.status,
        habr_path=args.habr,
        world_path=args.world,
    )
    print(result.summary())
    if result.summaries_error:
        print(f"  summaries error: {result.summaries_error}")
    kinds = (("", result), ("post ", result.posts), ("discussion ", result.discussions),
             ("habr ", result.habr), ("world ", result.world))
```

И зарегистрировать аргумент рядом с `--habr`:

```python
    merge_cmd.add_argument("--world", type=Path, default=Path("site/data/world.json"))
```

- [ ] **Step 8: Создать начальный файл данных**

```bash
cat > site/data/world.json <<'JSON'
{
  "generated_at": "2026-10-13T00:00:00Z",
  "items": []
}
JSON
uv run python -c "import json;print(json.load(open('site/data/world.json'))['items'])"
```

Ожидание: `[]`. Пустой файл нужен, чтобы страница `#/world` не показывала «Лента порвалась» до первого запуска routine.

- [ ] **Step 9: Проверить CLI на живом состоянии**

```bash
rm -rf /tmp/izo && mkdir -p /tmp/izo
uv run python -c "
import json, pathlib
state = pathlib.Path('/tmp/izo'); state.mkdir(exist_ok=True)
(state / 'pending.json').write_text(json.dumps({
  'generated_at': '2026-10-13T10:00:00Z', 'items': [], 'world': [{
    'id': 'world:0000000000000001', 'url': 'https://lenta.ru/news/1/', 'source': 'Лента.ру: Экономика',
    'title': 'ЦБ снизил ставку', 'snippet': 's', 'text': 't', 'text_source': 'article',
    'published_at': '2026-10-13T09:00:00Z'}], 'errors': [], 'stats': {'sources': []}}, ensure_ascii=False), encoding='utf-8')
(state / 'summaries.json').write_text(json.dumps({'world': [{
    'id': 'world:0000000000000001', 'status': 'ok',
    'title': 'ЦБ снизил ключевую ставку до 14 процентов',
    'summary': 'Совет директоров Банка России снизил ставку на один процентный пункт. Регулятор объяснил решение замедлением инфляции.'}]}, ensure_ascii=False), encoding='utf-8')
"
uv run python -m izolenta check --state-dir /tmp/izo
uv run python -m izolenta merge --state-dir /tmp/izo --news /tmp/izo/news.json
uv run python -m izolenta recent --news /tmp/izo/world.json --hours 48
```

Ожидание: `check` печатает `ok: every pending item has a valid summary` и выходит с кодом 0; `merge` печатает строку с ` | world: merged=1 skipped=0 ... | total=1`; `recent` печатает одну строку с id, временем, источником и заголовком. Последнее подтверждает, что дедупликация между источниками работает без правок кода.

- [ ] **Step 10: Коммит**

```bash
git add izolenta/merge.py izolenta/__main__.py site/data/world.json tests/test_merge.py
git commit -m "$(printf 'feat: merge world news into site/data/world.json\n\nFifth Kind in the merge pipeline: two-day retention, collector metadata\nonly, outcomes recorded on the status page. recent --news world.json\nserves the cross-source dedup rule with no code change.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 5: Страница `#/world` и пункт меню

**Files:**
- Modify: `site/lib.js` (`parseRoute`, `KIND_BY_MATERIAL`)
- Modify: `site/app.js` (`WORLD_URL`, `state`, `worldCard`, `worldView`, `render`, `updateChrome`, `load`, `MATERIAL_KINDS`, `siteHref`, `runsTable`)
- Modify: `site/index.html` (пункт меню)
- Modify при необходимости: `site/styles.css` — классы `.posts-page` и `.discussion` переиспользуются, поэтому нового CSS быть не должно. Если проверка на шаге 8 покажет проблему с вёрсткой, править здесь.
- Test: `tests/js/lib.test.mjs`

**Interfaces:**
- Consumes: `site/data/world.json` из задачи 4; запись вида `{id, url, source, published_at, title, summary}`.
- Produces: маршрут `{view: "world"}`; `KIND_BY_MATERIAL.world === "feed"`.

- [ ] **Step 1: Написать падающие тесты маршрута**

В `tests/js/lib.test.mjs` в блок `describe("parseRoute", ...)` добавить:

```js
  test("world news page", () => {
    assert.deepEqual(parseRoute("#/world"), { view: "world" });
  });

  test("the article route still wins over the news prefix", () => {
    assert.deepEqual(parseRoute("#/news/92be971aec513c1f"), { view: "article", id: "92be971aec513c1f" });
  });
```

В блок `describe("status page", ...)` добавить:

```js
  test("world materials count towards their feed row", () => {
    const status = {
      runs: [run("2026-10-08T12:00:00Z", [src("Лента.ру: Мир")])],
      materials: [
        { id: "world:1", source: "Лента.ру: Мир", outcome: "published", kind: "world" },
        { id: "world:2", source: "Лента.ру: Мир", outcome: "skipped", kind: "world" },
      ],
    };
    const [row] = summarizeSources(status);
    assert.equal(row.kind, "feed");
    assert.deepEqual([row.published, row.skipped, row.problems], [1, 1, 0]);
  });
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `node --test "tests/js/*.test.mjs"`
Ожидание: FAIL — `parseRoute("#/world")` возвращает `{ view: "home" }`.

- [ ] **Step 3: Добавить маршрут и тип материала**

В `site/lib.js` в `parseRoute` расширить список односегментных видов:

```js
  if (["x", "hn", "habr", "world", "status"].includes(parts[0]) && parts.length === 1) {
    return { view: parts[0] };
  }
```

И таблицу видов материалов для страницы состояния:

```js
const KIND_BY_MATERIAL = { article: "feed", habr: "feed", world: "feed", post: "x", discussion: "hn" };
```

- [ ] **Step 4: Запустить тесты**

Run: `node --test "tests/js/*.test.mjs"`
Ожидание: PASS.

- [ ] **Step 5: Нарисовать страницу**

В `site/app.js` рядом с остальными адресами данных добавить:

```js
const WORLD_URL = "data/world.json";
```

В объект `state` добавить два поля:

```js
const state = {
  data: null, error: null, posts: null, postsError: null, hn: null, hnError: null, habr: null, habrError: null,
  world: null, worldError: null,
  blockedHost: null,
};
```

После `habrView` добавить карточку и страницу. Карточка повторяет устройство карточки Хабра без автора: у новостных агентств он не нужен.

```js
function worldCard(n) {
  return el(
    "article",
    { class: "discussion" },
    el(
      "div",
      { class: "post__head" },
      el("span", { class: "post__time" }, formatTime(n.published_at)),
      el("span", { class: "post__handle" }, n.source),
    ),
    externalLink(n.url, n.title, "discussion__title"),
    el("p", { class: "post__text discussion__summary" }, n.summary),
    isSafeUrl(n.url)
      ? el("a", { class: "post__link", href: n.url, target: "_blank", rel: "noopener noreferrer" }, `Читать на ${n.source} →`)
      : null,
  );
}

function worldView() {
  document.title = "Новости — ИИзоЛента";
  const title = el("h1", { class: "page-title" }, "Новости");
  if (state.worldError) {
    return [
      title,
      stateView("Лента порвалась.", el("button", { class: "state__button", type: "button", onclick: () => load() }, "Подклеить")),
    ];
  }
  if (!state.world) return [title, stateView("Разматываем ленту...")];
  if (!state.world.items.length) return [title, stateView("Пока тихо: свежих новостей нет.")];
  return [title, el("div", { class: "posts-page" }, state.world.items.map(worldCard))];
}
```

В `render` добавить ветку после `habr`:

```js
  } else if (route.view === "habr") {
    content = habrView();
  } else if (route.view === "world") {
    content = worldView();
  } else if (route.view === "status") {
```

В `updateChrome` добавить вид в список подсвечиваемых:

```js
  const active = route.view === "category" ? route.category : ["x", "hn", "habr", "world"].includes(route.view) ? route.view : "";
```

В `load` добавить пятый источник данных:

```js
async function load() {
  const [news, posts, hn, habr, world] = await Promise.allSettled([
    loadJson(DATA_URL),
    loadJson(POSTS_URL),
    loadJson(HN_URL),
    loadJson(HABR_URL),
    loadJson(WORLD_URL),
  ]);
```

И обработку результата перед `render()`:

```js
  if (world.status === "fulfilled") {
    state.world = world.value;
    state.worldError = null;
  } else {
    console.warn("ИИзоЛента: не удалось загрузить новости раздела «Новости»", world.reason);
    if (!state.world) state.worldError = world.reason;
  }
  render();
}
```

- [ ] **Step 6: Показать новый тип на странице состояния**

В `site/app.js` расширить таблицу видов материалов и ссылки:

```js
const MATERIAL_KINDS = { article: "Статья", habr: "Хабр", world: "Новости", post: "Пост X", discussion: "HN" };
```

```js
function siteHref(material) {
  if (material.outcome !== "published") return null;
  if (material.kind === "article") return articleHref(material);
  return { post: "#/x", discussion: "#/hn", habr: "#/habr", world: "#/world" }[material.kind] || null;
}
```

В `runsTable` добавить два столбца. Столбца Хабра там не было с эпика 5, поэтому добавляются оба — иначе половина работы запуска не видна:

```js
function runsTable(runs) {
  return table(
    ["Обработка", "Сбор", "Источники", "Новых → взято", "Статьи", "Посты", "HN", "Хабр", "Новости"],
    runs.map((run) => {
      const sources = run.sources || [];
      const ok = sources.filter((s) => s.ok).length;
      const candidates = sources.reduce((sum, s) => sum + (s.candidates || 0), 0);
      const selected = sources.reduce((sum, s) => sum + (s.selected || 0), 0);
      return [
        formatTime(run.merged_at),
        formatTime(run.collected_at),
        el("span", { class: ok < sources.length ? "status-bad" : null }, `${ok} из ${sources.length}`),
        `${candidates} → ${selected}`,
        kindResult(run.result?.items),
        kindResult(run.result?.posts),
        kindResult(run.result?.discussions),
        kindResult(run.result?.habr),
        kindResult(run.result?.world),
      ];
    }),
  );
}
```

`kindResult` уже возвращает `—` для отсутствующего вида, поэтому старые записи `status.json` без ключей `habr` и `world` отрисуются без ошибок.

- [ ] **Step 7: Добавить пункт меню**

В `site/index.html` после пункта Хабра добавить последним:

```html
      <a class="menu__link" href="#/habr" data-category="habr">Пишут на Хабре</a>
      <a class="menu__link" href="#/world" data-category="world">Новости</a>
```

- [ ] **Step 8: Проверить в браузере (включая Review Focus 1)**

```bash
uv run python -m http.server -d site 8000
```

Проверить при ширине окна 1280 и 360 пикселей, открывая консоль разработчика:

1. `http://localhost:8000/#/world` — заголовок «Новости», состояние «Пока тихо: свежих новостей нет» (файл пустой), пункт меню «Новости» подсвечен и стоит последним.
2. Главная `http://localhost:8000/#/` — блока «Новости» нет, сверху главная новость AI/IT, справа блоки X, HN и Хабра.
3. Маршрут статьи не перехвачен новым разделом. Взять настоящий id:
   ```bash
   uv run python -c "import json;print(json.load(open('site/data/news.json', encoding='utf-8'))['items'][0]['id'])"
   ```
   Открыть `http://localhost:8000/#/news/<этот id>` — должна открыться страница новости AI/IT, а не раздел «Новости».
4. `http://localhost:8000/#/status` — в таблице запусков девять столбцов, последние два («Хабр», «Новости») показывают `—` для старых записей.
5. Временно подменить файл на битый и перезагрузить `#/world`:
   ```bash
   cp site/data/world.json /tmp/world.json.bak
   printf 'not json' > site/data/world.json
   ```
   Ожидание: на `#/world` — «Лента порвалась.» и кнопка «Подклеить»; главная, `#/x`, `#/hn`, `#/habr` работают как обычно; в консоли одно предупреждение `не удалось загрузить новости раздела «Новости»` и ни одной необработанной ошибки. Затем вернуть файл:
   ```bash
   cp /tmp/world.json.bak site/data/world.json
   ```
6. Удалить файл и перезагрузить `#/world` — то же состояние «Лента порвалась» (HTTP 404), остальные страницы работают. Вернуть файл.
7. На 360 пикселях на всех страницах `document.documentElement.scrollWidth <= 360` — проверить в консоли.

- [ ] **Step 9: Коммит**

```bash
git add site/lib.js site/app.js site/index.html tests/js/lib.test.mjs
git commit -m "$(printf 'feat: add the #/world page and the «Новости» menu item\n\nNo home-page block: the front page stays about AI and IT. The card\nreuses the Habr card markup, so no new CSS. The runs table on #/status\nnow also has the Habr and world columns.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 6: Правила для routine и документация

**Files:**
- Modify: `routine/PROMPT.md` (вводный абзац, шаги 3, 5, 6, 7, формат `summaries.json`, новый раздел правил)
- Modify: `README.md` (описание, схема конвейера, раздел «Как расширять»)
- Test: `tests/test_prompt.py` (создать)

**Interfaces:**
- Consumes: `izolenta.schema.WORLD_SUMMARY_LEN`, `izolenta.merge.WORLD_RETENTION_DAYS` из задач 3 и 4.
- Produces: контракт промпта. Ошибка здесь не ломает тесты, но ломает каждый час работы routine, поэтому числа закрепляются тестом.

- [ ] **Step 1: Написать падающий тест согласованности промпта и кода**

Создать `tests/test_prompt.py`:

```python
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


def test_prompt_allows_low_significance_skips_only_for_world_news():
    assert "значимость" in PROMPT
    assert str(WORLD_RETENTION_DAYS) in PROMPT
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `uv run pytest tests/test_prompt.py -v`
Ожидание: FAIL всех пяти тестов, кроме `test_prompt_names_every_data_file_the_merge_writes`, который падает только на `world.json`.

- [ ] **Step 3: Правка вводного абзаца и шага 3 в `routine/PROMPT.md`**

Заменить первый абзац после заголовка:

```markdown
Ты — редактор ленты «ИИзоЛента»: русскоязычные выжимки мировых новостей AI и IT, переводы постов известных людей из X, пересказы обсуждений на Hacker News и авторских статей Хабра, а также сжатые заметки об общих новостях для раздела «Новости». Этот файл — полная инструкция одного запуска. Выполняй шаги по порядку, ничего сверх них не делай.
```

В разделе «Два репозитория» заменить описание `pending.json`:

```markdown
- `iizolenta-work` — приватное состояние: `state/pending.json` (новые статьи, посты, обсуждения HN, статьи Хабра и общие новости; их раз в час собирает GitHub Actions) и `state/seen.json`.
```

В конце пункта «Есть ли работа» шага 2 заменить условие:

```markdown
   **Есть ли работа.** Если файла `$WORK/state/pending.json` нет или в нём пусты `items`, `posts`, `discussions`, `habr` и `world` — заверши запуск, больше ничего не коммить.
```

В шаге 3 после команды `izolenta recent --hours 48` добавить вторую команду и расширить перечень списков:

```markdown
3. **Выжимки и переводы.** Сначала выполни `uv run python -m izolenta recent --hours 48` — это уже опубликованные за двое суток новости AI/IT (id | время | источник | заголовок). Затем выполни `uv run python -m izolenta recent --news site/data/world.json --hours 48` — то же для раздела «Новости». Статья или заметка, которая описывает уже опубликованное событие и не добавляет к нему существенно новых фактов, — `skip` с причиной «дубль опубликованной <id>».
   **Работай порциями:** записей может быть до 50 статей, 10 постов, 4 обсуждений, 10 статей Хабра и 25 общих новостей. Читай `pending.json` частями (не больше 10 статей за раз) и пиши результат порциями — не больше 10 записей за одну команду, каждую порцию в отдельный файл `$WORK/state/summaries.<N>.json` (N = 1, 2, 3, ...) в том же формате, что и `summaries.json` (объект со списками `items`, `posts`, `discussions`, `habr`, `world`). `check` и `merge` сами объединяют все части.
```

В том же шаге заменить абзац про чтение текста — у общих новостей другой лимит, и без этой правки routine будет ждать 5000 символов там, где их нет (требование R6):

```markdown
   **Читай каждый текст целиком.** Решение `ok` или `skip` принимай только после чтения поля `text` записи полностью (до 5000 символов у статей и статей Хабра, до 1200 у общих новостей; не обрезай вывод) или `snippet`, если `text` пуст. Пропускать запись по одному заголовку нельзя. Это касается всех записей, включая очевидно далёкие от IT: прочитать их можно быстро, но прочитать нужно.
```

И в абзаце про перечень обязательных записей дописать после Хабра:

```markdown
   и для **каждого** элемента `world` (используй только `title`, `text`, `snippet`, `source`, `text_source`).
```

- [ ] **Step 4: Правка формата `summaries.json`**

В раздел «Формат `$WORK/state/summaries.json`» добавить `world` в первое предложение и в пример JSON после массива `habr`:

```markdown
JSON-объект с массивами `items` (статьи), `posts` (посты из X), `discussions` (обсуждения HN), `habr` (статьи Хабра) и `world` (общие новости). Запись `ok` — материал для сайта, `skip` — пропуск с причиной:
```

```json
  "world": [
    {"id": "world:3f2a9c0d41b7e865", "status": "ok", "title": "ЦБ снизил ключевую ставку до 14 процентов", "summary": "Совет директоров Банка России снизил ставку на один процентный пункт — четвёртое снижение за год. Регулятор объяснил решение замедлением инфляции до 6,2 процента в годовом выражении."},
    {"id": "world:7c01d5e9a2b3f448", "status": "skip", "reason": "заявление без решения"}
  ]
```

В перечень требований, которые проверяет `check`, добавить строку после строки про статью Хабра:

```markdown
- Общая новость: `id` — как в `pending.json` (`world:` и 16 символов); `title` — 10-200 символов; `summary` — 80-400 символов, один абзац; кириллица, без `<` и `>`.
```

- [ ] **Step 5: Добавить раздел правил «Новости»**

В конец `routine/PROMPT.md` добавить новый раздел:

```markdown
## Новости (раздел «Новости»)

Для каждого элемента `world` дана общая новость: мир, Россия, Рязань, наука, культура или спорт. Это не IT: критерии здесь свои. Пиши заголовок и один абзац 80-400 символов.

**Решающий тест.** Заметка публикуется, только если проходит три проверки:

1. Событие или решение уже произошло: есть субъект, действие и результат.
2. Оно меняет что-то шире одного частного случая: страну, отрасль, город, науку.
3. Через неделю о нём имеет смысл помнить.

Не прошла хотя бы одну — `skip` с предметной причиной.

**Что публикуем.**

- Мир и Россия: крупные события, решения, законы, международные соглашения, крупные катастрофы и стихийные бедствия.
- Рязань: городские решения и изменения — транспорт, перекрытия, ЖКХ, стройка, бюджет, что открылось и закрылось.
- Наука и медицина: открытия, исследования, космос.
- Культура и спорт: только крупное — итоги чемпионатов, премии, смерти известных людей.

**`skip`**, если заметка — это:

- военная сводка: удары, обстрелы, продвижение, потери. Поворотные события остаются: перемирие, договор, вступление новой стороны;
- заявление без решения: «заявил», «отреагировал», «предложил», «не исключил», комментарии и реакции;
- частное происшествие: отдельное ДТП, пожар, несчастный случай, пропавший человек;
- ежедневная сводка цен: курсы валют, биржа, бензин, продукты. Крупные сдвиги остаются: ключевая ставка, резкий обвал;
- криминал или суд, кроме решения по делу общественного значения;
- шоу-бизнес, личная жизнь, слухи, «в сети обсуждают»;
- совет или псевдомедицина: «врачи раскрыли», «назван продукт», «эксперт предупредил»;
- реклама, подборка, гороскоп, прогноз погоды;
- кликбейт по форме заголовка: вопрос вместо утверждения, «что известно», «подробности», «раскрыл», «шокировал», «названы причины», интрига многоточием;
- малозначимое событие. Для этого раздела значимость и есть фильтр — в отличие от ленты AI/IT, где малая значимость не повод для пропуска.

**Как писать.**

- `title` — законченное утверждение «кто что сделал», без кликбейта и вопросов, точка в конце не ставится.
- `summary` — один абзац, 2-3 предложения: что произошло, главный факт или число, следствие, если оно есть в тексте.
- Рязанские новости называй место конкретно: улица, район, маршрут. Иначе непонятно, кого это касается.
- Источники государственные и корпоративные. Передавай событие, а не оценки источника: не копируй абзацы и авторские формулировки, пересказывай своими словами.
- Только факты из `text` или `snippet`. Текста дано до 1200 символов — этого достаточно на абзац, досочинять нельзя.
- Дубли: внутри запуска оставь более полную запись, остальные — `skip` с причиной «дубль <id>». Против уже опубликованного — список из `recent --news site/data/world.json`, причина «дубль опубликованной <id>». Одно событие приходит из Лента.ру, РИА, РБК и Коммерсанта сразу, поэтому проверяй дубли внимательно.
- Заметки хранятся 2 суток, поэтому в раздел попадает только свежее.
```

- [ ] **Step 6: Правка шагов 5, 6 и 7**

В шаге 5 заменить описание запоминаемой строки:

```markdown
5. **Слияние.** `uv run python -m izolenta merge --state-dir "$WORK/state"`. Запомни первую строку вывода (`merged=... | news total=... | posts: merged=... | total=... | hn: merged=... | total=... | habr: merged=... | total=... | world: merged=... | total=...`).
```

В шаге 6 заменить перечень разрешённых изменений:

```markdown
6. **Не трогай ничего, кроме данных.** `git status --porcelain` в `iizolenta` должен показывать изменения только в `site/data/news.json`, `site/data/posts.json`, `site/data/hn.json`, `site/data/habr.json`, `site/data/world.json` и `site/data/status.json`, а `git -C "$WORK" status --porcelain` — только в `state/`. Лишние изменения откати (`git checkout -- <файл>` в соответствующем репозитории).
```

В шаге 7 заменить вводное предложение и обе команды публикации:

```markdown
7. **Публикация — сначала сайт, потом состояние.** Рабочие копии могут быть в состоянии detached HEAD — это нормально. Числа `<merged>`, `<posts>`, `<hn>`, `<habr>` и `<world>` — первое `merged=`, `merged=` после `posts:`, после `hn:`, после `habr:` и после `world:` из строки `merge`; время подставляет `date`.
   ```
   git add site/data/news.json site/data/posts.json site/data/hn.json site/data/habr.json site/data/world.json site/data/status.json
   git commit -m "news: +<merged> posts: +<posts> hn: +<hn> habr: +<habr> world: +<world> ($(date -u '+%Y-%m-%d %H:%M'))"
   git pull --rebase origin main
   git push origin HEAD:main

   git -C "$WORK" add -A state
   git -C "$WORK" commit -m "summaries: +<merged> posts: +<posts> hn: +<hn> habr: +<habr> world: +<world> ($(date -u '+%Y-%m-%d %H:%M'))"
   git -C "$WORK" pull --rebase origin main
   git -C "$WORK" push origin HEAD:main
   ```
```

- [ ] **Step 7: Запустить тест промпта**

Run: `uv run pytest tests/test_prompt.py -v`
Ожидание: PASS всех пяти тестов.

- [ ] **Step 8: Обновить README**

Заменить конец первого абзаца. Было:

```markdown
и блоком «Пишут на Хабре» с пересказами авторских статей из хабов «ИИ» и «ML».
```

Стало:

```markdown
и блоком «Пишут на Хабре» с пересказами авторских статей из хабов «ИИ» и «ML». Последний раздел — «Новости»: сжатые заметки об общей повестке (мир, Россия, Рязань, наука, культура) без криминала, происшествий, заявлений чиновников и кликбейта.
```

В схеме конвейера заменить строку с файлами данных:

```
          site/data/news.json, posts.json, hn.json, habr.json, world.json, status.json --> git push --> GitHub Pages
```

В разделе «Как расширять» после абзаца «Новый источник» добавить:

```markdown
- **Новый источник общих новостей:** добавить `[[feeds]]` с `kind = "world"` и без `default_category` — его заметки пойдут в раздел «Новости» (не больше `max_world_per_run` за запуск, текста модели передаётся `world_text_limit` символов). Лент с `kind = "world"` должно быть не больше 12: лимит делится между ними по кругу, и при большем числе события начинают теряться. Правила отбора — в `routine/PROMPT.md`, раздел «Новости»; обоснование — в `docs/plans/epic-6-world-news.md`.
```

В разделе «Что может сломать конвейер» дописать пункт:

```markdown
- низкий выход источников раздела «Новости» — Лента.ру, РИА и YA62 почти целиком состоят из заявлений и кликбейта; смотреть таблицу «Источники» на `#/status` и удалять ленты, у которых пропусков намного больше, чем публикаций.
```

- [ ] **Step 9: Прогнать все тесты и закоммитить**

```bash
uv run pytest -q
node --test "tests/js/*.test.mjs"
git add routine/PROMPT.md README.md tests/test_prompt.py
git commit -m "$(printf 'docs: add the world news rules to the routine prompt\n\nThe three-check test, the topic list, the skip list and the style rules,\nplus the world entries in the summaries format and the publish step. A\nnew test pins the prompt numbers to the schema constants.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 7: Живая проверка и выкатка

**Files:**
- Modify: `docs/plans/epic-6-world-news.md` (отметки в критериях приёмки, раздел Result)
- Никаких правок кода, кроме исправлений по результатам проверки.

**Interfaces:**
- Consumes: всё из задач 1–6.
- Produces: ветка `epic-6-world-news`, слитая в `main`; раздел «Новости», наполненный живыми данными.

- [ ] **Step 1: Проверить сбор на живых лентах**

```bash
rm -rf /tmp/live && mkdir -p /tmp/live
uv run python -m izolenta collect --state-dir /tmp/live
uv run python -c "
import json
data = json.load(open('/tmp/live/pending.json', encoding='utf-8'))
world = data['world']
print('world:', len(world))
for w in world:
    print(w['source'], '|', w['text_source'], '|', len(w['text'] or ''), '|', w['title'][:70])
print('errors:', data['errors'])
"
```

Ожидание: `world` непустой, не больше 25 записей; у каждой записи `source` из списка лент, `text_source` равен `article` или `snippet`, длина текста не больше 1200; в `errors` нет лент раздела «Новости» либо есть и это повод их заменить. Если какая-то лента в `errors` — записать это в раздел Result эпика и решить, удалять ли её.

- [ ] **Step 2: Проверить, что ленты не мешают друг другу**

```bash
uv run python -c "
import json
data = json.load(open('/tmp/live/pending.json', encoding='utf-8'))
ids = [w['id'] for w in data['world']]
urls = [w['url'] for w in data['world']]
print('дубли id:', len(ids) - len(set(ids)))
print('дубли url:', len(urls) - len(set(urls)))
print('по источникам:', {s['name']: s['selected'] for s in data['stats']['sources'] if s['selected']})
"
```

Ожидание: дублей нет; в разбивке по источникам видно, что лимит разошёлся по лентам, а не ушёл одной.

- [ ] **Step 3: Прогнать все тесты**

```bash
uv run pytest -q
node --test "tests/js/*.test.mjs"
```

Ожидание: всё зелёное. Записать числа пройденных тестов — они пойдут в раздел Result эпика.

- [ ] **Step 4: Слить ветку в `main`**

```bash
git checkout main
git pull --rebase origin main
git merge --no-ff epic-6-world-news
git push origin main
```

Ожидание: слияние без конфликтов. `world.json` на `main` новый, а коммиты routine меняют только существующие файлы данных, поэтому конфликтов быть не должно. Если конфликт всё же возник — `git merge --abort`, обновить ветку от `main` и повторить.

- [ ] **Step 5: Дождаться зелёных CI и деплоя**

```bash
gh run list -R dumka/iizolenta --limit 5
```

Ожидание: workflow `Tests` и `Deploy site to GitHub Pages` зелёные. Открыть https://dumka.github.io/iizolenta/#/world — страница «Новости» с состоянием «Пока тихо», пункт меню на месте.

- [ ] **Step 6: Запустить сбор и routine вручную**

```bash
gh workflow run collect.yml -R dumka/iizolenta-work
gh run list -R dumka/iizolenta-work --limit 3
```

Затем нажать «Run now» на странице routine либо выполнить `/schedule run` в Claude Code. Дождаться завершения и прочитать итоговое сообщение запуска.

Ожидание: в строке `merge` есть ` | world: merged=N`, где N больше нуля; в списке пропусков у общих новостей предметные причины.

- [ ] **Step 7: Проверить результат против требования R4**

Открыть https://dumka.github.io/iizolenta/#/world и прочитать все заметки. Открыть https://dumka.github.io/iizolenta/#/status, выбрать фильтр «Пропущено».

Ожидание:

1. На странице нет ни одной заметки из запрещённых категорий R4: военных сводок, заявлений без решения, частных происшествий, сводок цен, криминала, шоу-бизнеса, советов, рекламы, кликбейта.
2. Одно событие опубликовано один раз, хотя пришло из нескольких источников.
3. Причины пропусков предметные: «заявление без решения», «частное происшествие», а не «неинтересно».
4. Рязанские заметки называют конкретное место.

Если пункт 1 нарушен — выписать, какие именно категории прошли, и уточнить формулировки в разделе «Новости» файла `routine/PROMPT.md`, затем повторить шаг 6. Это ожидаемая итерация: спецификация прямо называет её риском.

- [ ] **Step 8: Через сутки оценить выход источников**

Открыть https://dumka.github.io/iizolenta/#/status, таблица «Источники».

Ожидание: для каждой ленты раздела видно «Опубл.» и «Пропущ.». Для лент, где пропусков в разы больше, чем публикаций, принять решение: оставить или удалить строку из `feeds.toml`. Записать решение в раздел Result эпика.

- [ ] **Step 9: Закрыть эпик**

Отметить выполненные пункты в `docs/plans/epic-6-world-news.md`, сменить статус на `закрыт` с датой и дописать раздел `## Result (дата)` с числами: сколько лент работает, сколько заметок собрано и опубликовано за первый запуск, числа пройденных тестов, какие формулировки промпта уточнялись, какие ленты удалены.

```bash
git add docs/plans/epic-6-world-news.md
git commit -m "$(printf 'docs: close epic 6, the «Новости» section is live\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
git push origin main
```
