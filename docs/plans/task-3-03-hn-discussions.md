# Task 3.3: «Обсуждают на HN» — сбор, схема, merge в `hn.json`, промпт

Epic: `docs/plans/epic-3-actions-hn.md` · Статус: closed (2026-10-09) · Оценка: 4-5 часов · Зависит от: Task 3.1

## Goal

`collect` (в Actions) отбирает популярные обсуждения с первой страницы HN и кладёт их в `pending.json["discussions"]` с первыми по рейтингу комментариями. Routine пишет русский заголовок и пересказ обсуждения; `check`/`merge` проверяют и вливают в `site/data/hn.json` (3 дня).

## Implementation

1. **Конфиг** (`[settings]` в `feeds.toml`, все с умолчаниями): `hn_discussions = true`, `hn_min_points = 200`, `hn_min_comments = 80`, `hn_max_age_hours = 36`, `max_discussions_per_run = 4`, `hn_top_comments = 12`.
2. **Сбор** (`izolenta/hn.py`):
   - список — Algolia `https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=40` (одним запросом: `objectID`, `title`, `url`, `points`, `num_comments`, `created_at_i`, `story_text`);
   - фильтр: очки и комментарии не ниже порогов, не старше `hn_max_age_hours`, id `hn:<objectID>` не в финальном статусе в `seen.json`; сортировка по `num_comments` убыв.; срез `max_discussions_per_run`;
   - комментарии — официальный API: `https://hacker-news.firebaseio.com/v0/item/<id>.json` → `kids` (уже в порядке рейтинга HN) → первые `hn_top_comments` верхнеуровневых `item/<kid>.json` параллельно; пропускать `deleted`/`dead`/пустые; текст — `html_to_text`, каждый не длиннее 1200 символов, все вместе не длиннее 8000;
   - запись: `{id: "hn:<id>", hn_url: "https://news.ycombinator.com/item?id=<id>", url (статья, http(s) или null для Ask HN), title, points, comments, published_at, story_text (до 1500), top_comments: [..]}`; `hn_url` строится из числового id, не берётся из ответа;
   - сбой Algolia или Firebase → запись в `errors` (`{"feed": "HN discussions", ...}`), статьи и посты собираются как обычно; комментарий, который не скачался, просто пропускается.
3. **`pending.json`**: новый список `discussions`; отобранные помечаются `pending` в `seen.json`.
4. **Схема** (`izolenta/schema.py`): `validate_discussion(raw)`: `id` — `hn:<цифры>`; `ok`: `title` 10-200 символов, `summary` 80-700 символов (2-4 предложения, без абзацев), кириллица, без `<`/`>`; `skip` — как у статей.
5. **merge/check**: третий `Kind` (`discussions`, файл `site/data/hn.json`, хранение 3 дня, CLI `--hn site/data/hn.json`); запись `hn.json`: `{id, hn_url, url, points, comments, published_at, title, summary}` — всё, кроме `title` и `summary`, из pending.
6. **`routine/PROMPT.md`**: шаги учитывают `discussions` (работа есть, если не пусто хотя бы одно из трёх; коммит `site/data/hn.json`); раздел «Обсуждения HN»: пересказывать обсуждение, а не статью (что утверждают, о чём спорят, какой консенсус, интересные факты от участников); заголовок — перевод заголовка HN; `skip` для политики и тем без связи с IT, флейма без содержания.

## Key Considerations (SRE review)

- **Объём запросов.** 1 (Algolia) + до 4 историй × (1 + 12) ≈ 53 запроса за запуск — в общем пуле потоков, укладывается во время сбора.
- **Огромные треды.** Берём только верхнеуровневые комментарии в порядке рейтинга HN, не всё дерево.
- **Неверная статья.** Пересказ строится только по комментариям и `story_text`; промпт запрещает додумывать содержание статьи (anti-pattern эпика).
- **Пересечение с новостями.** Та же история HN может прийти и как новость (лента hnrss), и как обсуждение — это разные материалы (статья и обсуждение), id разные (`<sha1 url>` и `hn:<id>`).
- **Пустые и удалённые комментарии** (`deleted`, `dead`, нет `text`) пропускаются; если осталось меньше 3 комментариев — обсуждение не отбирается.

## Tests (TDD)

`tests/test_hn.py` (фикстуры Algolia и Firebase, фейковый fetcher): отбор по порогам и возрасту; `seen` исключает; срез и сортировка по комментариям; комментарии в порядке `kids`, без `deleted/dead`, с обрезкой; `hn_url` из id; сбой Algolia → `errors`, статьи собраны; обсуждение с < 3 живыми комментариями не отбирается.
`tests/test_schema.py`: валидное обсуждение; короткий/английский `summary`; неверный id.
`tests/test_merge.py`: вливание в `hn.json` с метаданными из pending; хранение 3 дня; битый `hn.json` → `StateError`.
`tests/test_check.py`: проблемы обсуждений в отчёте `check`.

## Success Criteria

- [ ] Новые тесты есть и зелёные; весь `pytest` зелёный.
- [ ] Ручной сбор в Actions: в `pending.json` 1-4 обсуждения с 3-12 комментариями каждое.
- [ ] Пробный прогон (Claude в этой сессии) по обновлённому `PROMPT.md` на этих данных: `check` = 0, `hn.json` заполнен.
- [ ] Формат `news.json` и `posts.json` не изменился.

## Result (2026-10-09)

- `uv run pytest`: 184 passed (новые: 12 в `test_hn.py`, 3 в `test_collect.py`, 3 группы в `test_schema.py`, 4 в `test_merge.py`, 1 в `test_check.py`, 2 в `test_cli.py`).
- `merge.py`: посты и обсуждения обрабатываются одним кодом (`OPTIONAL_KINDS`), `_load_pending` возвращает словарь списков; CLI `--hn`.
- Реальный сбор (локально): `hn: selected=4`, по 12 комментариев, ошибок нет, 28 с.
- Пробный прогон по `PROMPT.md` (пересказы писал Claude в этой сессии): `check` = 0; `hn: merged=3 skipped=1` (тред про СДВГ — медицина, не IT); `hn_url` из числового id.
- Найден и исправлен баг в тестах: CLI-тест запускал `merge` без `--posts`, относительный путь по умолчанию указывал на `site/data/posts.json` репозитория, и тест переписал его (попало в коммит `a6192ea`). Файл восстановлен к точке ответвления; все CLI-тесты работают во временном каталоге (`monkeypatch.chdir`); регрессионный тест `test_merge_with_default_paths_never_touches_repo_data`. Ветка не меняет файлы данных относительно `main`.
