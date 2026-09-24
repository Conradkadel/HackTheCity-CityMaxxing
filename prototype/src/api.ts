import { validate, type Dataset } from "./replay";
import type { VehicleFilters, WorkspaceCatalog } from "./workspaceTypes";

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
