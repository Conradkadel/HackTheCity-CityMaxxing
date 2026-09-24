import { validate, type Dataset } from "./replay";
import type {
  BunchingWeek,
  BunchingWeekSummary,
  LineDay,
  VehicleDay,
  VehicleFilters,
  WorkspaceCatalog,
} from "./workspaceTypes";

export type Selection = VehicleFilters & {
  preview?: boolean;
  datasetVersion?: number;
};

export function queryFor(selection: Selection) {
  const params = new URLSearchParams({
    date: selection.date,
    start: selection.start,
    end: selection.end,
  });
  if (selection.preview) {
    params.set("preview", "true");
    if (selection.datasetVersion)
      params.set("dataset_version", String(selection.datasetVersion));
  }
  selection.areas.forEach((area) => params.append("area", area));
  selection.operators.forEach((operator) =>
    params.append("operator", operator),
  );
  if (selection.vehicleMode === "configured")
    selection.lines.forEach((line) => params.append("line", line));
  return params.toString();
}

export function loadLineDay(
  date: string,
  operatorId: string,
  line: string,
  signal?: AbortSignal,
) {
  const path = [operatorId, line].map(encodeURIComponent).join("/");
  return jsonRequest<LineDay>(
    `/api/lines/${path}/day?date=${encodeURIComponent(date)}`,
    signal,
  );
}

export function loadBunchingWeek(
  date: string,
  operatorId: string,
  line: string,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ date, operator: operatorId, line });
  return jsonRequest<BunchingWeek>(
    `/api/bunching/week?${params.toString()}`,
    signal,
  );
}

export function loadBunchingWeekSummary(date: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ date });
  return jsonRequest<BunchingWeekSummary>(
    `/api/bunching/week-summary?${params.toString()}`,
    signal,
  );
}

export async function jsonRequest<T>(
  url: string,
  init?: RequestInit | AbortSignal,
): Promise<T> {
  const config = init instanceof AbortSignal ? { signal: init } : init;
  const response = await fetch(url, config);
  if (!(response.headers.get("content-type") || "").includes("json")) {
    throw Error(
      "API unavailable. Start Docker Compose and import data; see README.",
    );
  }
  const value = await response.json();
  if (!response.ok)
    throw Error(
      typeof value.detail === "string"
        ? value.detail
        : `Request failed (${response.status}).`,
    );
  return value as T;
}

export function loadWorkspaceCatalog(date: string, signal?: AbortSignal) {
  return jsonRequest<WorkspaceCatalog>(
    `/api/workspace-catalog?date=${encodeURIComponent(date)}`,
    signal,
  );
}

export function loadVehicleDay(
  date: string,
  operatorId: string,
  vehicleId: string,
  signal?: AbortSignal,
) {
  const path = [operatorId, vehicleId].map(encodeURIComponent).join("/");
  return jsonRequest<VehicleDay>(
    `/api/vehicles/${path}/day?date=${encodeURIComponent(date)}`,
    signal,
  );
}

export async function loadSelection(
  selection: Selection,
  signal: AbortSignal,
): Promise<Dataset> {
  return validate(
    await jsonRequest(`/api/observations?${queryFor(selection)}`, signal),
  );
}

export class LatestRequest {
  private controller?: AbortController;
  private generation = 0;
  cancel() {
    this.controller?.abort();
    this.generation += 1;
  }
  async run<T>(
    work: (signal: AbortSignal) => Promise<T>,
  ): Promise<T | undefined> {
    this.cancel();
    const generation = this.generation;
    this.controller = new AbortController();
    try {
      const result = await work(this.controller.signal);
      return generation === this.generation ? result : undefined;
    } catch (error) {
      if (generation !== this.generation) return undefined;
      throw error;
    }
  }
}
