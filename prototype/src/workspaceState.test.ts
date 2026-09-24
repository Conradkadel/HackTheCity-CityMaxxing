import { expect, it } from "vitest";
import { defaultFilters, filtersEqual, toggleValue } from "./workspaceState";
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
