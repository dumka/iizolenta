# Task 3: Дашборд в стиле lenta.ru (`site/`)

Epic: `docs/plans/epic-izolenta.md` · Статус: closed (2026-10-08) · Оценка: 6-7 часов · Зависит от: Task 2 (closed, формат `news.json` зафиксирован)

## Goal

Статичная страница `site/index.html` загружает `data/news.json` и показывает новости в духе lenta.ru: шапка, рубрики, главная новость, лента, страница новости со ссылкой на оригинал. Работает на 360px без горизонтального скролла. Если пришли через LeechBlock (`#<url>`), показывает, какой сайт пытались открыть.

## Context

- `site/data/news.json`: `{"generated_at": "...Z", "items": [{id, url, source, published_at, category, importance (1..3), title, lead, body[3..5], image|null}]}`, отсортировано от новых к старым.
- Данные уже проверены `merge` (http(s)-ссылки, без HTML), но страница всё равно выводит только через `textContent` и перепроверяет URL (защита в глубину).
- Стиль Ленты (из её CSS): шрифт Lato (у Ленты своя сборка Lato Lenta; берём Lato из Google Fonts), текст `#292929`, акцент `#c33`, вторичный `#999` / `#595959`, линии `#eaeaea`, фон секций `#f5f5f5`. Заголовок главной — `font-weight: 900`; мини-карточка — 15px/1.25 regular с жирным временем; меню — 13px серым, активный пункт красным.
- Бренд: только словесный логотип «Изолента», никаких логотипов и названия Ленты.

## Implementation

1. `site/lib.js` — чистые функции (ES-модуль, без DOM), покрыты node:test:
   - `CATEGORIES = {ai: "ИИ и модели", dev: "Разработка", business: "Бизнес и стартапы"}`.
   - `parseRoute(hash)`: `""`/`"#"`/`"#/"` → `{view: "home"}`; `"#/ai"` → `{view: "category", category: "ai"}` (неизвестная рубрика → home); `"#/news/<id>"` → `{view: "article", id}`; хэш, начинающийся с `http://`/`https://` (после `#`) → `{view: "blocked", url}`.
   - `blockedHost(url)`: hostname без `www.`; невалидный URL → `null`.
   - `isSafeUrl(url)`: только `http:`/`https:`.
   - `formatTime(iso, now, timeZone)`: сегодня → `"14:05"`; вчера → `"вчера, 14:05"`; раньше → `"7 октября, 14:05"`. Через `Intl.DateTimeFormat("ru-RU", {timeZone})`; «сегодня/вчера» по календарной дате в этой зоне.
   - `pickTopStory(items)`: максимальная `importance`, среди равных — самая свежая; пустой список → `null`.
   - `filterByCategory(items, category)`.
   - `related(items, item, n)`: та же рубрика, без самой новости, не больше `n`.

2. `site/index.html`: каркас (`<header>`, `<nav>`, `<main id="app">`, `<footer>`), `<meta name="viewport">`, `lang="ru"`, `<title>Изолента</title>`, Lato через Google Fonts (`display=swap`), `<script type="module" src="app.js">`. Фавикон — inline SVG data-URI (полоска изоленты).

3. `site/styles.css`:
   - CSS-переменные с токенами выше.
   - Шапка: логотип «Изолента» (Lato 900, красная полоска-«изолента» под словом), дата, строка рубрик.
   - Главная, ширина от 1024px: две колонки. Слева (около 2/3) — главная новость (картинка, если есть; заголовок 900, 28px; лид), под ней «Важное» — карточки с заголовком и лидом (importance >= 2). Справа (около 1/3) — «Последние новости»: хронологическая лента мини-карточек (жирное время + заголовок + источник серым).
   - До 1024px — одна колонка: главная новость, «Важное», «Последние новости».
   - Страница новости: метка рубрики (красным), время и источник, `h1` (900), лид (жирный), абзацы `body`, картинка, кнопка «Читать оригинал на {source} →» (`target="_blank" rel="noopener noreferrer"`), ниже «Ещё в рубрике» (`related`, 5 штук).
   - `overflow-wrap: anywhere` для заголовков и текста; картинки `max-width: 100%`; боковые поля 16px на мобильном.
   - Тёмную тему не делаем (у Ленты её нет; вне scope).

4. `site/app.js` (ES-модуль, импортирует `lib.js`):
   - Загрузка `data/news.json?t=<минуты>` с `cache: "no-cache"` (Pages кеширует на 10 минут).
   - Состояния: «Загрузка...», «Новостей пока нет», «Не удалось загрузить новости» + кнопка «Повторить».
   - Рендер только через `document.createElement` + `textContent`; ссылки — через `isSafeUrl`, небезопасные не выводятся.
   - `hashchange` → перерисовка; при переходе на новость — скролл наверх.
   - Маршрут `blocked`: баннер «Вы хотели открыть {host}. Вот что почитать вместо этого.» над главной, затем `history.replaceState(null, "", "#/")`, чтобы обновление страницы не показывало баннер снова. Закрывается крестиком.
   - Неизвестный id новости (устарела и удалена) → «Новость не найдена» + ссылка на главную.
   - Картинка: `loading="lazy"`, `referrerPolicy="no-referrer"` (часть CDN режет хотлинк по Referer), при `error` элемент удаляется.
   - Футер: «Обновлено: {formatTime(generated_at)}» и ссылка на репозиторий.
   - Если вкладка видима, повторная загрузка данных раз в 15 минут.
   - `document.title`: на новости — заголовок новости + « — Изолента».

5. `site/sites.txt`: `lenta.ru` (одна строка; формат «Load list of sites from URL» у LeechBlock).

6. `site/data/news.json`: пустой `{"generated_at": null, "items": []}` (дашборд показывает «Новостей пока нет» до первой routine). `merge` его перезапишет.

## Key Considerations (SRE review)

- **XSS.** Данные из внешних лент; даже после merge — только `textContent`, `isSafeUrl` для `href`/`src`. Критерий: в `site/*.js` нет `innerHTML`, `insertAdjacentHTML`, `document.write`.
- **Хэш от LeechBlock.** `$U` подставляется без кодирования: `#https://lenta.ru/news/2026/10/08/x/?a=1&b=2`. `parseRoute` берёт всё после `#`, не парсит как query.
- **Кеш Pages (10 минут).** Без cache-busting после обновления routine можно видеть старые данные.
- **Пустые и битые данные.** Пустой `items`, `generated_at = null`, сетевая ошибка, 404 до первого деплоя данных — понятные состояния, а не пустой экран или исключение в консоли.
- **Часовой пояс.** Даты в UTC; показываем в зоне браузера. Тесты передают зону явно (`Europe/Moscow`), чтобы не зависеть от машины.
- **Нет картинки.** У части новостей `image = null` или CDN отдаёт 403 — вёрстка без картинки не должна ломаться.
- **Длинные слова.** Названия моделей и URL в тексте — `overflow-wrap: anywhere`, иначе горизонтальный скролл на 360px.
- **Подпапка на Pages.** Сайт живёт по адресу `https://dumka.github.io/izolenta/`, а не в корне домена. Все пути относительные (`data/news.json`, `app.js`, `styles.css`, `#/...`); ни одного пути, начинающегося с `/`. Локально с `http.server -d site` абсолютные пути работали бы и скрыли бы баг.
- **`#` внутри перехваченного URL.** `lenta.ru/x#comments` даст хэш `#https://lenta.ru/x#comments`: `parseRoute` берёт всё после первого `#`.
- **ES-модули и `file://`.** Модули не грузятся из `file://`, поэтому проверка только через HTTP-сервер.
- **Удалённая новость.** Ссылка на `#/news/<id>` старше 7 дней — «Новость не найдена», а не падение.

## Anti-patterns (для этой задачи)

- НЕТ `innerHTML` и шаблонных строк с данными в разметке.
- НЕТ фреймворков, сборщиков и npm-зависимостей в `site/` (anti-pattern эпика).
- НЕТ логотипа, названия и фирменного шрифта Ленты.
- НЕТ логики в `app.js`, которую можно вынести в чистую функцию `lib.js` без потери читаемости (тестируемость).

## Tests (`node --test site/tests/`)

`site/tests/lib.test.mjs`:
- `parseRoute`: home для `""`, `"#"`, `"#/"`; категория; неизвестная категория → home; статья; blocked для `#https://lenta.ru/news/x/?a=1&b=2` (url целиком, с `&`); blocked для `#http://...`.
- `parseRoute`: blocked для `#https://lenta.ru/x#comments` (вложенный `#` сохраняется в url).
- `blockedHost`: `https://www.lenta.ru/x` → `lenta.ru`; `m.lenta.ru` сохраняется; мусор → `null`.
- `isSafeUrl`: http/https — да; `javascript:alert(1)`, `data:...`, `//evil`, пустая строка — нет.
- `formatTime` (зона Europe/Moscow, now = 2026-10-08T12:00Z): сегодня `"14:05"` для 11:05Z; переход через полночь по Москве (2026-10-07T22:30Z → «сегодня», 01:30 МСК); вчера; «7 октября» для более старых; правильный родительный падеж месяца.
- `pickTopStory`: выбирает importance 3, среди двух троек — свежую; пустой список → `null`.
- `related`: исключает саму новость, только та же рубрика, ограничение `n`.

## Success Criteria

- [ ] `node --test site/tests/` зелёный, не меньше 20 проверок.
- [ ] `uv run pytest` по-прежнему зелёный.
- [ ] Локально (`python -m http.server -d site`) с демо-данными: скриншоты главной на 1280px и 360px и страницы новости на 360px; на 360px `document.documentElement.scrollWidth <= 360`.
- [ ] Открытие `index.html#https://lenta.ru/news/x/?a=1&b=2` показывает баннер с `lenta.ru`; после этого адрес — `#/`.
- [ ] `grep -nE "(src|href)=\"/|fetch\(\"/" site/` пусто (нет абсолютных путей).
- [ ] Проверка в headless Edge (`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`) через puppeteer-core, установленный во временную папку (не в проект).
- [ ] `grep -nE "innerHTML|insertAdjacentHTML|document\.write" site/*.js` пусто.
- [ ] Пустой `news.json` → «Новостей пока нет»; недоступный `news.json` → сообщение об ошибке и кнопка «Повторить».

## Result (2026-10-08)

- `node --test "tests/js/*.test.mjs"`: 30/30 (на Windows `node --test <папка>` не работает, нужен glob). Тесты перенесены из `site/tests/` в `tests/js/`, чтобы не публиковать их на Pages.
- `uv run pytest`: 95/95.
- Headless Edge + puppeteer-core (временная папка, `puppeteer.connect` к Edge с `--remote-debugging-port`; `launch` не работает, т.к. `msedge.exe` передаёт запуск дочернему процессу): 12 проверок PASS — главная 1280/360, статья 360 (scrollWidth = 360), активная рубрика, баннер `lenta.ru` и замена хэша на `#/`, закрытие баннера, «Новость не найдена», пустые данные, 404 + «Повторить».
- Единственная ошибка в консоли — картинка `media.wired.com` недоступна отсюда (`ERR_CONNECTION_RESET`); обработчик `error` убирает `<img>`, вёрстка цела.
- Грепы на `innerHTML`/`document.write` и абсолютные пути — пусто.

### Отклонения от плана
- **Шрифт.** Lato из Google Fonts не содержит кириллицы: латиница и кириллица в заголовках рендерились разными шрифтами. Вместо Google Fonts — Lato 2.015 (npm `lato-font@3.0.0`, SIL OFL), урезанный до Latin-1 + кириллица и переименованный в «Izolenta Sans» (требование OFL о Reserved Font Name). Файлы `site/fonts/izolenta-sans-{400,700,900}.woff2` по ~31 КБ + `OFL.txt`; скрипт сборки — `scripts/subset_fonts.py`.

### Выводы для следующих задач
- У TechCrunch и The Verge в лентах нет картинок, а у страниц статей есть `og:image`. `collect` уже скачивает страницу — можно брать картинку оттуда (`trafilatura.extract_metadata(page).image`), если в ленте её нет.
