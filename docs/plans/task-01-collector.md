# Task 1: Каркас проекта и сборщик лент (`izolenta collect`)

Epic: `docs/plans/epic-izolenta.md` · Статус: closed (2026-10-08) · Оценка: 5-6 часов · Зависимости: нет (первая задача)

## Goal

Команда `uv run python -m izolenta collect` скачивает ленты из `feeds.toml`, отбрасывает уже виденное и слишком старое, извлекает текст новых статей и пишет `state/pending.json`: не больше `max_items_per_run` записей, готовых к выжимке. Укладывается в 2 минуты даже при недоступных источниках.

## Implementation

1. Каркас
   - `pyproject.toml` (uv, Python >= 3.12): зависимости `feedparser`, `httpx`, `trafilatura`; dev — `pytest`.
   - `.gitignore`: `.venv/`, `__pycache__/`, `.pytest_cache/`, `state/pending.json`, `state/summaries.json`.
   - `izolenta/__init__.py`, `izolenta/__main__.py`: argparse, подкоманда `collect` с опциями `--config feeds.toml --state-dir state`. Код выхода 0 при успехе (даже если часть лент упала), 2 при фатальной ошибке (битый конфиг или `seen.json`).

2. Конфиг: `feeds.toml` + `izolenta/config.py`
   - `[settings]`: `max_items_per_run = 15`, `max_age_hours = 48`, `article_text_limit = 8000`, `http_timeout = 15`, `max_response_bytes = 5_000_000`, `seen_retention_days = 14`, `fetch_workers = 8`, `user_agent`.
   - `[[feeds]]`: `name`, `url`, `default_category` (`ai|dev|business`; подсказка для Claude).
   - `load_config(path) -> Config` (frozen dataclass). `ConfigError`, если список лент пуст, категория не из трёх, URL не http(s), имена лент повторяются.
   - Стартовые ленты: TechCrunch AI, TechCrunch Startups, The Verge AI, MIT Technology Review AI, Ars Technica AI, Wired AI, VentureBeat AI, Simon Willison, GitHub Blog, The New Stack, Google AI Blog, Hugging Face Blog, OpenAI News, Hacker News (`https://hnrss.org/frontpage?points=150`).

3. Ленты: `izolenta/feeds.py`
   - `canonical_url(url) -> str` через `urllib.parse` (без regex): схема `https`, хост в нижнем регистре без `www.`, убрать параметры `utm_*`, `fbclid`, `gclid`, `ref`, `ref_src`, отсортировать оставшиеся, убрать фрагмент и хвостовой `/` (кроме корня).
   - `item_id(url) = sha1(canonical_url(url)).hexdigest()[:16]`.
   - `parse_feed(name, raw: bytes, default_category, now) -> list[FeedItem]`:
     - `title`: HTML-теги убрать, сущности раскодировать, пробелы схлопнуть; пустой — запись пропустить.
     - `url`: из `link`; не абсолютный http(s) — запись пропустить.
     - `snippet`: summary/description без HTML, не длиннее 1000 символов.
     - `published_at`: из `published_parsed` / `updated_parsed` (UTC). Нет даты — `now`. Дата в будущем — обрезать до `now`.
     - `image`: `media:content` / `media:thumbnail` / `enclosure` с `type=image/*`; только http(s), иначе `None`.
     - `bozo` при наличии записей — не ошибка; 0 записей — `FeedError`.
   - `FeedItem` — dataclass: `id, url, source, title, snippet, published_at (datetime UTC), image, default_category`.

4. Сеть: `izolenta/http.py`
   - `make_fetcher(config) -> Callable[[str], bytes]`: httpx.Client с таймаутом, User-Agent, `follow_redirects=True`. Статус не 2xx — `FetchError`. Ответ читается потоком; больше `max_response_bytes` — `FetchError`.

5. Текст статьи: `izolenta/extract.py`
   - `extract_text(html: bytes) -> str | None` через `trafilatura.extract(..., include_comments=False)`. Результат короче 200 символов считается неудачей.
   - `truncate_paragraphs(text, limit) -> str`: целые абзацы, пока влезают; если первый абзац длиннее лимита — жёсткая обрезка до `limit` символов + `...`.
   - `article_text(item, fetch, limit) -> (text, text_source)`: при любой ошибке или пустом результате вернуть `(snippet или title, "snippet")`, иначе `(text, "article")`.

6. Состояние: `izolenta/state.py`
   - `seen.json`: `{"<id>": {"first_seen": iso, "status": "pending|done|skipped|failed", "attempts": int}}`.
   - `load_seen(path)`: нет файла — `{}`; битый JSON или не dict — `StateError` (фатально, код 2: молча начать с нуля значит заново прогнать уже обработанное и сжечь лимиты).
   - `save_json_atomic(path, data)`: UTF-8, `ensure_ascii=False`, temp-файл в той же папке, `os.replace`.
   - `prune_seen(seen, now, days)`: удалить записи с `first_seen` старше `days`.

7. Отбор: `izolenta/collect.py`
   - `collect(config, state_dir, fetch, now) -> CollectResult`.
   - Ленты качаются параллельно (`ThreadPoolExecutor(fetch_workers)`); ошибка одной ленты пишется в `errors` (`{"feed": name, "error": str}`) и не прерывает остальные.
   - Фильтры по порядку: дубликаты id внутри запуска (оставить первый по порядку лент в конфиге); id со статусом `done`/`skipped`/`failed`; `published_at` старше `max_age_hours`.
   - Round-robin: ленты в порядке конфига, внутри ленты свежие первыми; берём по одной из каждой по кругу, пока не наберём `max_items_per_run` или не кончатся кандидаты.
   - Тексты отобранных статей качаются параллельно (`article_text`).
   - `state/pending.json`: `{"generated_at": iso, "items": [...], "errors": [...]}`. Поля item: `id, url, source, title, snippet, text, text_source, published_at (iso Z), image, default_category`.
   - `seen.json`: отобранным — `status = "pending"` (если записи нет, `first_seen = now`, `attempts = 0`; существующие `attempts` не трогать), затем `prune_seen`, затем атомарная запись.
   - stdout: `feeds ok=12 failed=2 | candidates=57 | selected=15 (article=11, snippet=4)`.

## Key Considerations (SRE review)

- **Время выполнения.** Routine ждёт bash-команду 2 минуты (максимум 10). Последовательно 14 лент + 15 статей по 15 с — до 7 минут. Отсюда параллельная загрузка; худший случай около 60 с.
- **Огромные ответы.** GitHub Blog — 1,2 МБ, OpenAI — 765 КБ, бэклоги в сотни записей. Лимит размера ответа + фильтр по возрасту.
- **Недоверенные данные.** Ссылки и картинки потом попадут в `href`/`src` дашборда: только http(s), иначе `javascript:` станет XSS.
- **Битый `seen.json`** — фатальная ошибка, а не пустое состояние.
- **Битый XML.** feedparser часто выставляет `bozo`, но отдаёт записи; ошибка только если записей нет.
- **HTML вместо ленты** (капча, заглушка, 200 OK) — 0 записей — `FeedError`.
- **Даты.** Нет даты — `now`; будущая дата — `now`; всё в UTC.
- **Дубли.** TechCrunch AI и Startups пересекаются; ссылки с `utm_` и без — одна статья.
- **Пейволл и JS-страницы.** trafilatura вернёт мало текста — фолбэк на сниппет. HN-ссылки ведут на произвольные домены; в окружении Custom их скачивание даст 403 — тоже сниппет.
- **Юникод.** Ёлочки, эмодзи и CJK в заголовках сохраняются; JSON пишется с `ensure_ascii=False`.
- **Конкурентность.** Два запуска одновременно не ожидаются (интервал час, работа около минуты); блокировки не делаем.

## Anti-patterns (для этой задачи)

- НЕТ сетевых запросов в тестах: `fetch` внедряется, тесты используют фикстуры и фейковый fetcher.
- НЕТ `except Exception: pass` — каждая пойманная ошибка попадает в `errors` или в `text_source = "snippet"`.
- НЕТ частичной записи JSON — только атомарная.
- НЕТ regex для разбора URL — только `urllib.parse`.
- НЕТ TODO и заглушек в коде.

## Tests (TDD, `uv run pytest`)

Фикстуры в `tests/fixtures/`: `rss_basic.xml` (3 записи: с `media:content`, с `enclosure` image, без картинки), `atom_basic.xml` (2 записи, одна без даты), `rss_bozo.xml` (незакрытый тег, но записи есть), `not_a_feed.html`, `article.html` (статья из нескольких абзацев), `article_paywall.html` (почти без текста).

`tests/test_feeds.py`:
- `test_canonical_url_strips_tracking_params_and_fragment`
- `test_canonical_url_same_id_for_http_https_www_and_trailing_slash`
- `test_canonical_url_keeps_meaningful_query_params` (ловит потерю `?id=123`)
- `test_parse_rss_extracts_fields_and_images`
- `test_parse_atom_entry_without_date_gets_now`
- `test_future_date_is_clamped_to_now`
- `test_entry_without_link_or_title_is_skipped`
- `test_javascript_link_and_image_are_rejected`
- `test_html_in_title_and_snippet_is_stripped_and_unescaped`
- `test_bozo_feed_with_entries_is_parsed`
- `test_html_page_instead_of_feed_raises_feed_error`

`tests/test_extract.py`:
- `test_article_text_extracted_from_html`
- `test_paywall_page_falls_back_to_snippet`
- `test_fetch_error_falls_back_to_snippet`
- `test_truncate_keeps_whole_paragraphs_under_limit`
- `test_truncate_hard_cuts_single_long_paragraph`

`tests/test_state.py`:
- `test_missing_seen_file_is_empty_state`
- `test_corrupted_seen_file_raises_state_error`
- `test_prune_removes_only_old_entries`
- `test_atomic_write_preserves_unicode`

`tests/test_collect.py` (фейковый fetcher: словарь URL -> bytes или исключение):
- `test_done_skipped_failed_items_are_not_selected`
- `test_pending_item_from_crashed_run_is_selected_again`
- `test_items_older_than_max_age_are_dropped`
- `test_duplicate_article_across_feeds_selected_once`
- `test_round_robin_prevents_one_feed_taking_whole_limit` (лента A: 20 записей, лента B: 2; в выборке из 5 обе записи B)
- `test_failing_feed_recorded_in_errors_others_processed`
- `test_selected_items_marked_pending_and_attempts_preserved`
- `test_pending_json_matches_item_schema`

`tests/test_config.py`:
- `test_invalid_category_rejected`
- `test_empty_feed_list_rejected`
- `test_duplicate_feed_names_rejected`

## Success Criteria

- [ ] `uv run pytest`: все перечисленные тесты существуют и зелёные (не меньше 31).
- [ ] `uv run python -m izolenta collect` на реальной сети меньше чем за 120 с создаёт `state/pending.json` с 1..15 записями; у каждой непустые `id, url, title, text, published_at`, `text_source` из `article|snippet`.
- [ ] Не меньше половины отобранных записей реальных лент имеют `text_source = "article"` (извлечение работает, а не всё уходит в фолбэк).
- [ ] Недоступная отсюда лента (VentureBeat / hnrss) попадает в `errors`, код выхода 0.
- [ ] Битый `state/seen.json`: код выхода 2 и понятное сообщение в stderr; файл не перезаписан.
- [ ] `grep -rn "TODO" izolenta/` пусто; голых `except Exception: pass` нет.

## Result (2026-10-08)

- 54 теста (pytest) зелёные.
- Реальный прогон: `feeds ok=11 failed=3 | candidates=95 | selected=15 (article=13, snippet=2)`, 32 с.
- Отсюда недоступны Ars Technica (таймаут), VentureBeat (таймаут), hnrss (DNS) — вероятно, региональная блокировка; проверить из облачного окружения routine.
- Отклонение от плана: `make_fetcher(timeout, user_agent, max_bytes, transport=None)` принимает параметры, а не `Config`, чтобы в тестах подставлять `httpx.MockTransport`.
