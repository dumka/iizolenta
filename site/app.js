import {
  CATEGORIES,
  blockedHost,
  filterByCategory,
  formatTime,
  isSafeUrl,
  parseRoute,
  pickTopStory,
  related,
} from "./lib.js";

const DATA_URL = "data/news.json";
const REFRESH_MS = 15 * 60 * 1000;
const LATEST_LIMIT = 30;
const IMPORTANT_LIMIT = 8;
const RELATED_LIMIT = 5;
const SITE_TITLE = "ИИзоЛента — новости AI и IT";

const app = document.getElementById("app");
const state = { data: null, error: null, blockedHost: null };

// Build DOM nodes; strings become text nodes, so feed data never turns into markup.
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
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

function feedView(items, title) {
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
  const active = route.view === "category" ? route.category : "";
  for (const link of document.querySelectorAll(".menu__link")) {
    link.classList.toggle("is-active", route.view !== "article" && link.dataset.category === active);
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
  if (state.error) {
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
    content = feedView(state.data.items, null);
  }
  app.replaceChildren(...[banner(), content].flat().filter(Boolean));
}

async function load() {
  try {
    const cacheBust = Math.floor(Date.now() / 60000);
    const response = await fetch(`${DATA_URL}?t=${cacheBust}`, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data?.items)) throw new Error("news.json: items is not a list");
    state.data = data;
    state.error = null;
  } catch (error) {
    console.error("ИИзоЛента: не удалось загрузить новости", error);
    // keep showing stale data if we already have some
    if (!state.data) state.error = error;
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
  if (document.visibilityState === "visible") load();
}, REFRESH_MS);

render();
load();
