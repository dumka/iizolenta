# Task 2.1: Сбор постов X через FxTwitter и блоги авторов

Epic: `docs/plans/epic-x-posts.md` · Статус: closed (2026-10-08) · Оценка: 5 часов · Ветка: `x-posts` (не `main` до конца эпика — routine работает с `main`)

## Goal

`uv run python -m izolenta collect` кроме статей собирает посты 14 аккаунтов из `[[x_accounts]]` через FxTwitter API и кладёт новые в `state/pending.json` отдельным списком `posts` (не больше `max_posts_per_run`). Ответы другим людям и простые репосты отбрасываются, треды автора склеиваются в один пост. Четыре блога авторов добавлены как обычные ленты.

## Context

- Формат FxTwitter (проверено 2026-10-08 на ответе для @karpathy): `GET https://api.fxtwitter.com/2/profile/<handle>/statuses?count=20` → `{"code": 200, "results": [status, ...]}`. Поля status: `id`, `url`, `text`, `author.screen_name`, `author.name`, `created_timestamp` (unix), `replying_to` (`null` или `{"screen_name", "status"}`), `reposted_by` (`null` или объект — простой репост), `quote` (`null`/нет или вложенный status), `is_note_tweet`, `lang`. Курсора в ответе нет. При параметре `since` и отсутствии новых постов — 204 без тела.
- У @bcherny треды — ответы самому себе (`replying_to.screen_name == "bcherny"`).
- Отсюда (локальная сеть) `api.fxtwitter.com` отвечает медленно и обрывает ответы — сеть тестов не нужна (фикстуры), реальный прогон — из облака.
- `pending.json` сейчас: `{"generated_at", "items", "errors"}`; `merge`/`check` читают только `items` — новый ключ `posts` им не мешает (но обрабатывать их начнёт Task 2.2).

## Implementation

1. **Конфиг** (`feeds.toml`, `izolenta/config.py`)
   - `[settings]`: `max_posts_per_run = 10`, `post_max_age_hours = 48`.
   - `[[x_accounts]]`: `handle` — 14 аккаунтов из R4 эпика 2.
   - `XAccount(handle)`; `ConfigError` для handle не по `^[A-Za-z0-9_]{1,15}$` и для дубликатов (без учёта регистра). Секция необязательна: без неё посты не собираются.
   - Ленты блогов (R8): Andrej Karpathy (`https://karpathy.bearblog.dev/feed/`, ai), Boris Cherny (`https://borischerny.com/feed.xml`, dev), One Useful Thing (`https://www.oneusefulthing.org/feed`, ai), The Batch (`https://charonhub.deeplearning.ai/rss/`, ai).

2. **Разбор** (`izolenta/xposts.py`)
   - `XPost` (dataclass): `id` (`"x:" + status id` — не пересекается с id статей), `status_id`, `url` (`https://x.com/<handle>/status/<id>`), `author_handle`, `author_name`, `published_at` (UTC из `created_timestamp`, будущее — `now`), `text`, `quote` (`{"author_handle", "author_name", "text"}` или `None`), `lang`.
   - `parse_statuses(handle, raw: bytes, now) -> list[XPost]`:
     - пустое тело (204) → `[]`; не JSON, `code != 200`, нет списка `results` → `XError`;
     - пропустить: `type != "status"`, `reposted_by` не `null`, автор не равен `handle` (без учёта регистра), `replying_to` на другого пользователя, пустой `text`;
     - продолжение треда (`replying_to.screen_name == handle`): если родитель (по цепочке) есть в выдаче — текст дописывается к корню через пустую строку в порядке времени; если корня в выдаче нет — пропустить;
     - `url` строится из handle и id (не берётся из ответа), только цифры в id.
   - `fetch_posts(account, fetch, now) -> list[XPost]` — URL с `count=20`.

3. **Сбор** (`izolenta/collect.py`)
   - Аккаунты опрашиваются в том же пуле, что и ленты; ошибка аккаунта → `errors` с `{"feed": "@<handle>", "error": ...}`, запуск продолжается.
   - Фильтры: id со статусом `done/skipped/failed` в `seen.json`; старше `post_max_age_hours`.
   - Порядок: round-robin по авторам (как у лент), внутри автора — свежие первыми; срез `max_posts_per_run`.
   - `pending.json` получает `"posts": [{id, url, author_handle, author_name, published_at, text, quote, lang}]`.
   - Отобранные посты помечаются в `seen.json` как `pending` (как статьи).
   - Сводка: `... | posts: accounts ok=13 failed=1 | candidates=40 | selected=10`.

## Key Considerations (SRE review)

- **Продакшн.** Routine берёт `main`; работа идёт в ветке `x-posts` и сливается в `main` только после Task 2.3 (сайт и промпт готовы) и после того, как пользователь добавил домены в allowlist окружения.
- **Треды.** Без склейки тред @bcherny распался бы на «первый пост + отброшенные ответы».
- **Репост под чужим автором.** У репоста `author` — исходный автор, а `reposted_by` — наш аккаунт; проверка автора и `reposted_by` отсекает оба случая.
- **Обрыв ответа.** Битый JSON (обрыв соединения) → `XError` для аккаунта, не падение запуска.
- **Ссылки.** `url` собирается из проверенных handle и числового id — в `href` дашборда не попадёт чужая ссылка из ответа API.
- **Длинные посты.** `is_note_tweet` — полный текст в `text`; ограничение длины текста для routine — 4000 символов (обрезка по абзацам, как у статей).
- **Пересечение id.** Префикс `x:` в id исключает совпадение с sha1-id статей в общем `seen.json`.

## Anti-patterns

- НЕТ сетевых запросов в тестах (фикстуры FxTwitter).
- НЕТ пушей в `main` в рамках этой задачи.
- НЕТ скрапинга x.com/Nitter (эпик 2).

## Tests (TDD)

Фикстура `tests/fixtures/fx_statuses.json` (по реальной структуре): корневой пост; note tweet; цитата с комментарием; ответ другому пользователю; тред из корня и двух продолжений; продолжение без корня в выдаче; репост; пост с будущей датой. Плюс `fx_error.json` (`code: 404`).

`tests/test_xposts.py`:
- `test_root_post_parsed_with_url_built_from_handle_and_id`
- `test_reply_to_other_user_dropped`
- `test_plain_repost_dropped`
- `test_self_reply_thread_glued_to_root_in_time_order`
- `test_thread_continuation_without_root_dropped`
- `test_quote_post_keeps_quoted_text`
- `test_empty_body_204_returns_no_posts`
- `test_error_code_and_broken_json_raise_x_error`
- `test_future_timestamp_clamped_to_now`
- `test_long_note_tweet_cut_by_paragraphs`

`tests/test_collect.py` (дополнения):
- `test_posts_collected_into_pending_with_cap_and_round_robin`
- `test_seen_posts_not_selected_again`
- `test_failing_account_recorded_and_articles_still_collected`
- `test_old_posts_dropped`

`tests/test_config.py`: `test_invalid_or_duplicate_handle_rejected`, `test_x_accounts_optional`.

## Success Criteria

- [ ] Все новые тесты есть и зелёные; весь `pytest` и `node --test` зелёные.
- [ ] `feeds.toml` содержит 14 аккаунтов и 4 блога; `test_project_feeds_toml_is_valid` проходит.
- [ ] Реальный прогон `collect` локально завершается с кодом 0 за меньше чем 120 с, даже если FxTwitter отсюда недоступен (ошибки аккаунтов в `errors`).
- [ ] Работа закоммичена в ветку `x-posts`; `main` не тронут.

## Result (2026-10-08)

- `uv run pytest`: 131 passed (новые: 14 в `test_xposts.py`, 4 в `test_collect.py`, 6 в `test_config.py`).
- `feeds.toml`: 16 лент (+4 блога), 14 аккаунтов X, `fetch_workers = 12`, `max_posts_per_run = 10`, `post_max_age_hours = 48`.
- Ссылки статей в блогах ведут на те же домены, что и ленты: для allowlist окружения нужны `api.fxtwitter.com`, `karpathy.bearblog.dev`, `borischerny.com`, `www.oneusefulthing.org`, `charonhub.deeplearning.ai`.
- Реальный прогон локально: 42 с; `feeds ok=15 failed=1 | ... | posts: accounts ok=8 failed=6 | candidates=21 | selected=10`. Отказы — таймауты TLS/чтения до `api.fxtwitter.com` и `borischerny.com` из локальной сети; запуск не упал. Проверить из облака в Task 2.3.
- Среди собранных постов есть нерелевантные (личные) — их отсев на стороне routine (Task 2.2, R5 эпика 2).
