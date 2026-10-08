# Изолента

Если прокрастинировать, то с пользой. При попытке открыть lenta.ru (или другой сайт из списка) браузер показывает «Изоленту»: страницу в стиле lenta.ru с русскими выжимками мировых новостей AI и IT и ссылками на оригиналы.

- Дашборд: https://dumka.github.io/izolenta/
- Список перехватываемых сайтов: https://dumka.github.io/izolenta/sites.txt

## Как это устроено

```
RSS-ленты --> izolenta collect --> state/pending.json
                                         |
                                         v
                       Claude Code routine (раз в час): state/summaries.json
                                         |
                       izolenta check --> izolenta merge
                                         |
                                         v
                 site/data/news.json --> git push --> GitHub Pages
                                                          ^
        Zen / Vivaldi + LeechBlock NG -- sites.txt -- редирект
```

- `izolenta/` — Python-конвейер: сбор лент, извлечение текста статей, проверка выжимок, слияние.
- `routine/PROMPT.md` — инструкция для облачной Claude Code routine, которая раз в час пишет выжимки.
- `site/` — статичный дашборд без сборки (публикуется на Pages как есть).
- `feeds.toml` — источники и настройки сбора.
- `state/seen.json` — какие статьи уже обработаны (коммитит routine).
- `docs/plans/` — эпик и задачи: требования, решения и их обоснование.

## Локально

```bash
uv sync                                   # зависимости
uv run pytest                             # тесты Python
node --test "tests/js/*.test.mjs"         # тесты дашборда

uv run python -m izolenta collect         # собрать новые статьи в state/pending.json
uv run python -m izolenta check           # проверить state/summaries.json
uv run python -m izolenta merge           # влить выжимки в site/data/news.json

uv run python -m http.server -d site      # дашборд на http://localhost:8000
```

Коды выхода: `0` — успех; `1` — `check` нашёл проблемы; `2` — битый конфиг или состояние (ничего не перезаписано).

## Как расширять

- **Новый источник:** добавить `[[feeds]]` в `feeds.toml` (`name`, `url`, `default_category` = `ai` | `dev` | `business`). Если routine работает в окружении с режимом сети Custom, добавить домен ленты и её статей в список разрешённых.
- **Новый сайт для перехвата:** добавить домен строкой в `site/sites.txt`. LeechBlock на устройствах перечитывает список при запуске браузера.

## Шрифт

`site/fonts/izolenta-sans-*.woff2` — Lato 2.015 (Łukasz Dziedzic, SIL Open Font License 1.1), урезанный до латиницы и кириллицы и переименованный по требованию OFL. Лицензия — `site/fonts/OFL.txt`, сборка — `scripts/subset_fonts.py`.
