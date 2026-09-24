import { expect, it } from "vitest";
import {
  centeredDayWindow,
  dayMinuteToTime,
  defaultFilters,
  filtersEqual,
  resizeDayWindow,
  shiftDayWindow,
  timeToDayMinute,
  toggleValue,
  windowDurationMinutes,
} from "./workspaceState";
import type { WorkspaceCatalog } from "./workspaceTypes";

const catalog = {
  date: "2026-09-01",
  defaultPresetId: "carris_lisbon",
  areas: [{ id: "eyckp" }, { id: "eycs2" }],
  operators: [{ id: "IA9T6" }],
  presets: [
    {
      id: "carris_lisbon",
      operators: [{ id: "IA9T6", available: true }],
      lines: [
        { code: "755", vehicleAvailable: true },
        { code: "702", vehicleAvailable: false },
      ],
    },
  ],
} as WorkspaceCatalog;

it("moves a bounded zoom window across the full day", () => {
  expect(centeredDayWindow(8 * 60, 120)).toEqual({
    start: "07:00",
    end: "09:00",
  });
  expect(centeredDayWindow(15, 120)).toEqual({
    start: "00:00",
    end: "02:00",
  });
  expect(centeredDayWindow(24 * 60, 240)).toEqual({
    start: "20:00",
    end: "00:00",
  });
  expect(timeToDayMinute("00:00", true)).toBe(24 * 60);
  expect(dayMinuteToTime(24 * 60)).toBe("00:00");
});

it("enables every available area and configured line by default", () => {
  const filters = defaultFilters(catalog);
  expect(filters.areas).toEqual(["eyckp", "eycs2"]);
  expect(filters.operators).toEqual(["IA9T6"]);
  expect(filters.lines).toEqual(["755"]);
});

it("compares filters without depending on selection order", () => {
  const filters = defaultFilters(catalog);
  expect(
    filtersEqual({ ...filters, areas: [...filters.areas].reverse() }, filters),
  ).toBe(true);
  expect(filtersEqual({ ...filters, vehicleMode: "all" }, filters)).toBe(false);
});

it("toggles without mutating the original list", () => {
  const original = ["a"];
  expect(toggleValue(original, "b")).toEqual(["a", "b"]);
  expect(toggleValue(original, "a")).toEqual([]);
  expect(original).toEqual(["a"]);
});

it("resizes and shifts replay windows, including across midnight", () => {
  expect(resizeDayWindow("07:30", 60)).toEqual({
    start: "07:30",
    end: "08:30",
  });
  expect(shiftDayWindow("23:00", "01:00", 1)).toEqual({
    start: "01:00",
    end: "03:00",
  });
  expect(shiftDayWindow("00:30", "02:30", -1)).toEqual({
    start: "22:30",
    end: "00:30",
  });
  expect(windowDurationMinutes("23:00", "01:00")).toBe(120);
});
