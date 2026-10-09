import assert from "node:assert/strict";
import { describe, test } from "node:test";

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
} from "../../site/lib.js";

const TZ = "Europe/Moscow";
const NOW = new Date("2026-10-08T12:00:00Z");

function news(id, overrides = {}) {
  return {
    id,
    category: "ai",
    importance: 1,
    published_at: "2026-10-08T10:00:00Z",
    ...overrides,
  };
}

describe("parseRoute", () => {
  for (const hash of ["", "#", "#/"]) {
    test(`home for ${JSON.stringify(hash)}`, () => {
      assert.deepEqual(parseRoute(hash), { view: "home" });
    });
  }

  test("category", () => {
    assert.deepEqual(parseRoute("#/dev"), { view: "category", category: "dev" });
  });

  test("unknown category falls back to home", () => {
    assert.deepEqual(parseRoute("#/sport"), { view: "home" });
  });

  test("article", () => {
    assert.deepEqual(parseRoute("#/news/92be971aec513c1f"), {
      view: "article",
      id: "92be971aec513c1f",
    });
  });

  test("blocked url from LeechBlock keeps query string intact", () => {
    assert.deepEqual(parseRoute("#https://lenta.ru/news/x/?a=1&b=2"), {
      view: "blocked",
      url: "https://lenta.ru/news/x/?a=1&b=2",
    });
  });

  test("blocked http url", () => {
    assert.deepEqual(parseRoute("#http://lenta.ru/"), { view: "blocked", url: "http://lenta.ru/" });
  });

  test("blocked url keeps its own fragment", () => {
    assert.deepEqual(parseRoute("#https://lenta.ru/x#comments"), {
      view: "blocked",
      url: "https://lenta.ru/x#comments",
    });
  });
});

describe("blockedHost", () => {
  test("strips www", () => {
    assert.equal(blockedHost("https://www.lenta.ru/x"), "lenta.ru");
  });

  test("keeps other subdomains", () => {
    assert.equal(blockedHost("https://m.lenta.ru/news"), "m.lenta.ru");
  });

  test("garbage is null", () => {
    assert.equal(blockedHost("not a url"), null);
  });
});

describe("isSafeUrl", () => {
  test("http and https are safe", () => {
    assert.equal(isSafeUrl("https://techcrunch.com/a"), true);
    assert.equal(isSafeUrl("http://example.com/"), true);
  });

  for (const bad of ["javascript:alert(1)", "data:text/html,hi", "//evil.example/x", "", null]) {
    test(`unsafe: ${JSON.stringify(bad)}`, () => {
      assert.equal(isSafeUrl(bad), false);
    });
  }
});

describe("formatTime", () => {
  test("today shows only time in the given zone", () => {
    assert.equal(formatTime("2026-10-08T11:05:00Z", NOW, TZ), "14:05");
  });

  test("after local midnight counts as today even if UTC date is yesterday", () => {
    assert.equal(formatTime("2026-10-07T22:30:00Z", NOW, TZ), "01:30");
  });

  test("yesterday", () => {
    assert.equal(formatTime("2026-10-07T18:00:00Z", NOW, TZ), "вчера, 21:00");
  });

  test("older dates use genitive month", () => {
    assert.equal(formatTime("2026-10-06T07:15:00Z", NOW, TZ), "6 октября, 10:15");
    assert.equal(formatTime("2026-09-30T07:15:00Z", NOW, TZ), "30 сентября, 10:15");
  });

  test("missing date is empty string", () => {
    assert.equal(formatTime(null, NOW, TZ), "");
  });
});

describe("pickTopStory", () => {
  // NOW = 2026-10-08T12:00Z; news() defaults to 10:00Z (2 hours ago)
  test("highest importance wins within the window", () => {
    const items = [news("a", { importance: 1 }), news("b", { importance: 3 }), news("c", { importance: 2 })];
    assert.equal(pickTopStory(items, NOW).id, "b");
  });

  test("freshest among equal importance", () => {
    const items = [
      news("old", { importance: 3, published_at: "2026-10-08T08:00:00Z" }),
      news("new", { importance: 3, published_at: "2026-10-08T11:00:00Z" }),
    ];
    assert.equal(pickTopStory(items, NOW).id, "new");
  });

  test("an old top story gives way to a fresher less important one", () => {
    const items = [
      news("gpt6-yesterday", { importance: 3, published_at: "2026-10-06T22:00:00Z" }),
      news("fresh", { importance: 2, published_at: "2026-10-08T11:00:00Z" }),
    ];
    assert.equal(pickTopStory(items, NOW).id, "fresh");
  });

  test("story older than 12h loses to anything inside 12h", () => {
    const items = [
      news("13h-ago", { importance: 3, published_at: "2026-10-07T23:00:00Z" }),
      news("1h-ago", { importance: 1, published_at: "2026-10-08T11:00:00Z" }),
    ];
    assert.equal(pickTopStory(items, NOW).id, "1h-ago");
  });

  test("quiet night: falls back to the best of the last 24h", () => {
    const items = [
      news("20h-ago-important", { importance: 3, published_at: "2026-10-07T16:00:00Z" }),
      news("18h-ago", { importance: 1, published_at: "2026-10-07T18:00:00Z" }),
      news("3-days-ago", { importance: 3, published_at: "2026-10-05T12:00:00Z" }),
    ];
    assert.equal(pickTopStory(items, NOW).id, "20h-ago-important");
  });

  test("nothing in 24h: the freshest story", () => {
    const items = [
      news("older", { importance: 3, published_at: "2026-10-05T12:00:00Z" }),
      news("newer", { importance: 1, published_at: "2026-10-06T12:00:00Z" }),
    ];
    assert.equal(pickTopStory(items, NOW).id, "newer");
  });

  test("empty list is null", () => {
    assert.equal(pickTopStory([], NOW), null);
  });
});

describe("filterByCategory and related", () => {
  const items = [
    news("a1", { category: "ai" }),
    news("d1", { category: "dev" }),
    news("a2", { category: "ai" }),
    news("a3", { category: "ai" }),
  ];

  test("filterByCategory keeps only the category", () => {
    assert.deepEqual(filterByCategory(items, "ai").map((i) => i.id), ["a1", "a2", "a3"]);
  });

  test("related excludes the item itself and other categories", () => {
    assert.deepEqual(related(items, items[0], 5).map((i) => i.id), ["a2", "a3"]);
  });

  test("related respects the limit", () => {
    assert.deepEqual(related(items, items[0], 1).map((i) => i.id), ["a2"]);
  });

  test("categories have Russian labels", () => {
    assert.deepEqual(Object.keys(CATEGORIES), ["ai", "dev", "business"]);
    assert.equal(CATEGORIES.ai, "ИИ и модели");
  });
});

describe("posts", () => {
  test("route #/x", () => {
    assert.deepEqual(parseRoute("#/x"), { view: "x" });
  });

  test("postsStale: empty list is stale", () => {
    assert.equal(postsStale([], NOW), true);
  });

  test("postsStale: fresh newest post is not stale", () => {
    const items = [{ published_at: "2026-10-06T13:00:00Z" }, { published_at: "2026-10-08T11:00:00Z" }];
    assert.equal(postsStale(items, NOW), false);
  });

  test("postsStale: newest post older than 48h is stale", () => {
    assert.equal(postsStale([{ published_at: "2026-10-06T11:59:00Z" }], NOW), true);
  });

  test("paragraphs splits on blank lines and drops empty ones", () => {
    assert.deepEqual(paragraphs("Первый абзац.\n\n\n Второй абзац. \n\n"), ["Первый абзац.", "Второй абзац."]);
  });

  test("paragraphs of empty text is empty", () => {
    assert.deepEqual(paragraphs(""), []);
  });
});

describe("hn", () => {
  test("route #/hn", () => {
    assert.deepEqual(parseRoute("#/hn"), { view: "hn" });
  });

  const comments = ["комментарий", "комментария", "комментариев"];
  const cases = [
    [1, "комментарий"], [2, "комментария"], [4, "комментария"], [5, "комментариев"],
    [11, "комментариев"], [12, "комментариев"], [14, "комментариев"], [21, "комментарий"],
    [22, "комментария"], [111, "комментариев"], [0, "комментариев"],
  ];
  for (const [n, form] of cases) {
    test(`pluralRu ${n}`, () => {
      assert.equal(pluralRu(n, comments), form);
    });
  }
});

describe("status page", async () => {
  const { countOutcomes, filterMaterials, summarizeSources } = await import("../../site/lib.js");

  const run = (merged_at, sources) => ({ merged_at, collected_at: merged_at, sources, result: {} });
  const src = (name, overrides = {}) => ({
    name, kind: "feed", ok: true, error: null, entries: 10, candidates: 3, selected: 2, ...overrides,
  });
  const material = (id, source, outcome) => ({ id, source, outcome, kind: "article" });

  test("route #/status", () => {
    assert.deepEqual(parseRoute("#/status"), { view: "status" });
  });

  test("summarizeSources: last status from the newest run, totals over all runs and materials", () => {
    const status = {
      runs: [
        run("2026-10-08T10:00:00Z", [src("A", { ok: false, error: "HTTP 403", selected: 0 }), src("B")]),
        run("2026-10-08T11:00:00Z", [src("A", { selected: 3 }), src("B", { ok: false, error: "timeout", selected: 0 })]),
      ],
      materials: [
        material("1", "A", "published"), material("2", "A", "skipped"), material("3", "A", "missing"),
        material("4", "B", "failed"), material("5", "C", "published"),
      ],
    };
    const rows = summarizeSources(status);
    assert.deepEqual(rows.map((r) => r.name), ["B", "A", "C"]); // failing first, then by name
    const [b, a, c] = rows;
    assert.equal(b.ok, false);
    assert.equal(b.error, "timeout");
    assert.equal(a.ok, true);
    assert.equal(a.error, null);
    assert.equal(a.selected, 3); // last run
    assert.equal(a.selectedTotal, 3); // 0 (feed failed) + 3 over 48h
    assert.equal(b.selectedTotal, 2); // 2 + 0 (feed failed)
    assert.deepEqual([a.published, a.skipped, a.problems], [1, 1, 1]);
    assert.deepEqual([b.published, b.skipped, b.problems], [0, 0, 1]);
    assert.equal(c.ok, null); // known only from materials: no run stats
  });

  test("summarizeSources tolerates missing runs and materials", () => {
    assert.deepEqual(summarizeSources({}), []);
  });

  const materials = [
    material("1", "A", "published"), material("2", "A", "skipped"), material("3", "A", "invalid"),
    material("4", "A", "missing"), material("5", "A", "failed"),
  ];

  test("filterMaterials by outcome group", () => {
    assert.deepEqual(filterMaterials(materials, "all").map((m) => m.id), ["1", "2", "3", "4", "5"]);
    assert.deepEqual(filterMaterials(materials, "published").map((m) => m.id), ["1"]);
    assert.deepEqual(filterMaterials(materials, "skipped").map((m) => m.id), ["2"]);
    assert.deepEqual(filterMaterials(materials, "problems").map((m) => m.id), ["3", "4", "5"]);
  });

  test("countOutcomes", () => {
    assert.deepEqual(countOutcomes(materials), { all: 5, published: 1, skipped: 1, problems: 3 });
  });
});
