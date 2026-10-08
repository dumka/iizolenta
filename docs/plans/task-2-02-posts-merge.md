# Task 2.2: Переводы постов — схема, check, merge в `posts.json`, инструкция routine

Epic: `docs/plans/epic-x-posts.md` · Статус: closed (2026-10-08) · Оценка: 4 часа · Ветка: `x-posts` · Зависит от: Task 2.1 (closed)

## Goal

Routine пишет для постов из `pending.json["posts"]` записи в `summaries.json["posts"]`; `izolenta check` их проверяет, `izolenta merge` вливает валидные в `site/data/posts.json` (хранение 3 дня) и обновляет `seen.json`. `routine/PROMPT.md` объясняет, как переводить и что пропускать. Контракт `news.json` не меняется.

## Context

- `pending.json` (Task 2.1): `{"generated_at", "items", "posts", "errors"}`; пост: `{id: "x:<status>", url, author_handle, author_name, published_at, text, quote: {author_handle, author_name, text} | null, lang}`.
- `merge` сейчас читает только `items`; `check` — тоже. Посты, которые никто не обработал, остаются `pending` и отбираются снова (попытки не растут) — Task 2.2 это закрывает.
- `summaries.json` сейчас — `{"items": [...]}` или голый список статей.

## Implementation

1. **Формат `summaries.json`**: объект `{"items": [...], "posts": [...]}`. Голый список по-прежнему означает только статьи (обратная совместимость). Запись поста: `{"id": "x:123", "status": "ok", "text": "Русский перевод"}` или `{"id": "x:123", "status": "skip", "reason": "..."}`.
2. **Схема** (`izolenta/schema.py`): `validate_post(raw) -> PostSummary | Skip`. `ok`: `text` — после нормализации пробелов внутри строк 20-600 символов, есть кириллица, нет `<`/`>`; переносы абзацев (`\n\n`) сохраняются (до 3 абзацев). `skip`: как у статей. id обязан начинаться с `x:`.
3. **check** (`izolenta/merge.py`): те же проверки для `posts` — missing/invalid/unknown/duplicate с префиксом `post` в тексте проблемы.
4. **merge**:
   - посты обрабатываются как статьи: `ok` → запись в `posts.json`, `done`; `skip` → `skipped`; нет/невалидно → попытка, после 3 — `failed`;
   - запись `posts.json`: `{id, url, author_handle, author_name, published_at, text}` — всё, кроме `text`, из pending;
   - хранение `POST_RETENTION_DAYS = 3`, сортировка от новых к старым, затем по id;
   - `site/data/posts.json`: `{"generated_at", "items": [...]}`; путь — опция CLI `--posts site/data/posts.json`;
   - битый `posts.json` — `StateError`, ничего не перезаписывается (как с `news.json`);
   - сводка: `... | posts: merged=6 skipped=4 invalid=0 missing=0 failed=0 | total=18`.
5. **`routine/PROMPT.md`**:
   - шаг 3: работы нет, только если пусты и `items`, и `posts`;
   - шаг 4: писать и `items`, и `posts`;
   - шаг 7-8: в коммит добавляется `site/data/posts.json`; сообщение `news: +<merged> posts: +<merged posts> (...)`;
   - раздел «Посты из X»: что пропускать (ответы и репосты уже отсеяны скриптом; пропускать личное, бытовое, политику без связи с IT, рекламу, шутки без смысла вне контекста, посты из одной ссылки или одного слова); как переводить (смысловой перевод, сохранять тон автора и первое лицо, без «Автор пишет, что» в начале; для цитаты — кратко, что цитируется, если иначе непонятно; ссылки не вставлять — ссылка на пост добавится сама; термины и названия моделей латиницей; до 600 символов, длинные посты — сжатый пересказ главного).

## Key Considerations (SRE review)

- **Совместимость в переходный период.** До слияния ветки в `main` production-routine работает со старым кодом и промптом; после слияния — с новыми. `summaries.json` старого формата (голый список) продолжает работать.
- **Посты без перевода.** Если routine проигнорирует `posts`, каждый пост получит попытку и через 3 запуска станет `failed` — бесконечного накопления нет.
- **Подмена ссылки.** `url` поста строится в Task 2.1 из handle и числового id; в merge берётся из pending, а не от Claude.
- **Размер `posts.json`.** 10 постов в час × 3 дня ≈ 720 записей по ~0,6 КБ ≈ 0,4 МБ — допустимо.
- **Абзацы.** У статей пробелы схлопываются полностью; у постов нужно сохранить `\n\n`, иначе длинный пересказ станет сплошным текстом.

## Anti-patterns

- НЕТ изменений схемы и валидации записей `news.json`.
- НЕТ ссылок и HTML в тексте поста (только текст; ссылка — отдельное поле из pending).
- НЕТ пушей в `main`.

## Tests (TDD)

`tests/test_schema.py`: `test_valid_post_ok_keeps_paragraphs`, `test_post_too_long_or_untranslated_rejected`, `test_post_id_without_x_prefix_rejected`, `test_post_skip_accepted`.
`tests/test_merge.py`: `test_post_merged_into_posts_json_with_pending_metadata`, `test_post_skip_and_invalid_attempts`, `test_posts_older_than_3_days_pruned`, `test_bare_list_summaries_still_merge_articles_only`, `test_corrupted_posts_json_aborts_without_overwrite`, `test_missing_posts_summaries_count_attempts`.
`tests/test_check.py`: `test_check_reports_post_problems`.

## Success Criteria

- [ ] Новые тесты есть и зелёные; весь `pytest` и `node --test` зелёные.
- [ ] Ручной прогон: `collect` → `summaries.json` с 2 статьями и 2 постами (ok + skip каждого) → `check` = 0 → `merge`: `posts.json` с 1 постом, ссылка из pending; `news.json` с 1 новостью.
- [ ] `PROMPT.md` описывает посты; пробный прогон по нему (Claude в этой сессии) даёт `check` = 0.
- [ ] Всё в ветке `x-posts`; `main` не тронут.

## Result (2026-10-08)

- `uv run pytest`: 152 passed (новые: 4 группы в `test_schema.py`, 7 в `test_merge.py`, 1 в `test_check.py`, 1 в `test_cli.py`). Старые тесты merge/check прошли без изменений — обратная совместимость сохранена.
- `merge.py` переписан на общий обработчик видов контента (`Kind`: статьи и посты) — без дублирования логики попыток, пропусков и проверок; `MergeResult.news_total` оставлен свойством для совместимости.
- `PROMPT.md`: шаги 3-8 учитывают посты, новый раздел «Посты из X» (что пропускать, как переводить), раздел «Безопасность» распространён на посты.
- Пробный прогон по `PROMPT.md` во временной папке (2 статьи, 10 постов): выжимки и переводы писал Claude в этой сессии; `check` — код 0 с первой попытки; `merge`: `merged=1 skipped=1 ... | posts: merged=7 skipped=3 invalid=0 missing=0 failed=0 | total=7`; ссылки постов — из pending. Пропущены: пост со ссылкой без смысла без неё, фрагментарный пост, личный пост.
- Данные пробного прогона в репозиторий не попали (ветка не должна менять `news.json`/`seen.json`, иначе конфликт с коммитами routine в `main`).
