import type { VehicleFilters, WorkspaceCatalog } from "./workspaceTypes";

export const toggleValue = (values: string[], value: string) =>
  values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];

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
