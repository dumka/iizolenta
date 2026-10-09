import {
  CATEGORIES,
  blockedHost,
  filterByCategory,
  formatTime,
  isSafeUrl,
  paragraphs,
  parseRoute,
  pickTopStory,
  pluralRu,
  postsStale,
  related,
} from "./lib.js";

const DATA_URL = "data/news.json";
const POSTS_URL = "data/posts.json";
const HN_URL = "data/hn.json";
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
  if (route.view === "x") {
    content = postsView();
  } else if (route.view === "hn") {
    content = discussionsView();
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

async function loadJson(url) {
  const cacheBust = Math.floor(Date.now() / 60000);
  const response = await fetch(`${url}?t=${cacheBust}`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  const data = await response.json();
  if (!Array.isArray(data?.items)) throw new Error(`${url}: items is not a list`);
  return data;
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
  if (document.visibilityState === "visible") load();
}, REFRESH_MS);

render();
load();
