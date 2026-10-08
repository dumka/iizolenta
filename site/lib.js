// Pure helpers for the dashboard: routing, formatting, selection. No DOM here.

export const CATEGORIES = {
  ai: "ИИ и модели",
  dev: "Разработка",
  business: "Бизнес и стартапы",
};

export function parseRoute(hash) {
  const value = (hash || "").replace(/^#/, "");
  if (/^https?:\/\//i.test(value)) {
    return { view: "blocked", url: value };
  }
  const parts = value.replace(/^\//, "").split("/");
  if (parts[0] === "news" && parts[1]) {
    return { view: "article", id: parts[1] };
  }
  if (Object.hasOwn(CATEGORIES, parts[0])) {
    return { view: "category", category: parts[0] };
  }
  return { view: "home" };
}

export function blockedHost(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "") || null;
  } catch {
    return null;
  }
}

export function isSafeUrl(url) {
  if (typeof url !== "string" || !url) return false;
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

function calendarDate(date, timeZone) {
  // en-CA formats as YYYY-MM-DD
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

function previousDay(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day - 1)).toISOString().slice(0, 10);
}

export function formatTime(iso, now = new Date(), timeZone = undefined) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const time = new Intl.DateTimeFormat("ru-RU", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(date);
  const day = calendarDate(date, timeZone);
  const today = calendarDate(now, timeZone);
  if (day === today) return time;
  if (day === previousDay(today)) return `вчера, ${time}`;
  const dayMonth = new Intl.DateTimeFormat("ru-RU", { timeZone, day: "numeric", month: "long" }).format(date);
  return `${dayMonth}, ${time}`;
}

export function pickTopStory(items) {
  let top = null;
  for (const item of items) {
    if (
      !top ||
      item.importance > top.importance ||
      (item.importance === top.importance && item.published_at > top.published_at)
    ) {
      top = item;
    }
  }
  return top;
}

export function filterByCategory(items, category) {
  return items.filter((item) => item.category === category);
}

export function related(items, item, n) {
  return items.filter((other) => other.category === item.category && other.id !== item.id).slice(0, n);
}
