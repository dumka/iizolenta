# Task 2: Валидация выжимок и слияние в `news.json` (`izolenta merge`)

Epic: `docs/plans/epic-izolenta.md` · Статус: open (SRE review: approved) · Оценка: 4-5 часов · Зависит от: Task 1 (closed)

## Goal

Команда `uv run python -m izolenta merge` берёт `state/pending.json` (от `collect`) и `state/summaries.json` (пишет Claude в routine), проверяет каждую выжимку, вливает валидные в `site/data/news.json`, удаляет новости старше 7 дней и обновляет `state/seen.json`. Невалидная выжимка никогда не попадает на сайт.

## Context (из Task 1)

- `pending.json`: `{"generated_at", "items": [{id, url, source, title, snippet, text, text_source, published_at, image, default_category}], "errors"}`.
- `seen.json`: `{id: {first_seen, status: pending|done|skipped|failed, attempts}}`; `collect` повторно отбирает только `pending`.
- Для части статей (OpenAI, Wired) есть только сниппет, `text_source = "snippet"`. Из такого текста 3-5 абзацев не написать без выдумок, поэтому routine должна их пропускать (`skip`), а merge строго требует 3-5 абзацев.

## Implementation

1. Формат `state/summaries.json` (контракт с Claude; копия попадёт в `routine/PROMPT.md` в Task 4):
   ```json
   {"items": [
     {"id": "<id из pending>", "status": "ok", "category": "ai|dev|business", "importance": 1,
      "title": "Русский заголовок", "lead": "1-2 предложения", "body": ["абзац", "абзац", "абзац"]},
     {"id": "<id>", "status": "skip", "reason": "не про AI/IT"}
   ]}
   ```

2. `izolenta/schema.py`
   - `validate_summary(raw: dict) -> Summary | Skip` или `ValidationError` со списком причин.
   - Правила для `ok`: `category` из `CATEGORIES`; `importance` — int 1..3 (3 — главная новость); `title`: после strip от 10 до 200 символов; `lead`: от 20 до 400; `body`: список из 3-5 строк, каждая после strip от 40 до 1500 символов; в `title`, `lead` и каждом абзаце есть кириллица (ловит забытый перевод); в текстах нет `<` и `>` (HTML не принимаем, дашборд выводит только текст).
   - Правила для `skip`: `reason` — непустая строка не длиннее 300 символов.
   - Неизвестный `status` или нестроковый `id` — ошибка.
   - Строки нормализуются: strip, схлопнуть пробелы внутри (переносы в абзаце убрать).

3. `izolenta/merge.py`: `merge(state_dir, news_path, now, retention_days=7, max_attempts=3) -> MergeResult`
   - Нет `pending.json` — ничего не делать, вернуть результат с `nothing_to_merge = True` (код выхода 0).
   - Битый `pending.json`, `seen.json` или `news.json` — `StateError` (код 2). `news.json` при этом не перезаписывается.
   - Нет `summaries.json` или он битый — у всех pending считается неудачная попытка (`attempts + 1`), причина в отчёте.
   - Для каждого item из pending:
     - валидная `ok` → запись в news; seen: `done`, `attempts + 1`;
     - валидная `skip` → seen: `skipped`, `attempts + 1`;
     - нет выжимки или невалидная → `attempts + 1`; если `attempts >= max_attempts` → `failed`, иначе остаётся `pending`.
   - Выжимки с id не из pending игнорируются и попадают в отчёт (`unknown_ids`). Дубликаты id в summaries — берётся первая, остальные в отчёт.
   - Запись в news: `id, url, source, published_at, category, importance, title, lead, body, image` (url, source, published_at, image — из pending, а не от Claude, чтобы Claude не мог подменить ссылку).
   - Если id уже есть в news — запись заменяется.
   - Удалить из news записи с `published_at` старше `now - retention_days`.
   - Сортировка news по `published_at` по убыванию, затем по id (стабильный порядок для diff).
   - Запись `site/data/news.json`: `{"generated_at": iso_z(now), "items": [...]}` атомарно; затем `seen.json` атомарно; затем удалить `pending.json` и `summaries.json` (иначе следующий запуск может повторно влить старые выжимки).
   - stdout: `merged=9 skipped=4 invalid=1 missing=1 failed=0 | news total=87`; затем по строке на каждую невалидную выжимку с причинами.

4. CLI: подкоманда `merge` в `izolenta/__main__.py` (`--state-dir state --news site/data/news.json`), коды выхода как у `collect`.

## Key Considerations (SRE review)

- **Сайт не должен сломаться.** Одна битая запись ломает рендер, поэтому валидируется каждая запись, а при битом `news.json` merge падает, а не пишет пустой файл.
- **Подмена ссылок.** URL, источник, дата и картинка берутся из pending (уже проверены как http(s) в Task 1), а не из ответа Claude.
- **Бесконечные повторы.** `max_attempts = 3` (anti-pattern эпика).
- **Повторное слияние.** Рабочие файлы удаляются после успешного merge.
- **Забытый перевод.** Проверка кириллицы в каждом текстовом поле.
- **Выдумки на сниппетах.** Строгие 3-5 абзацев по 40+ символов; инструкция «skip, если текста мало» — в промпте (Task 4).
- **Юникод.** Ёлочки, тире, эмодзи сохраняются, JSON с `ensure_ascii=False`.
- **Формат ответа Claude.** `summaries.json` читается как `utf-8-sig` (BOM допустим); верхний уровень — либо `{"items": [...]}`, либо просто список. Обёртка в markdown-блок не принимается (это ошибка, попытка засчитывается).
- **Нет записи в seen.** Для id из pending без записи в `seen.json` (ручная правка состояния) запись создаётся через `setdefault`, без KeyError.
- **Стабильные диффы.** Детерминированная сортировка и `indent=2`, чтобы коммиты routine были читаемыми.

## Anti-patterns (для этой задачи)

- НЕТ записи невалидных или частично валидных записей в `news.json`.
- НЕТ доверия `url`/`source`/`image` из summaries.
- НЕТ перезаписи `news.json` пустым содержимым при ошибке чтения.
- НЕТ TODO и заглушек.

## Tests (TDD)

`tests/test_schema.py`:
- `test_valid_ok_summary_accepted_and_normalized` (лишние пробелы и переносы схлопнуты)
- `test_valid_skip_accepted`
- `test_unknown_category_rejected`
- `test_importance_out_of_range_or_not_int_rejected` (0, 4, "2", true)
- `test_body_with_2_or_6_paragraphs_rejected`
- `test_short_paragraph_rejected`
- `test_untranslated_english_title_rejected`
- `test_html_in_text_rejected`
- `test_empty_skip_reason_rejected`
- `test_unknown_status_rejected`
- `test_all_errors_reported_together` (несколько нарушений — все в списке причин)

`tests/test_merge.py`:
- `test_valid_summary_added_to_news_with_pending_metadata` (url/source/image из pending, даже если Claude прислал другие)
- `test_skip_marks_seen_skipped_and_not_in_news`
- `test_invalid_summary_not_in_news_and_attempt_counted`
- `test_third_failed_attempt_marks_failed`
- `test_missing_summary_counts_attempt`
- `test_missing_summaries_file_counts_attempt_for_all`
- `test_unknown_and_duplicate_ids_reported_and_ignored`
- `test_existing_news_preserved_and_same_id_replaced`
- `test_news_older_than_retention_pruned`
- `test_news_sorted_newest_first`
- `test_no_pending_file_is_noop`
- `test_corrupted_news_json_aborts_without_overwrite`
- `test_work_files_removed_after_merge`
- `test_summaries_with_bom_and_bare_list_accepted`
- `test_pending_id_without_seen_entry_does_not_crash`

`tests/test_cli.py`: `test_merge_corrupted_news_exits_2`.

## Success Criteria

- [ ] `uv run pytest` зелёный; все перечисленные тесты существуют (не меньше 27 новых).
- [ ] Ручной прогон: `collect` → вручную написанный `summaries.json` на 2 записи (одна `ok`, одна `skip`) → `merge` → в `site/data/news.json` ровно одна новость с url из pending, в `seen.json` статусы `done` и `skipped`.
- [ ] Повторный `collect` после этого не отбирает эти две статьи.
- [ ] Битый `site/data/news.json`: код выхода 2, файл не изменён.
- [ ] `grep -rn "TODO" izolenta/` пусто.
