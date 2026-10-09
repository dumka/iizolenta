# Task 4.1: статистика сбора, status.json и страница #/status

Эпик: `epic-4-status-dashboard.md` · Статус: закрыта · 2026-10-09

## Сделано

- `izolenta/collect.py`: в `pending.json` добавлен `stats.sources` — по каждой ленте, аккаунту X и обсуждениям HN: `ok`, `error`, `entries` (записей в ленте), `candidates` (новых и свежих), `selected` (взято в запуск). `izolenta/hn.py`: `collect_discussions` возвращает `Discussions` со счётчиками.
- `izolenta/merge.py`: `_apply` записывает итог каждого материала (`published | skipped | invalid | missing | failed`, причина, попытки); `_update_status` добавляет запуск в `site/data/status.json`, обновляет материалы по id (первый `collected_at` сохраняется), удаляет записи старше 48 часов. Битый `status.json` начинается заново и не ломает слияние. Тексты статей в файл не попадают: только оригинальный заголовок (у поста — первые 120 символов), ссылка, источник, время, итог.
- CLI: `merge --status` (по умолчанию `site/data/status.json`); routine коммитит файл вместе с остальными данными.
- `site/lib.js`: `summarizeSources`, `filterMaterials`, `countOutcomes`, `outcomeGroup`, маршрут `#/status`. `site/app.js`: вид `statusView` (сводка, таблицы «Запуски» и «Источники», материалы с фильтрами Все / Опубликовано / Пропущено / Проблемы, первые 200 + «Показать все»); `status.json` грузится только на этой странице. Ссылок на страницу в меню и подвале нет.

## Проверка

- Тесты: `test_source_stats_*` (3), `test_status_*` и `test_corrupted_status_is_started_afresh` (6), JS `status page` (5).
- Предпросмотр на живом сборе (27 лент, 14 аккаунтов, HN) с искусственными выжимками всех исходов: headless Edge 360 и 1280 px — разделы, фильтры, ссылки «На сайте» только у опубликованных, без горизонтального скролла страницы и ошибок в консоли.
