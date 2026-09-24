import type { VehicleFilters, WorkspaceCatalog } from "./workspaceTypes";

export const toggleValue = (values: string[], value: string) =>
  values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];

export function timeToDayMinute(value: string, midnightAsEnd = false) {
  const [hours, minutes] = value.split(":").map(Number);
  if (midnightAsEnd && hours === 0 && minutes === 0) return 24 * 60;
  return hours * 60 + minutes;
}

export function dayMinuteToTime(value: number) {
  const normalized = Math.max(0, Math.min(24 * 60, Math.round(value)));
  if (normalized === 24 * 60) return "00:00";
  return `${String(Math.floor(normalized / 60)).padStart(2, "0")}:${String(normalized % 60).padStart(2, "0")}`;
}

export function centeredDayWindow(center: number, duration: number) {
  const safeDuration = Math.max(15, Math.min(4 * 60, duration));
  const roundedCenter = Math.round(center / 15) * 15;
  const start = Math.max(
    0,
    Math.min(24 * 60 - safeDuration, roundedCenter - safeDuration / 2),
  );
  return {
    start: dayMinuteToTime(start),
    end: dayMinuteToTime(start + safeDuration),
  };
}

export function windowDurationMinutes(startValue: string, endValue: string) {
  const start = timeToDayMinute(startValue);
  const end = timeToDayMinute(endValue);
  const duration = (end - start + 24 * 60) % (24 * 60);
  return duration || 24 * 60;
}

export function resizeDayWindow(startValue: string, duration: number) {
  const safeDuration = Math.max(15, Math.min(4 * 60, duration));
  const start = timeToDayMinute(startValue);
  return {
    start: dayMinuteToTime(start),
    end: dayMinuteToTime((start + safeDuration) % (24 * 60)),
  };
}

export function shiftDayWindow(
  startValue: string,
  endValue: string,
  direction: -1 | 1,
) {
  const duration = windowDurationMinutes(startValue, endValue);
  const start =
    (timeToDayMinute(startValue) + direction * duration + 24 * 60) % (24 * 60);
  return {
    start: dayMinuteToTime(start),
    end: dayMinuteToTime((start + duration) % (24 * 60)),
  };
}

export function defaultFilters(
  catalog: WorkspaceCatalog,
  start = "07:00",
  end = "09:00",
): VehicleFilters {
  const preset = catalog.presets.find(
    (item) => item.id === catalog.defaultPresetId,
  );
  const operators = (preset?.operators ?? [])
    .filter((item) => item.available)
    .map((item) => item.id);
  const lines = (preset?.lines ?? [])
    .filter((item) => item.vehicleAvailable)
    .map((item) => item.code);
  return {
    date: catalog.date,
    start,
    end,
    areas: catalog.areas.map((item) => item.id),
    operators: operators.length
      ? operators
      : catalog.operators.slice(0, 1).map((item) => item.id),
    lines,
    vehicleMode: "configured",
  };
}

export function filtersEqual(
  left: VehicleFilters | null,
  right: VehicleFilters,
) {
  if (!left) return false;
  const normalize = (values: string[]) => [...values].sort().join("\u0000");
  return (
    left.date === right.date &&
    left.start === right.start &&
    left.end === right.end &&
    left.vehicleMode === right.vehicleMode &&
    normalize(left.areas) === normalize(right.areas) &&
    normalize(left.operators) === normalize(right.operators) &&
    normalize(left.lines) === normalize(right.lines)
  );
}
