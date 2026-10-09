import {
  CATEGORIES,
  blockedHost,
  countOutcomes,
  filterByCategory,
  filterMaterials,
  formatTime,
  isSafeUrl,
  outcomeGroup,
  paragraphs,
  parseRoute,
  pickTopStory,
  pluralRu,
  postsStale,
  related,
  summarizeSources,
} from "./lib.js";

const DATA_URL = "data/news.json";
const POSTS_URL = "data/posts.json";
const HN_URL = "data/hn.json";
const STATUS_URL = "data/status.json";
const STATUS_MATERIALS_LIMIT = 200;
const HOME_DISCUSSIONS_LIMIT = 4;
const REFRESH_MS = 15 * 60 * 1000;
const LATEST_LIMIT = 30;
const IMPORTANT_LIMIT = 8;
const RELATED_LIMIT = 5;
const HOME_POSTS_LIMIT = 5;
const SITE_TITLE = "ИИзоЛента — новости AI и IT";

const app = document.getElementById("app");
// news and posts load independently: a broken posts.json must not take the news down
const state = { data: null, error: null, posts: null, postsError: null, hn: null, hnError: null, blockedHost: null };
// the hidden #/status page loads its own data only when opened
const statusPage = { data: null, error: null, loading: false, filter: "all", showAll: false };

// Build DOM nodes; strings become text nodes, so feed data never turns into markup.
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function articleHref(item) {
  return `#/news/${encodeURIComponent(item.id)}`;
}

function image(url, className) {
  if (!isSafeUrl(url)) return null;
  const img = el("img", { class: className, src: url, alt: "", loading: "lazy" });
  img.referrerPolicy = "no-referrer";
  img.addEventListener("error", () => img.remove());
  return img;
}

function meta(item, { rubric = false } = {}) {
  return el(
    "div",
    { class: "meta" },
    el("span", { class: "meta__time" }, formatTime(item.published_at)),
    rubric ? el("a", { class: "meta__rubric", href: `#/${item.category}` }, CATEGORIES[item.category] || "") : null,
    item.source,
  );
}

function topStory(item) {
  return el(
    "article",
    { class: "card-big" },
    el("a", { href: articleHref(item) }, image(item.image, "card-big__image")),
    meta(item, { rubric: true }),
    el("a", { class: "card-big__title", href: articleHref(item) }, item.title),
    el("p", { class: "card-big__lead" }, item.lead),
  );
}

function mediumCard(item) {
  return el(
    "article",
    { class: "card-medium" },
    meta(item, { rubric: true }),
    el("a", { class: "card-medium__title", href: articleHref(item) }, item.title),
    el("p", { class: "card-medium__lead" }, item.lead),
  );
}

function miniCard(item) {
  return el(
    "a",
    { class: "card-mini", href: articleHref(item) },
    el("span", { class: "meta__time" }, formatTime(item.published_at)),
    el("span", { class: "card-mini__source" }, item.source),
    el("span", { class: "card-mini__title" }, item.title),
  );
}

function postCard(post) {
  return el(
    "article",
    { class: "post" },
    el(
      "div",
      { class: "post__head" },
      el("span", { class: "post__author" }, post.author_name),
      el("span", { class: "post__handle" }, `@${post.author_handle}`),
      el("span", { class: "post__time" }, formatTime(post.published_at)),
    ),
    paragraphs(post.text).map((paragraph) => el("p", { class: "post__text" }, paragraph)),
    isSafeUrl(post.url)
      ? el("a", { class: "post__link", href: post.url, target: "_blank", rel: "noopener noreferrer" }, "Открыть в X →")
      : null,
  );
}

const STALE_POSTS = "Посты из X временно не обновляются.";

function postsBlock() {
  if (!state.posts) return null; // still loading or failed: the home page works without the block
  const items = state.posts.items;
  return el(
    "section",
    { class: "posts-block" },
    el("h2", { class: "section-title" }, el("a", { href: "#/x" }, "Пишут в X")),
    postsStale(items)
      ? el("p", { class: "posts-block__note" }, STALE_POSTS)
      : [items.slice(0, HOME_POSTS_LIMIT).map(postCard), el("a", { class: "posts-block__more", href: "#/x" }, "Все посты →")],
  );
}

function postsView() {
  document.title = "Пишут в X — ИИзоЛента";
  const title = el("h1", { class: "page-title" }, "Пишут в X");
  if (state.postsError) {
    return [
      title,
      stateView("Лента порвалась.", el("button", { class: "state__button", type: "button", onclick: () => load() }, "Подклеить")),
    ];
  }
  if (!state.posts) return [title, stateView("Разматываем ленту...")];
  const items = state.posts.items;
  if (!items.length) return [title, stateView("Пока тихо: свежих постов нет.")];
  return [
    title,
    el(
      "div",
      { class: "posts-page" },
      postsStale(items) ? el("p", { class: "posts-block__note" }, STALE_POSTS) : null,
      items.map(postCard),
    ),
  ];
}

function discussionCard(d) {
  const counters = `${d.points} ${pluralRu(d.points, ["очко", "очка", "очков"])} · ${d.comments} ${pluralRu(d.comments, ["комментарий", "комментария", "комментариев"])}`;
  return el(
    "article",
    { class: "discussion" },
    el(
      "div",
      { class: "post__head" },
      el("span", { class: "post__time" }, formatTime(d.published_at)),
      el("span", { class: "post__handle" }, counters),
    ),
    isSafeUrl(d.hn_url)
      ? el("a", { class: "discussion__title", href: d.hn_url, target: "_blank", rel: "noopener noreferrer" }, d.title)
      : el("span", { class: "discussion__title" }, d.title),
    el("p", { class: "post__text discussion__summary" }, d.summary),
    el(
      "div",
      { class: "discussion__links" },
      isSafeUrl(d.hn_url)
        ? el("a", { class: "post__link", href: d.hn_url, target: "_blank", rel: "noopener noreferrer" }, "Обсуждение на HN →")
        : null,
      isSafeUrl(d.url)
        ? el("a", { class: "post__link discussion__article", href: d.url, target: "_blank", rel: "noopener noreferrer" }, "Статья →")
        : null,
    ),
  );
}

function discussionsBlock() {
  if (!state.hn || !state.hn.items.length) return null; // still loading, failed or empty: no block
  return el(
    "section",
    { class: "posts-block hn-block" },
    el("h2", { class: "section-title" }, el("a", { href: "#/hn" }, "Обсуждают на HN")),
    state.hn.items.slice(0, HOME_DISCUSSIONS_LIMIT).map(discussionCard),
    el("a", { class: "posts-block__more", href: "#/hn" }, "Все обсуждения →"),
  );
}

function discussionsView() {
  document.title = "Обсуждают на HN — ИИзоЛента";
  const title = el("h1", { class: "page-title" }, "Обсуждают на HN");
  if (state.hnError) {
    return [
      title,
      stateView("Лента порвалась.", el("button", { class: "state__button", type: "button", onclick: () => load() }, "Подклеить")),
    ];
  }
  if (!state.hn) return [title, stateView("Разматываем ленту...")];
  if (!state.hn.items.length) return [title, stateView("Пока тихо: свежих обсуждений нет.")];
  return [title, el("div", { class: "posts-page" }, state.hn.items.map(discussionCard))];
}

function feedView(items, title, { withPosts = false } = {}) {
  const top = pickTopStory(items);
  const important = items
    .filter((item) => item !== top && item.importance >= 2)
    .slice(0, IMPORTANT_LIMIT);
  return [
    title ? el("h1", { class: "page-title" }, title) : null,
    el(
      "div",
      { class: "layout" },
      el(
        "div",
        { class: "main-column" },
        top ? topStory(top) : null,
        important.length
          ? el("section", { class: "important" }, el("h2", { class: "section-title" }, "Важное"), important.map(mediumCard))
          : null,
      ),
      el(
        "aside",
        { class: "latest" },
        withPosts ? postsBlock() : null,
        withPosts ? discussionsBlock() : null,
        el("h2", { class: "section-title" }, "Последние новости"),
        items.slice(0, LATEST_LIMIT).map(miniCard),
      ),
    ),
  ];
}

function articleView(items, id) {
  const item = items.find((candidate) => candidate.id === id);
  if (!item) {
    document.title = SITE_TITLE;
    return stateView("Эту новость уже смотали: она старше недели.", el("a", { class: "state__link", href: "#/" }, "На главную"));
  }
  document.title = `${item.title} — ИИзоЛента`;
  const more = related(items, item, RELATED_LIMIT);
  return el(
    "article",
    { class: "article" },
    meta(item, { rubric: true }),
    el("h1", { class: "article__title" }, item.title),
    el("p", { class: "article__lead" }, item.lead),
    image(item.image, "article__image"),
    el("div", { class: "article__body" }, item.body.map((paragraph) => el("p", {}, paragraph))),
    isSafeUrl(item.url)
      ? el("a", { class: "source-link", href: item.url, target: "_blank", rel: "noopener noreferrer" }, `Читать оригинал на ${item.source} →`)
      : null,
    more.length ? el("section", {}, el("h2", { class: "section-title" }, "Ещё в рубрике"), more.map(miniCard)) : null,
  );
}

const OUTCOMES = {
  published: "Опубликовано",
  skipped: "Пропущено",
  invalid: "Невалидно, будет повтор",
  missing: "Нет выжимки, будет повтор",
  failed: "Снято после 3 попыток",
};
const MATERIAL_KINDS = { article: "Статья", post: "Пост X", discussion: "HN" };
const SOURCE_KINDS = { feed: "лента", x: "X", hn: "HN" };
const STATUS_FILTERS = [
  ["all", "Все"],
  ["published", "Опубликовано"],
  ["skipped", "Пропущено"],
  ["problems", "Проблемы"],
];

function plural(n, forms) {
  return `${n} ${pluralRu(n, forms)}`;
}

function externalLink(url, text, className) {
  return isSafeUrl(url)
    ? el("a", { class: className, href: url, target: "_blank", rel: "noopener noreferrer" }, text)
    : el("span", { class: className }, text);
}

function table(head, rows) {
  return el(
    "div",
    { class: "status-table-wrap" },
    el(
      "table",
      { class: "status-table" },
      el("thead", {}, el("tr", {}, head.map((cell) => el("th", {}, cell)))),
      el("tbody", {}, rows.map((cells) => el("tr", {}, cells.map((cell) => el("td", {}, cell))))),
    ),
  );
}

function kindResult(result) {
  if (!result) return "—";
  const problems = result.invalid + result.missing + result.failed;
  return `+${result.merged} · пропущено ${result.skipped}${problems ? ` · проблем ${problems}` : ""}`;
}

function runsTable(runs) {
  return table(
    ["Обработка", "Сбор", "Источники", "Новых → взято", "Статьи", "Посты", "HN"],
    runs.map((run) => {
      const sources = run.sources || [];
      const ok = sources.filter((s) => s.ok).length;
      const candidates = sources.reduce((sum, s) => sum + (s.candidates || 0), 0);
      const selected = sources.reduce((sum, s) => sum + (s.selected || 0), 0);
      return [
        formatTime(run.merged_at),
        formatTime(run.collected_at),
        el("span", { class: ok < sources.length ? "status-bad" : null }, `${ok} из ${sources.length}`),
        `${candidates} → ${selected}`,
        kindResult(run.result?.items),
        kindResult(run.result?.posts),
        kindResult(run.result?.discussions),
      ];
    }),
  );
}

function sourcesTable(rows) {
  return table(
    ["Источник", "Состояние", "Записей", "Новых", "Взято", "Взято за 48 ч", "Опубл.", "Пропущ.", "Проблем"],
    rows.map((r) => [
      el("span", {}, el("b", {}, r.name), " ", el("span", { class: "status-muted" }, SOURCE_KINDS[r.kind] || "")),
      r.ok === false
        ? el("span", { class: "status-bad" }, "Ошибка: ", el("span", { class: "status-error" }, r.error || ""))
        : r.ok
          ? el("span", { class: "status-good" }, "Работает")
          : el("span", { class: "status-muted" }, "нет данных сбора"),
      String(r.entries ?? "—"),
      String(r.candidates ?? "—"),
      String(r.selected ?? "—"),
      String(r.selectedTotal),
      String(r.published),
      String(r.skipped),
      r.problems ? el("span", { class: "status-bad" }, String(r.problems)) : "0",
    ]),
  );
}

function siteHref(material) {
  if (material.outcome !== "published") return null;
  if (material.kind === "article") return articleHref(material);
  return material.kind === "post" ? "#/x" : "#/hn";
}

function materialCard(m) {
  const href = siteHref(m);
  const textSource = m.text_source === "article" ? "полный текст" : m.text_source === "snippet" ? "только анонс" : null;
  return el(
    "article",
    { class: "material" },
    el(
      "div",
      { class: "post__head" },
      el("span", { class: "material__kind" }, MATERIAL_KINDS[m.kind] || m.kind || ""),
      el("span", { class: "post__author" }, m.source || ""),
      el("span", { class: "post__time" }, `опубл. ${formatTime(m.published_at)}`),
      el("span", { class: "post__time" }, `собрано ${formatTime(m.collected_at)}`),
      textSource ? el("span", { class: "post__time" }, textSource) : null,
      m.attempts > 1 ? el("span", { class: "post__time" }, `попыток: ${m.attempts}`) : null,
    ),
    externalLink(m.url, m.title || m.id, "material__title"),
    el(
      "div",
      { class: "material__outcome" },
      el("span", { class: `chip chip--${outcomeGroup(m.outcome)}` }, OUTCOMES[m.outcome] || m.outcome || ""),
      m.reason && m.outcome !== "missing" ? el("span", { class: "material__reason" }, m.reason) : null,
      href ? el("a", { class: "post__link", href }, "На сайте →") : null,
    ),
  );
}

function rerenderStatus(change) {
  Object.assign(statusPage, change);
  render();
}

function materialsSection(materials) {
  const counts = countOutcomes(materials);
  const shown = filterMaterials(materials, statusPage.filter);
  const visible = statusPage.showAll ? shown : shown.slice(0, STATUS_MATERIALS_LIMIT);
  return el(
    "section",
    { class: "status-section" },
    el("h2", { class: "section-title" }, "Материалы"),
    el(
      "div",
      { class: "status-filters" },
      STATUS_FILTERS.map(([key, label]) =>
        el(
          "button",
          {
            class: `status-filter${statusPage.filter === key ? " is-active" : ""}`,
            type: "button",
            onclick: () => rerenderStatus({ filter: key, showAll: false }),
          },
          `${label} · ${counts[key]}`,
        ),
      ),
    ),
    visible.length ? visible.map(materialCard) : el("p", { class: "status-muted" }, "Ничего нет."),
    visible.length < shown.length
      ? el(
          "button",
          { class: "state__button", type: "button", onclick: () => rerenderStatus({ showAll: true }) },
          `Показать все (${shown.length})`,
        )
      : null,
  );
}

function statusView() {
  document.title = "Состояние конвейера — ИИзоЛента";
  const title = el("h1", { class: "page-title" }, "Состояние конвейера");
  if (statusPage.error) {
    return [
      title,
      stateView("Не удалось загрузить состояние.", el("button", { class: "state__button", type: "button", onclick: () => loadStatus() }, "Повторить")),
    ];
  }
  if (!statusPage.data) return [title, stateView("Разматываем ленту...")];
  const runs = [...statusPage.data.runs].sort((a, b) => String(b.merged_at).localeCompare(String(a.merged_at)));
  const materials = statusPage.data.materials;
  if (!runs.length) return [title, stateView("Запусков за 48 часов пока нет.")];
  const [last] = runs;
  return [
    title,
    el(
      "div",
      { class: "status-page" },
      el(
        "p",
        { class: "status-summary" },
        `Последняя обработка: ${formatTime(last.merged_at)} (сбор ${formatTime(last.collected_at)}). `,
        `За 48 часов: ${plural(runs.length, ["запуск", "запуска", "запусков"])}, `,
        `${plural(materials.length, ["материал", "материала", "материалов"])}. `,
        "Запуски без новых материалов здесь не видны.",
      ),
      el("section", { class: "status-section" }, el("h2", { class: "section-title" }, "Запуски"), runsTable(runs)),
      el(
        "section",
        { class: "status-section" },
        el("h2", { class: "section-title" }, "Источники"),
        sourcesTable(summarizeSources(statusPage.data)),
      ),
      materialsSection(materials),
    ),
  ];
}

function stateView(message, ...extra) {
  return el("div", { class: "state" }, el("p", {}, message), extra);
}

function banner() {
  if (state.blockedHost === null) return null;
  return el(
    "div",
    { class: "banner", role: "status" },
    el("span", {}, `${state.blockedHost ? `Сайт ${state.blockedHost}` : "Этот сайт"} заизолирован. Держите ИИзоЛенту — тут полезнее.`),
    el("button", {
      class: "banner__close",
      type: "button",
      "aria-label": "Закрыть",
      onclick: () => {
        state.blockedHost = null;
        render();
      },
    }, "×"),
  );
}

function updateChrome(route) {
  const active = route.view === "category" ? route.category : route.view === "x" || route.view === "hn" ? route.view : "";
  for (const link of document.querySelectorAll(".menu__link")) {
    const highlighted = route.view !== "article" && route.view !== "status" && link.dataset.category === active;
    link.classList.toggle("is-active", highlighted);
  }
  const updated = document.getElementById("updated");
  updated.textContent = state.data?.generated_at ? `Обновлено: ${formatTime(state.data.generated_at)}` : "";
}

function render() {
  let route = parseRoute(location.hash);
  if (route.view === "blocked") {
    state.blockedHost = blockedHost(route.url) || "";
    history.replaceState(null, "", "#/");
    route = { view: "home" };
  }
  if (route.view !== "article") document.title = SITE_TITLE;
  updateChrome(route);

  let content;
  if (route.view === "x") {
    content = postsView();
  } else if (route.view === "hn") {
    content = discussionsView();
  } else if (route.view === "status") {
    if (!statusPage.data && !statusPage.error && !statusPage.loading) loadStatus();
    content = statusView();
  } else if (state.error) {
    content = stateView(
      "Лента порвалась.",
      el("button", { class: "state__button", type: "button", onclick: () => load() }, "Подклеить"),
    );
  } else if (!state.data) {
    content = stateView("Разматываем ленту...");
  } else if (!state.data.items.length) {
    content = stateView("Свежую ленту ещё наматывают. Загляните через час.");
  } else if (route.view === "article") {
    content = articleView(state.data.items, route.id);
  } else if (route.view === "category") {
    content = feedView(filterByCategory(state.data.items, route.category), CATEGORIES[route.category]);
  } else {
    content = feedView(state.data.items, null, { withPosts: true });
  }
  app.replaceChildren(...[banner(), content].flat().filter(Boolean));
}

async function loadJson(url, lists = ["items"]) {
  const cacheBust = Math.floor(Date.now() / 60000);
  const response = await fetch(`${url}?t=${cacheBust}`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  const data = await response.json();
  for (const key of lists) {
    if (!Array.isArray(data?.[key])) throw new Error(`${url}: ${key} is not a list`);
  }
  return data;
}

async function loadStatus() {
  statusPage.loading = true;
  try {
    statusPage.data = await loadJson(STATUS_URL, ["runs", "materials"]);
    statusPage.error = null;
  } catch (error) {
    console.warn("ИИзоЛента: не удалось загрузить состояние конвейера", error);
    if (!statusPage.data) statusPage.error = error;
  } finally {
    statusPage.loading = false;
  }
  if (parseRoute(location.hash).view === "status") render();
}

async function load() {
  const [news, posts, hn] = await Promise.allSettled([loadJson(DATA_URL), loadJson(POSTS_URL), loadJson(HN_URL)]);
  // keep showing stale data if we already have some
  if (news.status === "fulfilled") {
    state.data = news.value;
    state.error = null;
  } else {
    console.error("ИИзоЛента: не удалось загрузить новости", news.reason);
    if (!state.data) state.error = news.reason;
  }
  if (posts.status === "fulfilled") {
    state.posts = posts.value;
    state.postsError = null;
  } else {
    console.warn("ИИзоЛента: не удалось загрузить посты", posts.reason);
    if (!state.posts) state.postsError = posts.reason;
  }
  if (hn.status === "fulfilled") {
    state.hn = hn.value;
    state.hnError = null;
  } else {
    console.warn("ИИзоЛента: не удалось загрузить обсуждения HN", hn.reason);
    if (!state.hn) state.hnError = hn.reason;
  }
  render();
}

document.getElementById("today").textContent = new Intl.DateTimeFormat("ru-RU", {
  weekday: "long",
  day: "numeric",
  month: "long",
}).format(new Date());

window.addEventListener("hashchange", () => {
  render();
  window.scrollTo(0, 0);
});

setInterval(() => {
  if (document.visibilityState !== "visible") return;
  load();
  if (parseRoute(location.hash).view === "status") loadStatus();
}, REFRESH_MS);

render();
load();
