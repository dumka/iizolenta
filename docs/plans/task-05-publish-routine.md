# Task 5: Публикация на GitHub Pages и запуск routine

Epic: `docs/plans/epic-izolenta.md` · Статус: closed (2026-10-08) · Оценка: 3-4 часа (плюс ожидание запусков по расписанию) · Зависит от: Task 4 (closed)

## Goal

Репозиторий `dumka/iizolenta` опубликован, дашборд открывается по `https://dumka.github.io/iizolenta/`, `sites.txt` доступен по URL. Claude Code routine запускается раз в час (на `:07`), собирает новости, пушит `site/data/news.json` и `state/seen.json` в `main`, после чего Pages обновляется автоматически.

## Context

- 2026-10-08: по просьбе пользователя бренд переименован в «ИИзоЛента», репозиторий `dumka/izolenta` переименован в `dumka/iizolenta` (`gh repo rename`); старый адрес Pages больше не работает.

- Всё нужное лежит в репозитории: `routine/PROMPT.md`, `.github/workflows/pages.yml` (деплой `site/**`), `.github/workflows/tests.yml` (тесты при изменении кода), `state/seen.json`, 9 настоящих новостей из пробного прогона.
- Routines (docs: code.claude.com/docs/en/routines.md, cloud-environments.md): минимальный интервал 1 час; каждый запуск клонирует ветку по умолчанию; пушить в `main` можно, если нет защиты ветки; сеть по умолчанию Trusted — домены лент надо разрешить (Custom или Full); setup script окружения кешируется, если укладывается примерно в 5 минут; ручной запуск — «Run now» или `/schedule run`.
- GitHub CLI авторизован как `dumka`.

## Implementation

**Точка подтверждения A (внешнее действие):** спросить пользователя перед созданием публичного репозитория; предложить имя `izolenta`.

0. `gh repo view dumka/iizolenta` — имя должно быть свободно; если занято, спросить другое имя (п. 6).
1. Проверка истории перед публикацией: `git log -p` без `gho_`, `ghp_`, `github_pat_`, `sk-`, `ANTHROPIC`, `BEGIN .* PRIVATE KEY`; `.venv/` и `state/pending.json` не в индексе.
2. `gh repo create dumka/iizolenta --public --description "..."` (без push), `git remote add origin`.
3. Включить Pages с источником GitHub Actions: `gh api -X POST repos/dumka/iizolenta/pages -f build_type=workflow` — до первого push, иначе первый деплой упадёт.
4. `git push -u origin main`. Дождаться workflow `Deploy site to GitHub Pages` и `Tests` (`gh run watch`).
5. Проверка: `https://dumka.github.io/iizolenta/` — 200 и содержит «ИИзоЛента»; `data/news.json` — 200, 9 items; `sites.txt` — 200, `lenta.ru`; шрифты — 200. При 404 сразу после деплоя — повторять до 5 минут (CDN Pages).
6. Если имя репозитория отличается от `izolenta`: поправить `user_agent` в `feeds.toml`, ссылку в футере `site/index.html` и `README.md`.

**Точка подтверждения B (выбор пользователя):** режим сети облачного окружения.
- *Custom (рекомендуется)*: только домены лент и статей — меньше поверхность для prompt injection; тексты HN-ссылок с произвольных доменов будут недоступны (фолбэк на сниппет).
- *Full*: полные тексты для HN, но агент с доступом на запись в репозиторий сможет ходить куда угодно.

7. Облачное окружение `izolenta`. Сначала загрузить навык `schedule` и выяснить, может ли Claude сам создать окружение с нужной сетью и setup script; если нет — дать пользователю пошаговую инструкцию для claude.ai и дождаться подтверждения:
   - Network: выбранный режим. Для Custom — список: `techcrunch.com`, `*.techcrunch.com`, `theverge.com`, `*.theverge.com`, `technologyreview.com`, `*.technologyreview.com`, `arstechnica.com`, `*.arstechnica.com`, `wired.com`, `*.wired.com`, `venturebeat.com`, `*.venturebeat.com`, `simonwillison.net`, `github.blog`, `thenewstack.io`, `blog.google`, `huggingface.co`, `openai.com`, `hnrss.org`; галочка «Also include default list of common package managers» (PyPI для `uv`).
   - Setup script: `pip install --quiet uv && uv sync --frozen`.
8. Routine: репозиторий `dumka/iizolenta`, ветка `main`, окружение `izolenta`, расписание — каждый час в `:07`, промпт: «Выполни инструкцию из файла routine/PROMPT.md в корне репозитория. Пушь только в main.» Коннекторы не нужны — отключить все.
9. Первый запуск — «Run now». Проверить: в логе запуска `collect` без фатальных ошибок и с меньшим числом упавших лент, чем локально; коммит `news: +N (...)` в `main` от routine; workflow Pages отработал; на сайте появились новые новости; `git status` в облаке чистый (никаких лишних файлов).
10. Документация: в README — раздел «Routine» (окружение, список доменов, setup script, промпт, расписание, как запустить вручную, как посмотреть логи).

## Key Considerations (SRE review)

- **Порядок Pages и push.** Если запушить до включения Pages, первый деплой упадёт с «Pages not enabled»; лечится `workflow_dispatch`, но проще включить заранее.
- **Публичная история.** Репозиторий публичный навсегда (форки, кеши). Отсюда проверка истории на секреты в п. 1.
- **Защита ветки.** Новая ветка `main` без правил; если пользователь позже включит защиту, routine перестанет пушить — отметить в README.
- **Лимиты подписки.** 24 запуска в сутки по ~15 статей. После первых суток посмотреть https://claude.ai/settings/usage; при перерасходе снизить `max_items_per_run` или частоту (это настройки, не код).
- **Ленты, недоступные локально** (VentureBeat 429, hnrss DNS) — проверить в логе первого облачного запуска; если и там падают, это не ошибка конвейера, но кандидаты на удаление из `feeds.toml`.
- **Отказ от routine.** Если GitHub-подключение пропадёт, запуски пропускаются до 72 часов, затем routine выключается — отметить в README, как проверить.
- **Версии actions.** actionlint не проверяет существование мажорных версий (`astral-sh/setup-uv@v6`, `actions/upload-pages-artifact@v3`, `actions/deploy-pages@v4`). Если первый прогон упал на устаревшей версии — обновить по логу (`gh run view --log-failed`).
- **Проверка routine без доступа к её логам.** Достаточный признак успеха — коммит routine в `main` (`gh api repos/dumka/iizolenta/commits`), успешный деплой и новые id в `news.json`; лог запуска смотреть в claude.ai при проблемах.
- **Наложение запусков.** Запуск длится несколько минут при интервале в час; блокировки не нужны. Если человек пушит в `main` одновременно — `pull --rebase` в промпте.

## Anti-patterns (для этой задачи)

- НЕТ создания репозитория, включения Pages и создания routine без явного подтверждения пользователя.
- НЕТ секретов в репозитории, переменных окружения routine и промпте (они не нужны).
- НЕТ ручных правок `news.json`/`seen.json` для «проверки» деплоя — только через конвейер.
- НЕТ режима Full без явного выбора пользователя.

## Success Criteria

- [ ] `https://dumka.github.io/iizolenta/` отдаёт 200 и показывает новости; `sites.txt` и `data/news.json` отдают 200.
- [ ] Workflows `Tests` и `Deploy site to GitHub Pages` зелёные на первом push.
- [ ] Ручной запуск routine создал коммит `news: +N` в `main`, Pages передеплоился, новые новости видны на сайте.
- [ ] В README есть раздел про routine: окружение, домены, setup script, промпт, расписание, ручной запуск.
- [ ] Расписание routine — каждый час в `:07`; запуски по расписанию проверяются в Task 6 (критерий эпика «3 запуска подряд»).

## Result (2026-10-08)

- Публикация: история проверена на секреты (чисто); email в коммитах по просьбе пользователя заменён на `3381914+dumka@users.noreply.github.com` (`git filter-branch` до первого push, `user.email` задан локально для репозитория). Репозиторий создан как `dumka/izolenta`, затем по просьбе пользователя переименован в `dumka/iizolenta`, бренд — «ИИзоЛента».
- Pages: `https://dumka.github.io/iizolenta/` — 200; `data/news.json`, `sites.txt`, шрифты — 200.
- Workflows: первый push в пустой репозиторий не запустил workflow с фильтром `paths` — Pages запущен через `workflow_dispatch`. Затем: обновление actions до мажоров на Node 24 (`checkout@v7`, `configure-pages@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5`, `setup-node@v7`); `astral-sh/setup-uv` с v8 не публикует плавающие мажорные теги — закреплён `v10.2.0`. После этого `Tests` и `Deploy` зелёные на каждом push.
- Окружение `iizolenta` (`env_013kFErvjdth5uBGHUHhYUjy`) настроил пользователь: Custom network + setup script `pip install --quiet uv`.
- Routine `trig_01EJgo1DR8d2EZsSriRkoTua`: `7 * * * *`, `claude-sonnet-5-5`, Bash/Read/Write/Edit/Glob/Grep. Сервер сам прикрепил MCP-коннекторы Claude_Docs и Claude_Code_Remote — убраны (`clear_mcp_connections`).
- Ручной запуск (сессия `cse_01UzNBDJydNCazVfQuzQtfvQ`, 109 с): `feeds ok=13 failed=1` (VentureBeat — HTTP 429, как и локально; Ars Technica и hnrss из облака доступны); `check` — с первой попытки; `merged=12 skipped=3 invalid=0 missing=0 failed=0 | news total=21`; коммит `e24b6ac news: +12` только с `news.json` и `seen.json`; Pages передеплоился; на сайте 21 новость, у всех картинки.

### Выводы
- VentureBeat отдаёт 429 и локально, и из облака — кандидат на удаление из `feeds.toml`.
- В режиме Custom ссылки HN ведут на неразрешённые домены: у них только сниппет «Article URL: ...», routine их пропускает. Каждый запуск один слот round-robin уходит на HN впустую — решить с пользователем (оставить, убрать HN или перейти на Full).
- Расход подписки за запуск — смотреть https://claude.ai/settings/usage после первых суток.
