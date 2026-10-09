# ИИзоЛента

Если прокрастинировать, то с пользой. При попытке открыть lenta.ru (или другой сайт из списка) браузер показывает «ИИзоЛенту»: страницу в стиле lenta.ru с русскими выжимками мировых новостей AI и IT, ссылками на оригиналы блоком «Пишут в X» — переводами постов Карпаты, Бориса Черного, Альтмана и других — блоком «Обсуждают на HN» с пересказами самых горячих обсуждений Hacker News и блоком «Пишут на Хабре» с пересказами авторских статей из хабов «ИИ» и «ML».

- Дашборд: https://dumka.github.io/iizolenta/
- Список перехватываемых сайтов: https://dumka.github.io/iizolenta/sites.txt
- Состояние конвейера (скрытая страница, ссылок на неё нет): https://dumka.github.io/iizolenta/#/status — запуски, источники и что случилось с каждым материалом за 48 часов

## Как это устроено

```
RSS-ленты, X  --> GitHub Actions в приватном iizolenta-work (по запросу routine)
                  izolenta collect --> state/pending.json, state/seen.json
                                         |
                                         v
                  Claude Code routine (раз в час, :07): выжимки и переводы
                  izolenta check --> izolenta merge
                                         |
                                         v
          site/data/news.json, posts.json, hn.json, habr.json, status.json --> git push --> GitHub Pages
                                                              ^
          Zen / Vivaldi + LeechBlock NG -- sites.txt -- редирект
```

- `izolenta/` — Python-конвейер: сбор лент, извлечение текста статей, проверка выжимок, слияние.
- `routine/PROMPT.md` — инструкция для облачной Claude Code routine, которая раз в час пишет выжимки.
- `site/` — статичный дашборд без сборки (публикуется на Pages как есть).
- `feeds.toml` — источники (RSS-ленты и аккаунты X) и настройки сбора.
- Рабочее состояние (`state/pending.json` с текстами статей и `state/seen.json`) — в приватном репозитории `dumka/iizolenta-work`: тексты чужих статей не публикуются. Там же workflow `collect.yml`, который запускает `izolenta collect` из этого репозитория с полным доступом в интернет — когда routine в начале каждого запуска пушит в `iizolenta-work` файл `state/trigger`; routine ждёт свежий `pending.json` (`routine/wait-for-collect.sh`) и сразу его обрабатывает. Cron — запасной вариант: расписания GitHub ненадёжны.
- `docs/plans/` — эпик и задачи: требования, решения и их обоснование.

## Локально

```bash
uv sync                                   # зависимости
uv run pytest                             # тесты Python
node --test "tests/js/*.test.mjs"         # тесты дашборда

uv run python -m izolenta collect --state-dir /tmp/state   # собрать новые статьи в /tmp/state/pending.json
uv run python -m izolenta check --state-dir /tmp/state     # проверить summaries.json
uv run python -m izolenta merge --state-dir /tmp/state     # влить выжимки в site/data/*.json и записать status.json
uv run python -m izolenta recent --hours 48               # уже опубликованные новости (для проверки дублей)

uv run python -m http.server -d site      # дашборд на http://localhost:8000
```

Коды выхода: `0` — успех; `1` — `check` нашёл проблемы; `2` — битый конфиг или состояние (ничего не перезаписано).

## Как расширять

- **Новый источник:** добавить `[[feeds]]` в `feeds.toml` (`name`, `url`, `default_category` = `ai` | `dev` | `business`). Лента авторских статей, а не новостей (например, ещё один хаб Хабра), — с `kind = "habr"`: её статьи пойдут в блок «Пишут на Хабре» (не больше `max_habr_per_run` за запуск). Сбор работает в GitHub Actions с полным доступом в интернет, так что настраивать ничего больше не нужно.
- **Новый автор в «Пишут в X»:** добавить `[[x_accounts]]` с `handle = "..."` в `feeds.toml`. Посты берутся через FxTwitter API (`api.fxtwitter.com`) — неофициальный бесплатный сервис; если он перестанет работать, блок покажет «Посты из X временно не обновляются», запасной вариант — официальный X API (см. `docs/plans/epic-x-posts.md`).
- **Новый сайт для перехвата:** добавить домен строкой в `site/sites.txt`. LeechBlock на устройствах перечитывает список при запуске браузера.

Настройка перехвата на устройствах (Zen, Vivaldi): [docs/setup-leechblock.md](docs/setup-leechblock.md).

## Шрифт

`site/fonts/izolenta-sans-*.woff2` — Lato 2.015 (Łukasz Dziedzic, SIL Open Font License 1.1), урезанный до латиницы и кириллицы и переименованный по требованию OFL. Лицензия — `site/fonts/OFL.txt`, сборка — `scripts/subset_fonts.py`.

## Routine (обновление новостей)

Выжимки и переводы раз в час пишет облачная Claude Code routine «ИИзоЛента: новости AI/IT»: https://claude.ai/code/routines/trig_01EJgo1DR8d2EZsSriRkoTua. Статьи, посты и обсуждения для неё собирает workflow `collect` в `dumka/iizolenta-work`: в начале запуска routine пушит `state/trigger`, сбор стартует, routine ждёт его результат (до 7 минут) и обрабатывает свежие материалы.

| Параметр | Значение |
|---|---|
| Расписание | `7 * * * *` — каждый час в :07 UTC |
| Репозитории | `dumka/iizolenta` (код и сайт) и `dumka/iizolenta-work` (состояние), ветка `main` |
| Модель | `claude-sonnet-5-5` |
| Инструменты | Bash, Read, Write, Edit, Glob, Grep; MCP-коннекторов нет |
| Промпт | «Прочитай целиком файл routine/PROMPT.md в корне репозитория iizolenta и выполни инструкцию из него. Пушь только в ветку main.» |
| Окружение | `iizolenta` |

Окружение `iizolenta` (claude.ai → Code → Environments):

- **Network access:** Trusted (по умолчанию: GitHub и менеджеры пакетов). Агенту не нужен интернет — статьи и посты уже лежат в `state/pending.json`.
- **Setup script:** `pip install --quiet uv`.

**Ручной запуск:** кнопка «Run now» на странице routine или `/schedule run` в Claude Code. **Логи:** список запусков на той же странице.

**Что может сломать конвейер:**
- workflow `collect` в `iizolenta-work` не запускается или падает — смотреть `gh run list -R dumka/iizolenta-work`; на бесплатном тарифе у приватных репозиториев около 2000 минут Actions в месяц, сбор тратит примерно 720;
- защита ветки `main` в настройках GitHub — routine перестанет пушить;
- отключение GitHub от Claude — запуски пропускаются до 72 часов, затем routine выключается (переподключить: `/web-setup`);
- исчерпание лимитов подписки — запуски отклоняются до сброса; расход видно на https://claude.ai/settings/usage, снизить его можно через `max_items_per_run` в `feeds.toml`.
