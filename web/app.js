import {
  addDays,
  buildCalendarDays,
  displayDate,
  eventTimeLabel,
  localIsoDate,
  LOOKBACK_DAYS,
  parseEventDate,
} from "./date-utils.js";
import { renderCalendar } from "./calendar.js";

export const API_BASE = "/api";
export { addDays, buildCalendarDays, localIsoDate, LOOKBACK_DAYS, parseEventDate };

const userSelect = document.querySelector("#user-select");
const medicationSelect = document.querySelector("#medication-select");
const statusPanel = document.querySelector("#status-panel");
const medicationView = document.querySelector("#medication-view");
const refreshButton = document.querySelector("#refresh-button");

let users = [];
let medications = [];
let selectedMedication = null;
let calendarEndDate = new Date();
let selectedDate = null;

export async function fetchJson(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

export function setStatus(message, isError = false) {
  statusPanel.textContent = message;
  statusPanel.classList.toggle("is-error", isError);
  statusPanel.hidden = false;
}

export function showView() {
  statusPanel.hidden = true;
  medicationView.hidden = false;
}

export function setOptions(select, rows, getValue, getLabel) {
  select.replaceChildren(
    ...rows.map((row) => {
      const option = document.createElement("option");
      option.value = getValue(row);
      option.textContent = getLabel(row);
      return option;
    }),
  );
}

export function medicationKey(medication) {
  return medication.display_name;
}

export function doseLabel(medication) {
  const dose = medication.unit_mg ?? medication.dosage_mg;
  if (dose === null || dose === undefined || dose === "") return "Dose unknown";
  return `${Number(dose).toLocaleString("en-US", { maximumFractionDigits: 2 })} mg`;
}

async function fetchMedicationEvents(userId, params) {
  const limit = 500;
  const events = [];
  let offset = 0;

  while (true) {
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    const page = await fetchJson(`/users/${userId}/medication-events?${params}`);
    events.push(...page);
    if (page.length < limit) return events;
    offset += limit;
  }
}

function selectedMedicationName(event) {
  return event.nickname || event.medication;
}

export function groupEventsByDate(events) {
  const groups = new Map();
  events.forEach((event) => {
    const iso = parseEventDate(event.date_text);
    const dayEvents = groups.get(iso) ?? [];
    dayEvents.push(event);
    groups.set(iso, dayEvents);
  });
  return groups;
}

export function renderSelectedDay(eventsByDate, iso) {
  const section = document.querySelector("#selected-day-section");
  const title = document.querySelector("#selected-day-title");
  const list = document.querySelector("#selected-day-list");
  const events = [...(eventsByDate.get(iso) ?? [])].sort((left, right) =>
    left.date_text.localeCompare(right.date_text),
  );

  section.hidden = false;
  title.textContent = `Taken on ${displayDate(new Date(`${iso}T00:00:00`))}`;
  list.replaceChildren();

  if (events.length === 0) {
    const empty = document.createElement("p");
    empty.className = "selected-day-empty";
    empty.textContent = "No medications logged for this day.";
    list.appendChild(empty);
    return;
  }

  events.forEach((event) => {
    const item = document.createElement("li");
    item.className = "selected-day-item";

    const name = document.createElement("span");
    name.className = "selected-day-medication";
    name.textContent = selectedMedicationName(event);

    const time = document.createElement("span");
    time.className = "selected-day-time";
    time.textContent = eventTimeLabel(event.date_text);

    item.append(name, time);
    list.appendChild(item);
  });
}

function selectCalendarDate(iso, days, loggedDates, eventsByDate) {
  selectedDate = iso;
  renderSelectedDay(eventsByDate, iso);
  renderMedicationCalendar(days, loggedDates, eventsByDate);
}

function renderMedicationCalendar(days, loggedDates, eventsByDate) {
  renderCalendar({
    days,
    loggedDates,
    eventsByDate,
    selectedDate,
    onDateSelect: (iso) => selectCalendarDate(iso, days, loggedDates, eventsByDate),
    onMoveWindow: moveCalendarWindow,
  });
}

function moveCalendarWindow(days) {
  calendarEndDate = addDays(calendarEndDate, days);
  selectedDate = null;
  loadEvents().catch((error) => setStatus(error.message, true));
}

export async function loadEvents() {
  const userId = userSelect.value;
  const medicationName = medicationSelect.value;
  selectedMedication = medications.find((medication) => medicationKey(medication) === medicationName);
  if (!userId || !selectedMedication) return;

  setStatus("Loading selected medication...");
  medicationView.hidden = true;

  const endDate = calendarEndDate;
  const startDate = addDays(endDate, -(LOOKBACK_DAYS - 1));
  const params = new URLSearchParams({
    date_from: localIsoDate(startDate),
    date_to: `${localIsoDate(endDate)} 23:59:59`,
  });

  const events = await fetchMedicationEvents(userId, params);
  const loggedDates = new Set(
    events
      .filter((event) => selectedMedicationName(event) === medicationName)
      .map((event) => parseEventDate(event.date_text)),
  );
  const eventsByDate = groupEventsByDate(events);
  const days = buildCalendarDays(endDate);

  document.querySelector("#page-title").textContent = selectedMedication.display_name;
  document.querySelector("#nav-title").textContent = selectedMedication.display_name;
  document.querySelector("#highlight-name").textContent = selectedMedication.display_name;
  document.querySelector("#highlight-copy").textContent =
    `Here's a look at how you've logged ${selectedMedication.display_name} from ${displayDate(startDate)} to ${displayDate(endDate)}.`;
  document.querySelector("#detail-name").textContent = selectedMedication.display_name;
  document.querySelector("#detail-dose").textContent = doseLabel(selectedMedication);
  document.querySelector("#range-copy").textContent =
    `${loggedDates.size} of ${LOOKBACK_DAYS} days logged`;

  document.querySelector("#selected-day-section").hidden = true;
  renderMedicationCalendar(days, loggedDates, eventsByDate);
  showView();
}

export async function loadMedications() {
  const userId = userSelect.value;
  medications = await fetchJson(`/users/${userId}/medications`);
  if (medications.length === 0) {
    medicationSelect.replaceChildren();
    medicationView.hidden = true;
    setStatus("No imported medication events found for this user. Import a transformed CSV first.");
    return;
  }

  setOptions(medicationSelect, medications, medicationKey, (medication) => medication.display_name);
  calendarEndDate = new Date();
  selectedDate = null;
  await loadEvents();
}

export async function loadUsers() {
  setStatus("Loading users...");
  users = await fetchJson("/users");
  if (users.length === 0) {
    setStatus("No users found. Create a user and import medication events through the API first.");
    return;
  }
  setOptions(userSelect, users, (user) => String(user.id), (user) => user.name);
  await loadMedications();
}

export function startApp() {
  userSelect.addEventListener("change", () => {
    loadMedications().catch((error) => setStatus(error.message, true));
  });

  medicationSelect.addEventListener("change", () => {
    loadEvents().catch((error) => setStatus(error.message, true));
  });

  refreshButton.addEventListener("click", () => {
    loadEvents().catch((error) => setStatus(error.message, true));
  });

  loadUsers().catch((error) => setStatus(error.message, true));
}

if (!globalThis.__MEDS_SKIP_AUTO_START__) {
  startApp();
}
