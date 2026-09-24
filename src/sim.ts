import { jsonRequest } from "./api";

/** Scenario = one timing change the simulator can replay (backend/simulator.py). */
export type SimScenarioInfo = {
  code: string;
  name: string;
  lever: string;
  package: string;
};
export type SeedRange = { mean: number; min: number; max: number };
export type SimKpis = {
  bunched_pct?: SeedRange;
  ewt_s?: SeedRange;
  headway_cv?: SeedRange;
  hold_s_per_trip?: SeedRange;
  terminal_wait_s_per_trip?: SeedRange;
  trip_time_min?: SeedRange;
};
export type SimScenario = SimScenarioInfo & {
  kpis: SimKpis;
  holds: number;
  extraVehicles: number;
  /** excess wait saved vs as run, mean over the seeds (s per passenger) */
  ewtSaved: number | null;
  /** 5th percentile over the seeds: > 0 = it helps in (almost) every seed */
  ewtSavedP5: number | null;
};
export type HeldOut = {
  robust: boolean;
  ewt_saved: number;
  ewt_saved_range: [number, number];
  bunched_pct_change: number;
  extra_vehicles: number;
};
/** [y (stop index), time in ms, bunched 0/1] */
export type SimPoint = [number, number, number];
export type SimTrip = {
  id: number;
  vehicle: string;
  dispatchable: boolean;
  asRun: SimPoint[];
  simulated: SimPoint[];
};
export type SimBaseline = {
  trips: number;
  passages: number;
  bunched: number;
  bunched_pct: number | null;
  headway_cv: number | null;
  ewt_s: number | null;
  trip_time_min: number | null;
};
export type SimRun = {
  date: string;
  line: string;
  direction: string;
  directionName: string;
  startTimestamp: number;
  endTimestamp: number;
  scenario: string;
  seeds: number;
  k: number;
  stops: { y: number; stop_id: string; name: string }[];
  trips: SimTrip[];
  holds: { trip: number; y: number | null; t: number; s: number }[];
  dispatch: {
    trip: number;
    y: number | null;
    t: number;
    shift_s: number;
    wait_s: number;
  }[];
  baseline: SimBaseline;
  scenarios: SimScenario[];
  recommendation: {
    today: string | null;
    heldOut: string | null;
    heldOutScenarios: Record<string, HeldOut> | null;
  };
  validation: {
    status: "pass" | "partial" | "fail" | null;
    note: string | null;
    k: number;
    kRange: number[];
    testDays: string[];
    fitDays: string[];
  } | null;
};
export type SimQuery = {
  date: string;
  start: string;
  end: string;
  line: string;
  direction: string;
  scenario: string;
  seeds: number;
};

async function simRequest<T>(url: string, signal: AbortSignal) {
  try {
    return await jsonRequest<T>(url, signal);
  } catch (error) {
    if ((error as Error).message === "Not Found")
      throw Error(
        "The API does not have the Simulate endpoints yet. Rebuild it: docker compose up -d --build",
        { cause: error },
      );
    throw error;
  }
}

export function simQuery(query: SimQuery) {
  return new URLSearchParams({
    date: query.date,
    start: query.start,
    end: query.end,
    line: query.line,
    direction: query.direction,
    scenario: query.scenario,
    seeds: String(query.seeds),
  }).toString();
}

export function loadSimScenarios(signal: AbortSignal) {
  return simRequest<{
    scenarios: SimScenarioInfo[];
    scopeLines: string[];
    k: number;
    status: string | null;
  }>("/api/sim/scenarios", signal);
}

export function loadSimRun(query: SimQuery, signal: AbortSignal) {
  return simRequest<SimRun>(`/api/sim/run?${simQuery(query)}`, signal);
}

/** Split a trajectory into runs of bunched / not bunched points (for red segments). */
export function bunchedSegments(points: SimPoint[]) {
  const out: SimPoint[][] = [];
  let current: SimPoint[] = [];
  points.forEach((point, index) => {
    const previous = points[index - 1];
    if (point[2] && previous) {
      if (!current.length) current.push(previous);
      current.push(point);
    } else if (current.length) {
      out.push(current);
      current = [];
    }
  });
  if (current.length) out.push(current);
  return out;
}

/** Cost of a scenario for the trade-off chart: seconds per trip (on board + at the terminal). */
export const scenarioCost = (scenario: SimScenario) =>
  (scenario.kpis.hold_s_per_trip?.mean ?? 0) +
  (scenario.kpis.terminal_wait_s_per_trip?.mean ?? 0);

export const signed = (value: number | null | undefined, digits = 0) =>
  value == null
    ? "–"
    : `${value > 0 ? "+" : value < 0 ? "−" : "±"}${Math.abs(value).toFixed(digits)}`;
