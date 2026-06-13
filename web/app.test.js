import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

const ELEMENT_IDS = [
  "user-select",
  "medication-select",
  "status-panel",
  "medication-view",
  "refresh-button",
  "calendar-previous",
  "calendar-next",
  "calendar-hover-summary",
  "calendar-grid",
  "selected-day-section",
  "selected-day-title",
  "selected-day-list",
  "page-title",
  "nav-title",
  "highlight-name",
  "highlight-copy",
  "detail-name",
  "detail-dose",
  "range-copy",
  "landing-page",
  "calendar-view",
  "edit-view",
  "view-calendar-btn",
  "view-edit-btn",
  "user-actions",
  "back-to-landing-from-calendar",
  "back-to-landing-from-edit",
  "sync-meds-btn",
  "managed-meds-list",
  "calendar-user-name",
  "edit-user-name",
  "password-modal",
  "password-input",
  "password-submit-btn",
  "password-cancel-btn",
  "password-error",
];

class FakeClassList {
  constructor() {
    this.names = new Set();
  }

  add(name) {
    this.names.add(name);
  }

  toggle(name, force) {
    if (force) {
      this.names.add(name);
      return true;
    }
    this.names.delete(name);
    return false;
  }

  contains(name) {
    return this.names.has(name);
  }
}

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.classList = new FakeClassList();
    this.style = {};
    this.hidden = false;
    this.textContent = "";
    this.value = "";
  }

  addEventListener(type, listener) {
    this[`on${type}`] = listener;
  }

  click() {
    this.onclick?.();
  }

  appendChild(child) {
    this.children.push(child);
    if (this.tagName === "SELECT" && !this.value) {
      this.value = child.value;
    }
    return child;
  }

  append(...children) {
    this.children.push(...children);
  }

  insertAdjacentHTML(_position, html) {
    const child = new FakeElement("span");
    child.innerHTML = html;
    this.children.push(child);
  }

  replaceChildren(...children) {
    this.children = children;
    if (this.tagName === "SELECT") {
      this.value = children[0]?.value ?? "";
    }
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  getAttribute(name) {
    return this.attributes.get(name);
  }
}

function setupDom() {
  const elements = new Map(
    ELEMENT_IDS.map((id) => {
      const tag = id.endsWith("-select") ? "select" : "div";
      return [id, new FakeElement(tag)];
    }),
  );

  globalThis.document = {
    cookie: "",
    createElement: (tagName) => new FakeElement(tagName),
    querySelector: (selector) => {
      const id = selector.startsWith("#") ? selector.slice(1) : selector;
      const element = elements.get(id);
      if (!element) throw new Error(`Missing fake element for selector ${selector}`);
      return element;
    },
  };

  return elements;
}

async function importApp() {
  globalThis.__MEDS_SKIP_AUTO_START__ = true;
  return import(`./app.js?test=${Date.now()}-${Math.random()}`);
}

beforeEach(() => {
  setupDom();
});

afterEach(() => {
  delete globalThis.document;
  delete globalThis.fetch;
  delete globalThis.__MEDS_SKIP_AUTO_START__;
});

test("fetchJson sends web UI requests through the nginx /api proxy path", async () => {
  const seenUrls = [];
  globalThis.fetch = async (url) => {
    seenUrls.push(url);
    return {
      ok: true,
      json: async () => [{ id: 1, name: "Andrew" }],
    };
  };

  const { fetchJson } = await importApp();
  const data = await fetchJson("/users");

  assert.deepEqual(data, [{ id: 1, name: "Andrew" }]);
  assert.deepEqual(seenUrls, ["/api/users"]);
});

test("loadUsers renders medication detail data from users, medications, and events endpoints", async () => {
  const elements = setupDom();
  const seenUrls = [];
  globalThis.fetch = async (url) => {
    seenUrls.push(url);
    if (url === "/api/users") {
      return response([{ id: 1, name: "Andrew" }]);
    }
    if (url === "/api/users/1/medications") {
      return response([
        {
          medication: "clonazepam 0.5 MG Oral Tablet",
          nickname: "Klonopin",
          unit_mg: 0.5,
          dosage_mg: 0.5,
          display_name: "Klonopin",
        },
      ]);
    }
    if (url.startsWith("/api/users/1/medication-events?")) {
      return response([
        {
          medication: "clonazepam 0.5 MG Oral Tablet",
          nickname: "Klonopin",
          date_text: "2026-05-15 08:00:00 -0400",
        },
      ]);
    }
    throw new Error(`Unexpected URL ${url}`);
  };

  const { loadUsers, loadMedications } = await importApp();
  await loadUsers();
  elements.get("user-select").value = "1";
  await loadMedications();

  assert.equal(elements.get("page-title").textContent, "Klonopin");
  assert.equal(elements.get("detail-name").textContent, "Klonopin");
  assert.equal(elements.get("detail-dose").textContent, "0.5 mg");
  assert.equal(elements.get("medication-view").hidden, false);
  assert.equal(elements.get("status-panel").hidden, true);

  const eventsUrl = new URL(seenUrls[2], "http://example.test");
  assert.deepEqual(seenUrls.slice(0, 2), ["/api/users", "/api/users/1/medications"]);
  assert.equal(eventsUrl.pathname, "/api/users/1/medication-events");
  assert.equal(eventsUrl.searchParams.get("limit"), "500");
  assert.equal(eventsUrl.searchParams.has("nickname"), false);
  assert.match(eventsUrl.searchParams.get("date_from"), /^\d{4}-\d{2}-\d{2}$/);
  assert.match(eventsUrl.searchParams.get("date_to"), /^\d{4}-\d{2}-\d{2} 23:59:59$/);
});

test("loadUsers queries raw medication events when the selected medication has no nickname", async () => {
  const seenUrls = [];
  globalThis.fetch = async (url) => {
    seenUrls.push(url);
    if (url === "/api/users") return response([{ id: 1, name: "Andrew" }]);
    if (url === "/api/users/1/medications") {
      return response([
        {
          medication: "Unmapped Supplement",
          nickname: null,
          unit_mg: null,
          dosage_mg: null,
          display_name: "Unmapped Supplement",
        },
      ]);
    }
    if (url.startsWith("/api/users/1/medication-events?")) {
      return response([
        {
          medication: "Unmapped Supplement",
          nickname: null,
          date_text: "2026-05-15 08:00:00 -0400",
        },
      ]);
    }
    throw new Error(`Unexpected URL ${url}`);
  };

  const elements = setupDom();
  const { loadUsers, loadMedications } = await importApp();
  await loadUsers();
  elements.get("user-select").value = "1";
  await loadMedications();

  const eventsUrl = new URL(seenUrls[2], "http://example.test");
  assert.equal(eventsUrl.pathname, "/api/users/1/medication-events");
  assert.equal(eventsUrl.searchParams.has("nickname"), false);
});

test("loadUsers surfaces API detail errors in the status panel", async () => {
  const elements = setupDom();
  globalThis.fetch = async () => ({
    ok: false,
    text: async () => '{"detail":"Not Found"}',
  });

  const { loadUsers, setStatus } = await importApp();
  await loadUsers().catch((error) => setStatus(error.message, true));

  assert.equal(elements.get("status-panel").textContent, '{"detail":"Not Found"}');
  assert.equal(elements.get("status-panel").classList.contains("is-error"), true);
});

test("renderSelectedDay displays every medication taken on the selected date", async () => {
  const elements = setupDom();
  const { groupEventsByDate, renderSelectedDay } = await importApp();
  const eventsByDate = groupEventsByDate([
    {
      medication: "clonazepam 0.5 MG Oral Tablet",
      nickname: "Klonopin",
      date_text: "2026-05-15 20:30:00 -0400",
    },
    {
      medication: "lisdexamfetamine 50 MG Oral Capsule",
      nickname: "Vyvanse",
      date_text: "2026-05-15 08:00:00 -0400",
    },
    {
      medication: "Vitamin D",
      nickname: null,
      date_text: "2026-05-16 09:00:00 -0400",
    },
  ]);

  renderSelectedDay(eventsByDate, "2026-05-15");

  const section = elements.get("selected-day-section");
  const list = elements.get("selected-day-list");
  assert.equal(section.hidden, false);
  assert.equal(elements.get("selected-day-title").textContent, "Taken on May 15, 2026");
  assert.equal(list.children.length, 2);
  assert.equal(list.children[0].children[0].textContent, "Vyvanse");
  assert.equal(list.children[0].children[1].children[0].textContent, "8:00 AM");
  assert.equal(list.children[1].children[0].textContent, "Klonopin");
  assert.equal(list.children[1].children[1].children[0].textContent, "8:30 PM");
});

test("calendar date buttons toggle the selected day summary", async () => {
  const elements = setupDom();
  const today = new Date();
  const todayIso = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");

  globalThis.fetch = async (url) => {
    if (url === "/api/users") return response([{ id: 1, name: "Andrew" }]);
    if (url === "/api/users/1/medications") {
      return response([
        {
          medication: "lisdexamfetamine 50 MG Oral Capsule",
          nickname: "Vyvanse",
          unit_mg: 50,
          dosage_mg: 50,
          display_name: "Vyvanse",
        },
      ]);
    }
    if (url.startsWith("/api/users/1/medication-events?")) {
      return response([
        {
          medication: "lisdexamfetamine 50 MG Oral Capsule",
          nickname: "Vyvanse",
          date_text: `${todayIso} 08:00:00 -0400`,
        },
        {
          medication: "Vitamin D",
          nickname: null,
          date_text: `${todayIso} 09:00:00 -0400`,
        },
      ]);
    }
    throw new Error(`Unexpected URL ${url}`);
  };

  const { loadUsers, loadMedications } = await importApp();
  await loadUsers();
  elements.get("user-select").value = "1";
  await loadMedications();

  const marker = findElement(
    elements.get("calendar-grid"),
    (element) => element.tagName === "BUTTON" && element.textContent === String(today.getDate()),
  );

  marker.onmouseenter();
  assert.equal(elements.get("calendar-hover-summary").textContent, `${todayIso}: 2 medication entries`);

  marker.click();
  assert.equal(elements.get("selected-day-section").hidden, false);
  assert.equal(elements.get("selected-day-list").children.length, 2);

  marker.click();
  assert.equal(elements.get("selected-day-section").hidden, true);
  assert.equal(elements.get("selected-day-list").children.length, 0);
});

test("calendar arrow buttons move the visible 28 day window", async () => {
  const elements = setupDom();
  const seenEventUrls = [];
  globalThis.fetch = async (url) => {
    if (url === "/api/users") return response([{ id: 1, name: "Andrew" }]);
    if (url === "/api/users/1/medications") {
      return response([
        {
          medication: "lisdexamfetamine 50 MG Oral Capsule",
          nickname: "Vyvanse",
          unit_mg: 50,
          dosage_mg: 50,
          display_name: "Vyvanse",
        },
      ]);
    }
    if (url.startsWith("/api/users/1/medication-events?")) {
      seenEventUrls.push(url);
      return response([]);
    }
    throw new Error(`Unexpected URL ${url}`);
  };

  const { loadUsers, loadMedications } = await importApp();
  await loadUsers();
  elements.get("user-select").value = "1";
  await loadMedications();

  elements.get("calendar-previous").click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(seenEventUrls.length, 2);
  const first = new URL(seenEventUrls[0], "http://example.test");
  const second = new URL(seenEventUrls[1], "http://example.test");
  assert.notEqual(second.searchParams.get("date_from"), first.searchParams.get("date_from"));
  assert.notEqual(second.searchParams.get("date_to"), first.searchParams.get("date_to"));
});

function findElement(root, predicate) {
  if (predicate(root)) return root;
  for (const child of root.children) {
    const match = findElement(child, predicate);
    if (match) return match;
  }
  return null;
}

function response(payload) {
  return {
    ok: true,
    json: async () => payload,
  };
}
