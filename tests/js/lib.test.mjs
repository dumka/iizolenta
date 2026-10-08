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
  test("highest importance wins", () => {
    const items = [news("a", { importance: 1 }), news("b", { importance: 3 }), news("c", { importance: 2 })];
    assert.equal(pickTopStory(items).id, "b");
  });

  test("freshest among equal importance", () => {
    const items = [
      news("old", { importance: 3, published_at: "2026-10-08T08:00:00Z" }),
      news("new", { importance: 3, published_at: "2026-10-08T11:00:00Z" }),
    ];
    assert.equal(pickTopStory(items).id, "new");
  });

  test("empty list is null", () => {
    assert.equal(pickTopStory([]), null);
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
