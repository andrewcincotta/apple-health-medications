export const API_BASE = "/api";
export const LOOKBACK_DAYS = 28;
const loggedColor = "#10bfdf";
const missedColor = "#c9c9cc";
const todayColor = "#77797d";

const userSelect = document.querySelector("#user-select");
const medicationSelect = document.querySelector("#medication-select");
const statusPanel = document.querySelector("#status-panel");
const medicationView = document.querySelector("#medication-view");
const refreshButton = document.querySelector("#refresh-button");

const formatMonth = new Intl.DateTimeFormat("en-US", { month: "short" });

let users = [];
let medications = [];
let selectedMedication = null;

export function localIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function addDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function parseEventDate(value) {
  return value.slice(0, 10);
}

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

export function buildCalendarDays(endDate) {
  const days = [];
  const startDate = addDays(endDate, -(LOOKBACK_DAYS - 1));
  for (let cursor = new Date(startDate); cursor <= endDate; cursor = addDays(cursor, 1)) {
    days.push(new Date(cursor));
  }
  return days;
}

export function renderMonthMarker(day, previousDay) {
  if (!previousDay || day.getMonth() === previousDay.getMonth()) return "";
  return `<span class="month-marker">${formatMonth.format(day).toUpperCase()}</span>`;
}

export function renderCalendar(days, loggedDates) {
  const grid = document.querySelector("#calendar-grid");
  const todayIso = localIsoDate(new Date());
  grid.replaceChildren();

  days.forEach((day, index) => {
    const iso = localIsoDate(day);
    const cell = document.createElement("div");
    cell.className = "day-cell";
    if (index === 0) {
      cell.style.gridColumn = String(day.getDay() + 1);
    }

    const marker = document.createElement("div");
    marker.className = "day-marker";
    marker.textContent = String(day.getDate());
    marker.style.backgroundColor = loggedDates.has(iso) ? loggedColor : missedColor;
    marker.style.color = loggedDates.has(iso) ? "#ffffff" : "#707276";
    marker.setAttribute("aria-label", `${iso}: ${loggedDates.has(iso) ? "logged" : "not logged"}`);

    if (iso === todayIso) {
      marker.classList.add("is-today");
      marker.style.boxShadow = `0 0 0 4px #f8f8fb, 0 0 0 8px ${todayColor}`;
    }

    const markerText = renderMonthMarker(day, days[index - 1]);
    if (markerText) {
      cell.insertAdjacentHTML("beforeend", markerText);
    }
    cell.appendChild(marker);
    grid.appendChild(cell);
  });
}

export async function loadEvents() {
  const userId = userSelect.value;
  const medicationName = medicationSelect.value;
  selectedMedication = medications.find((medication) => medicationKey(medication) === medicationName);
  if (!userId || !selectedMedication) return;

  setStatus("Loading selected medication...");
  medicationView.hidden = true;

  const endDate = new Date();
  const startDate = addDays(endDate, -(LOOKBACK_DAYS - 1));
  const params = new URLSearchParams({
    date_from: localIsoDate(startDate),
    date_to: localIsoDate(endDate),
    limit: "500",
  });
  if (selectedMedication.nickname) {
    params.set("nickname", selectedMedication.nickname);
  }

  const events = await fetchJson(`/users/${userId}/medication-events?${params}`);
  const loggedDates = new Set(
    events
      .filter((event) => (event.nickname || event.medication) === medicationName)
      .map((event) => parseEventDate(event.date_text)),
  );
  const days = buildCalendarDays(endDate);

  document.querySelector("#page-title").textContent = selectedMedication.display_name;
  document.querySelector("#nav-title").textContent = selectedMedication.display_name;
  document.querySelector("#highlight-name").textContent = selectedMedication.display_name;
  document.querySelector("#highlight-copy").textContent =
    `Here's a look at how you've logged ${selectedMedication.display_name} in the past 28 days.`;
  document.querySelector("#detail-name").textContent = selectedMedication.display_name;
  document.querySelector("#detail-dose").textContent = doseLabel(selectedMedication);
  document.querySelector("#range-copy").textContent =
    `${loggedDates.size} of ${LOOKBACK_DAYS} days logged`;

  renderCalendar(days, loggedDates);
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
