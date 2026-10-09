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
  if (["x", "hn", "habr", "status"].includes(parts[0]) && parts.length === 1) {
    return { view: parts[0] };
  }
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

const TOP_STORY_WINDOWS_HOURS = [12, 24];

function mostImportant(items) {
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

// The top story is the most important one of the last 12 hours (then 24 hours), not of the whole week:
// otherwise a single big story would stay on top for days.
export function pickTopStory(items, now = new Date()) {
  for (const hours of TOP_STORY_WINDOWS_HOURS) {
    const since = now.getTime() - hours * 3600 * 1000;
    const recent = items.filter((item) => new Date(item.published_at).getTime() >= since);
    if (recent.length) return mostImportant(recent);
  }
  let freshest = null;
  for (const item of items) {
    if (!freshest || item.published_at > freshest.published_at) freshest = item;
  }
  return freshest;
}

export function filterByCategory(items, category) {
  return items.filter((item) => item.category === category);
}

export function related(items, item, n) {
  return items.filter((other) => other.category === item.category && other.id !== item.id).slice(0, n);
}

const STALE_POSTS_HOURS = 48;

// True when there is nothing fresh to show in the posts block.
export function postsStale(items, now = new Date(), hours = STALE_POSTS_HOURS) {
  const newest = Math.max(...items.map((item) => new Date(item.published_at).getTime()).filter(Number.isFinite));
  return !Number.isFinite(newest) || now.getTime() - newest > hours * 3600 * 1000;
}

export function paragraphs(text) {
  return (text || "")
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean);
}

// Russian plural: pluralRu(5, ["комментарий", "комментария", "комментариев"]) -> "комментариев"
export function pluralRu(n, [one, few, many]) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

// Status page (#/status): what the pipeline did with every source and material over the last 48 hours.

const PROBLEM_OUTCOMES = new Set(["invalid", "missing", "failed"]);
const KIND_BY_MATERIAL = { article: "feed", habr: "feed", post: "x", discussion: "hn" };

export function outcomeGroup(outcome) {
  return PROBLEM_OUTCOMES.has(outcome) ? "problems" : outcome;
}

// One row per source: the status of its newest run plus totals over the whole status window.
// Failing sources go first.
export function summarizeSources(status) {
  const rows = new Map();
  const row = (name, kind) => {
    if (!rows.has(name)) {
      rows.set(name, {
        name, kind, ok: null, error: null, entries: null, candidates: null, selected: null,
        selectedTotal: 0, published: 0, skipped: 0, problems: 0,
      });
    }
    return rows.get(name);
  };
  const runs = [...(status?.runs || [])].sort((a, b) => String(a.merged_at).localeCompare(String(b.merged_at)));
  for (const run of runs) {
    for (const source of run.sources || []) {
      const r = row(source.name, source.kind);
      // runs go oldest first, so the newest run has the last word
      Object.assign(r, {
        kind: source.kind,
        ok: source.ok,
        error: source.error ?? null,
        entries: source.entries,
        candidates: source.candidates,
        selected: source.selected,
      });
      r.selectedTotal += source.selected || 0;
    }
  }
  for (const material of status?.materials || []) {
    const r = row(material.source, KIND_BY_MATERIAL[material.kind] || null);
    const group = outcomeGroup(material.outcome);
    if (group in r && group !== "selected") r[group] += 1;
  }
  return [...rows.values()].sort((a, b) => {
    if ((a.ok === false) !== (b.ok === false)) return a.ok === false ? -1 : 1;
    return a.name.localeCompare(b.name, "ru");
  });
}

// filter: all | published | skipped | problems (invalid, missing, failed)
export function filterMaterials(materials, filter) {
  if (filter === "all") return materials;
  return materials.filter((material) => outcomeGroup(material.outcome) === filter);
}

export function countOutcomes(materials) {
  const counts = { all: materials.length, published: 0, skipped: 0, problems: 0 };
  for (const material of materials) {
    const group = outcomeGroup(material.outcome);
    if (group in counts && group !== "all") counts[group] += 1;
  }
  return counts;
}
