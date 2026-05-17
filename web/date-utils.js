export const LOOKBACK_DAYS = 28;

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

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

export function buildCalendarDays(endDate) {
  const days = [];
  const startDate = addDays(endDate, -(LOOKBACK_DAYS - 1));
  for (let cursor = new Date(startDate); cursor <= endDate; cursor = addDays(cursor, 1)) {
    days.push(new Date(cursor));
  }
  return days;
}

export function displayDate(date) {
  return dateFormatter.format(date);
}

export function eventTimeLabel(dateText) {
  const [hours, minutes] = dateText.slice(11, 16).split(":").map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return "Time unknown";

  const suffix = hours >= 12 ? "PM" : "AM";
  const hour = hours % 12 || 12;
  return `${hour}:${String(minutes).padStart(2, "0")} ${suffix}`;
}
