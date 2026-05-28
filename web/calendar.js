import { LOOKBACK_DAYS, localIsoDate } from "./date-utils.js";

const loggedColor = "#10bfdf";
const missedColor = "#c9c9cc";
const todayColor = "#77797d";
const formatMonth = new Intl.DateTimeFormat("en-US", { month: "short" });

function dayCountLabel(count) {
  return `${count} medication ${count === 1 ? "entry" : "entries"}`;
}

function renderMonthMarker(day, previousDay) {
  if (!previousDay || day.getMonth() === previousDay.getMonth()) return null;

  const marker = document.createElement("span");
  marker.className = "month-marker";
  marker.textContent = formatMonth.format(day).toUpperCase();
  return marker;
}

export function setCalendarSummary(summary, iso, count) {
  summary.textContent = `${iso}: ${dayCountLabel(count)}`;
}

export function renderCalendar({
  days,
  loggedDates,
  eventsByDate,
  selectedDate,
  onDateSelect,
  onMoveWindow,
}) {
  const grid = document.querySelector("#calendar-grid");
  const summary = document.querySelector("#calendar-hover-summary");
  const previousButton = document.querySelector("#calendar-previous");
  const nextButton = document.querySelector("#calendar-next");
  const todayIso = localIsoDate(new Date());

  previousButton.onclick = () => onMoveWindow(-LOOKBACK_DAYS);
  nextButton.onclick = () => onMoveWindow(LOOKBACK_DAYS);
  grid.replaceChildren();

  days.forEach((day, index) => {
    const iso = localIsoDate(day);
    const events = eventsByDate.get(iso) ?? [];
    const count = events.length;
    const cell = document.createElement("div");
    cell.className = "day-cell";
    cell.addEventListener("mouseenter", () => setCalendarSummary(summary, iso, count));
    cell.addEventListener("pointerenter", () => setCalendarSummary(summary, iso, count));
    if (index === 0) {
      cell.style.gridColumn = String(day.getDay() + 1);
    }

    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "day-marker";
    marker.textContent = String(day.getDate());
    marker.style.backgroundColor = loggedDates.has(iso) ? loggedColor : missedColor;
    marker.style.color = loggedDates.has(iso) ? "#ffffff" : "#707276";
    marker.title = `${iso}: ${dayCountLabel(count)}`;
    marker.setAttribute(
      "aria-label",
      `${iso}: ${loggedDates.has(iso) ? "selected medication logged" : "selected medication not logged"}, ${dayCountLabel(count)}`,
    );
    marker.setAttribute("aria-pressed", iso === selectedDate ? "true" : "false");
    marker.setAttribute("aria-expanded", iso === selectedDate ? "true" : "false");
    marker.addEventListener("mouseenter", () => setCalendarSummary(summary, iso, count));
    marker.addEventListener("pointerenter", () => setCalendarSummary(summary, iso, count));
    marker.addEventListener("focus", () => setCalendarSummary(summary, iso, count));
    marker.addEventListener("click", () => onDateSelect(iso));

    if (iso === todayIso) {
      marker.classList.add("is-today");
    }

    if (iso === selectedDate) {
      marker.classList.add("is-selected");
    }

    const markerText = renderMonthMarker(day, days[index - 1]);
    if (markerText) {
      cell.appendChild(markerText);
    }
    cell.appendChild(marker);
    grid.appendChild(cell);
  });

  if (selectedDate) {
    setCalendarSummary(summary, selectedDate, eventsByDate.get(selectedDate)?.length ?? 0);
  } else if (days.length > 0) {
    const lastDayIso = localIsoDate(days[days.length - 1]);
    setCalendarSummary(summary, lastDayIso, eventsByDate.get(lastDayIso)?.length ?? 0);
  }
}
