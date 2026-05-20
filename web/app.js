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

// View Containers
const landingPage = document.querySelector("#landing-page");
const calendarView = document.querySelector("#calendar-view");
const editView = document.querySelector("#edit-view");

// Selectors
const userSelect = document.querySelector("#user-select");
const medicationSelect = document.querySelector("#medication-select");
const statusPanel = document.querySelector("#status-panel");
const medicationView = document.querySelector("#medication-view");

// Buttons
const viewCalendarBtn = document.querySelector("#view-calendar-btn");
const viewEditBtn = document.querySelector("#view-edit-btn");
const userActions = document.querySelector("#user-actions");
const backToLandingFromCalendar = document.querySelector("#back-to-landing-from-calendar");
const backToLandingFromEdit = document.querySelector("#back-to-landing-from-edit");
const refreshButton = document.querySelector("#refresh-button");

// Labels
const calendarUserName = document.querySelector("#calendar-user-name");
const editUserName = document.querySelector("#edit-user-name");

const passwordModal = document.querySelector("#password-modal");
const passwordInput = document.querySelector("#password-input");
const passwordSubmitBtn = document.querySelector("#password-submit-btn");
const passwordCancelBtn = document.querySelector("#password-cancel-btn");
const passwordError = document.querySelector("#password-error");

let users = [];
let medications = [];
let selectedMedication = null;
let calendarEndDate = new Date();
let selectedDate = null;
let currentPendingViewId = null;
let isPasswordVerified = false;

// Cookie helper
function setCookie(name, value, days = 30) {
  const expires = new Date(Date.now() + days * 864e5).toUTCString();
  document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/`;
}

function getCookie(name) {
  return document.cookie.split("; ").reduce((r, v) => {
    const parts = v.split("=");
    return parts[0] === name ? decodeURIComponent(parts[1]) : r;
  }, "");
}

export async function fetchJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

export function setStatus(message, isError = false) {
  if (!message) {
    statusPanel.hidden = true;
    return;
  }
  statusPanel.textContent = message;
  statusPanel.classList.toggle("is-error", isError);
  statusPanel.hidden = false;
}

export function showMedicationView() {
  setStatus(null);
  medicationView.hidden = false;
}

export function setOptions(select, rows, getValue, getLabel) {
  const currentVal = select.value;
  select.replaceChildren();
  
  // Add placeholder for user select if needed
  if (select.id === "user-select") {
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.disabled = true;
    placeholder.selected = !currentVal;
    placeholder.textContent = "Choose a user...";
    select.appendChild(placeholder);
  }

  rows.forEach((row) => {
    const option = document.createElement("option");
    option.value = getValue(row);
    option.textContent = getLabel(row);
    select.appendChild(option);
  });
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

    const info = document.createElement("div");
    info.className = "selected-day-info";
    info.style.textAlign = "right";

    const time = document.createElement("span");
    time.className = "selected-day-time";
    time.textContent = eventTimeLabel(event.date_text);
    time.style.display = "block";

    const dosage = document.createElement("span");
    dosage.className = "selected-day-dosage";
    const doseVal = event.dosage_mg ?? (event.count * (event.unit_mg || 0));
    dosage.textContent = doseVal > 0 ? `${Number(doseVal).toLocaleString("en-US", { maximumFractionDigits: 2 })} mg` : "";
    dosage.style.fontSize = "13px";
    dosage.style.color = "var(--muted)";
    dosage.style.fontWeight = "600";

    info.append(time, dosage);
    item.append(name, info);
    list.appendChild(item);
  });
}

function hideSelectedDay() {
  const section = document.querySelector("#selected-day-section");
  const title = document.querySelector("#selected-day-title");
  const list = document.querySelector("#selected-day-list");

  selectedDate = null;
  section.hidden = true;
  title.textContent = "";
  list.replaceChildren();
}

function selectCalendarDate(iso, days, loggedDates, eventsByDate) {
  if (selectedDate === iso) {
    hideSelectedDay();
  } else {
    selectedDate = iso;
    renderSelectedDay(eventsByDate, iso);
  }
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
  hideSelectedDay();
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
  document.querySelector("#highlight-name").textContent = selectedMedication.display_name;
  document.querySelector("#highlight-copy").textContent =
    `Here's a look at how you've logged ${selectedMedication.display_name} from ${displayDate(startDate)} to ${displayDate(endDate)}.`;
  document.querySelector("#detail-name").textContent = selectedMedication.display_name;
  document.querySelector("#detail-dose").textContent = doseLabel(selectedMedication);
  document.querySelector("#range-copy").textContent =
    `${loggedDates.size} of ${LOOKBACK_DAYS} days logged`;

  hideSelectedDay();
  renderMedicationCalendar(days, loggedDates, eventsByDate);
  showMedicationView();
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
  users = await fetchJson("/users");
  setOptions(userSelect, users, (user) => String(user.id), (user) => user.name);
  
  const savedUserId = getCookie("selected_user_id");
  if (savedUserId && users.some(u => String(u.id) === savedUserId)) {
    userSelect.value = savedUserId;
    onUserSelected();
  }
}

function onUserSelected() {
  const userId = userSelect.value;
  if (!userId) {
    userActions.classList.add("hidden");
    return;
  }
  
  setCookie("selected_user_id", userId);
  const user = users.find(u => String(u.id) === userId);
  calendarUserName.textContent = user.name;
  editUserName.textContent = user.name;
  userActions.classList.remove("hidden");
  
  // Check if already verified via cookie
  const isPreviouslyVerified = getCookie(`auth_verified_${userId}`) === "true";
  isPasswordVerified = !user.has_password || isPreviouslyVerified;
}

function showPasswordModal(viewId) {
  currentPendingViewId = viewId;
  passwordModal.classList.remove("hidden");
  passwordInput.value = "";
  passwordError.classList.add("hidden");
  passwordInput.focus();
}

function hidePasswordModal() {
  passwordModal.classList.add("hidden");
  currentPendingViewId = null;
}

async function verifyAndSwitchView(viewId) {
  if (isPasswordVerified) {
    switchView(viewId);
    return;
  }
  showPasswordModal(viewId);
}

async function handlePasswordSubmit() {
  const userId = userSelect.value;
  const password = passwordInput.value;
  
  try {
    await fetchJson(`/users/${userId}/verify-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    
    // Set a verification cookie that lasts for the session (or 30 days as per current setCookie)
    setCookie(`auth_verified_${userId}`, "true");
    isPasswordVerified = true;
    hidePasswordModal();
    if (currentPendingViewId) {
      switchView(currentPendingViewId);
    }
  } catch (error) {
    passwordError.textContent = error.message.includes("401") 
      ? "Invalid password. Please try again." 
      : "Error verifying password.";
    passwordError.classList.remove("hidden");
  }
}

function switchView(viewId) {
  [landingPage, calendarView, editView].forEach(view => view.classList.add("hidden"));
  if (viewId === "landing") {
    landingPage.classList.remove("hidden");
    const userId = userSelect.value;
    const user = users.find(u => String(u.id) === userId);
    const isPreviouslyVerified = userId ? getCookie(`auth_verified_${userId}`) === "true" : false;
    isPasswordVerified = user ? (!user.has_password || isPreviouslyVerified) : false;
  } else if (viewId === "calendar") {
    calendarView.classList.remove("hidden");
    loadMedications().catch((error) => setStatus(error.message, true));
  } else if (viewId === "edit") {
    editView.classList.remove("hidden");
  }
}

export function startApp() {
  userSelect.addEventListener("change", onUserSelected);

  medicationSelect.addEventListener("change", () => {
    loadEvents().catch((error) => setStatus(error.message, true));
  });

  refreshButton.addEventListener("click", () => {
    loadEvents().catch((error) => setStatus(error.message, true));
  });

  viewCalendarBtn.addEventListener("click", () => verifyAndSwitchView("calendar"));
  viewEditBtn.addEventListener("click", () => verifyAndSwitchView("edit"));
  
  backToLandingFromCalendar.addEventListener("click", () => switchView("landing"));
  backToLandingFromEdit.addEventListener("click", () => switchView("landing"));

  passwordSubmitBtn.addEventListener("click", handlePasswordSubmit);
  passwordCancelBtn.addEventListener("click", hidePasswordModal);
  passwordInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") handlePasswordSubmit();
  });

  loadUsers().catch((error) => {
    landingPage.innerHTML = `<div class="status-panel is-error">${error.message}</div>`;
  });
}

if (!globalThis.__MEDS_SKIP_AUTO_START__) {
  startApp();
}
