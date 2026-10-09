# Task 3.1: Приватный `iizolenta-work`, сбор в GitHub Actions, перенос routine

Epic: `docs/plans/epic-3-actions-hn.md` · Статус: open (SRE review: approved) · Оценка: 3-4 часа + ожидание запусков

## Goal

Сбор работает в Actions приватного `dumka/iizolenta-work` (cron `40 * * * *`) и коммитит туда `state/`. Routine клонирует оба репозитория, не запускает `collect`, берёт `pending.json` из `iizolenta-work`, публикует в `iizolenta`, обновляет `seen.json` в `iizolenta-work`. В публичном репозитории больше нет `state/`.

## Implementation (порядок важен — ни один запуск routine не должен остаться без состояния)

1. **Создать `dumka/iizolenta-work`** (приватный, `gh repo create --private`): `README.md` (что это и почему приватный), `.gitignore` (`.venv/`, `__pycache__/`), `state/seen.json` — копия текущего из `iizolenta/main` (взять сразу после очередного коммита routine), `.github/workflows/collect.yml`:
   - `on: schedule: cron "40 * * * *"` + `workflow_dispatch`; `permissions: contents: write`; `concurrency: collect`; `timeout-minutes: 10`;
   - `actions/checkout@v7` (`path: work`), `actions/checkout@v7` (`repository: dumka/iizolenta`, `path: app`), `astral-sh/setup-uv@v10.2.0`;
   - `uv sync --frozen` и `uv run python -m izolenta collect --config feeds.toml --state-dir ../work/state` в `app/` (код выхода 2 валит шаг — коммита нет);
   - коммит `work/state` от `github-actions[bot]`, только если есть изменения: `collect: <UTC дата время>`, `git pull --rebase origin main`, `git push origin HEAD:main`.
   - `actionlint` чистый.
2. **Routine**: `RemoteTrigger update` — в `sources` добавить `https://github.com/dumka/iizolenta-work` (старый промпт продолжает работать как раньше).
3. **Первый сбор**: `gh workflow run collect.yml -R dumka/iizolenta-work`, дождаться успеха; в `iizolenta-work` появился коммит с `state/pending.json`.
4. **`routine/PROMPT.md`** (коммит в публичный репозиторий вместе с удалением `state/`):
   - вступление: два репозитория — `iizolenta` (код и сайт, рабочий каталог) и `iizolenta-work` (состояние); `WORK` — путь к `iizolenta-work` (обычно `../iizolenta-work`; если нет — `find / -maxdepth 4 -type d -name iizolenta-work 2>/dev/null | head -1`; не нашёлся — завершить без коммитов);
   - шаг «Сбор» убран; «Есть ли работа»: нет `$WORK/state/pending.json` или в нём пусты `items` и `posts` — завершить без коммитов;
   - `check` и `merge` с `--state-dir "$WORK/state"`;
   - публикация: сначала `iizolenta` (`site/data/news.json`, `site/data/posts.json`), потом `iizolenta-work` (`git -C "$WORK" add state`, коммит `summaries: ...`, `pull --rebase`, `push origin HEAD:main`); порядок защищает от потери: если второй push не прошёл, следующий запуск переобработает те же записи (merge заменяет по id, дублей нет);
   - «Не трогай ничего, кроме данных» — для обоих репозиториев.
   - `git rm -r state/`, `.gitignore`: `state/`; README: раздел про `iizolenta-work`, сбор в Actions, окружение Trusted.
5. **Окружение** (делает пользователь): сеть `iizolenta` → Trusted (по умолчанию: GitHub, PyPI); setup script без изменений.
6. **Проверка**: ручной запуск routine → в логе путь `WORK`, `check` = 0, коммиты в оба репозитория, деплой Pages. Затем 3 плановых сбора подряд в Actions.

## Key Considerations (SRE review)

- **Окно между шагами.** Шаг 2 до шага 4: routine со старым промптом и двумя репозиториями работает как раньше; новый промпт приходит, когда состояние уже есть в `iizolenta-work`.
- **Копия `seen.json`.** Брать сразу после коммита routine (`:08-:12`) и до следующего — иначе потеряются отметки последнего запуска и статьи переобработаются (не страшно: merge идемпотентен по id, но тратит лимиты).
- **Опоздание cron.** GitHub может задерживать cron на 5-15 минут (до 30 в часы нагрузки); `:40` оставляет 27 минут до routine. Если сбор не успел — routine обработает прошлый `pending.json` (если он ещё не обработан) или ничего.
- **Гонка push.** Сбор (`:40`) и routine (`:07`) пишут в `iizolenta-work` в разное время; на случай совпадения обе стороны делают `pull --rebase`, конфликт — запуск без коммита, следующий час всё исправит.
- **Доступ routine к приватному репозиторию.** GitHub подключён через `/web-setup` (токен `gh` с `repo`); проверяется ручным запуском. Если клон не удался — запуск без коммитов, routine не ломает сайт.
- **Минуты Actions.** Около 720 из 2000 бесплатных минут в месяц; проверить расход через сутки.
- **Безопасность.** Агент без интернета (кроме GitHub и PyPI), но с правом push в публичный репозиторий; защита от вставки чужого кода через prompt injection — по-прежнему промпт и проверка `git status`. Отдельный guard-workflow — вне этой задачи.

## Anti-patterns

- НЕТ `pending.json` и `seen.json` в публичном репозитории.
- НЕТ PAT и секретов.
- НЕТ режима сети Full.

## Success Criteria

- [ ] `dumka/iizolenta-work` приватный; `collect.yml` проходит `actionlint`; ручной запуск успешен и коммитит `state/`.
- [ ] Routine (ручной запуск) в окружении Trusted: читает `pending.json` из `iizolenta-work`, публикует на сайт, коммитит в оба репозитория.
- [ ] В `iizolenta` нет `state/`; README описывает новую схему.
- [ ] 3 плановых сбора подряд в Actions успешны (проверка `gh run list -R dumka/iizolenta-work`).
