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

/**
 * Plain-language names for the simulator's changes (the backend keeps its short codes).
 * name = what the operator does; short = label for charts; lever = one sentence of how.
 */
export const SCENARIO_TEXT: Record<
  string,
  { name: string; short: string; lever: string; main?: boolean }
> = {
  AS: {
    name: "As it really ran",
    short: "As run",
    lever: "Nothing changed: the recorded day",
  },
  D1: {
    name: "Leave exactly on time (for comparison)",
    short: "On time",
    lever:
      "Every bus leaves the terminal at its timetable time. A best case to compare with, not a real rule",
  },
  "D2-2": {
    name: "Wait for a proper gap (up to 2 min)",
    short: "Gap wait 2 min",
    lever:
      "At the terminal, a bus waits until the bus in front is far enough ahead, at most 2 min",
  },
  D2: {
    name: "Wait for a proper gap at the terminal",
    short: "Gap wait 3 min",
    lever:
      "At the terminal, a bus waits until the bus in front is far enough ahead (90 % of the planned gap), at most 3 min",
    main: true,
  },
  "D2-5": {
    name: "Wait for a proper gap (up to 5 min)",
    short: "Gap wait 5 min",
    lever:
      "At the terminal, a bus waits until the bus in front is far enough ahead, at most 5 min",
  },
  "H1-60": {
    name: "Short hold at two checkpoints",
    short: "Checkpoints 1 min",
    lever:
      "At 2 stops along the route, a bus that is more than 3 min too close to the bus in front waits up to 1 min",
    main: true,
  },
  "H1-120": {
    name: "Hold at two checkpoints (up to 2 min)",
    short: "Checkpoints 2 min",
    lever:
      "At 2 stops along the route, a bus that is more than 3 min too close to the bus in front waits up to 2 min",
  },
  "M-90": {
    name: "Hold when the early warning fires",
    short: "Warning hold",
    lever:
      "When the model warns that a bus is catching up, it waits at that stop up to 90 s",
    main: true,
  },
  "D2+H1": {
    name: "Gap wait at the terminal + checkpoint holds",
    short: "Gap + checkpoints",
    lever: "Both: wait for a proper gap at the terminal and hold at 2 stops",
  },
  "T2-2": {
    name: "2 more minutes of break at the terminal",
    short: "Break +2 min",
    lever:
      "Each bus rests 2 min longer between trips, so a late arrival does not delay the next trip. Needs about 1 extra bus",
    main: true,
  },
  "T2-4": {
    name: "4 more minutes of break at the terminal",
    short: "Break +4 min",
    lever: "Each bus rests 4 min longer between trips. Needs extra buses",
  },
};

/** What each change costs, in plain words. */
export const PACKAGE_TEXT: Record<string, string> = {
  "no cost": "free",
  "low cost": "low cost",
  investment: "needs a bus",
  ceiling: "comparison",
};

export const scenarioShort = (code: string | null | undefined) =>
  code ? (SCENARIO_TEXT[code]?.short ?? code) : "–";

function friendly<T extends SimScenarioInfo>(scenario: T): T {
  const text = SCENARIO_TEXT[scenario.code];
  return text ? { ...scenario, name: text.name, lever: text.lever } : scenario;
}

export async function loadSimScenarios(signal: AbortSignal) {
  const value = await simRequest<{
    scenarios: SimScenarioInfo[];
    scopeLines: string[];
    k: number;
    status: string | null;
  }>("/api/sim/scenarios", signal);
  return value && { ...value, scenarios: value.scenarios.map(friendly) };
}

export async function loadSimRun(query: SimQuery, signal: AbortSignal) {
  const value = await simRequest<SimRun>(
    `/api/sim/run?${simQuery(query)}`,
    signal,
  );
  return value && { ...value, scenarios: value.scenarios.map(friendly) };
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

/**
 * The best change = the biggest reliable cut in waiting. "Leave exactly on time" is a comparison,
 * never a policy. When two changes are practically equal (within 1 s or 5 %), the cheaper one wins.
 * backend/build_findings.py (best_change) uses the same rule, so Findings and Simulation agree.
 */
export function bestChange<
  T extends { code: string; saved: number; reliable: boolean; cost: number[] },
>(options: T[]): T | null {
  const ok = options.filter(
    (o) => o.reliable && o.code !== "D1" && o.saved > 0,
  );
  if (!ok.length) return null;
  const top = Math.max(...ok.map((o) => o.saved));
  const close = ok.filter((o) => o.saved >= top - Math.max(1, 0.05 * top));
  const cheaper = (a: T, b: T) => {
    for (let i = 0; i < Math.max(a.cost.length, b.cost.length); i += 1)
      if ((a.cost[i] ?? 0) !== (b.cost[i] ?? 0))
        return (a.cost[i] ?? 0) - (b.cost[i] ?? 0);
    return 0;
  };
  return [...close].sort(cheaper)[0];
}

/** Best change on the day that was simulated (it must help in 95 % of the repeats). */
export function bestToday(run: SimRun) {
  const best = bestChange(
    run.scenarios
      .filter((s) => s.code !== "AS")
      .map((s) => ({
        code: s.code,
        saved: s.ewtSaved ?? 0,
        reliable: (s.ewtSavedP5 ?? 0) > 0,
        cost: [s.extraVehicles, scenarioCost(s)],
      })),
  );
  return best?.code ?? null;
}

/** Best change over the held-out test days (both days, both dwell settings). */
export function bestTested(run: SimRun) {
  const held = run.recommendation.heldOutScenarios;
  if (!held) return null;
  const best = bestChange(
    Object.entries(held).map(([code, h]) => ({
      code,
      saved: h.ewt_saved,
      reliable: h.robust,
      cost: [h.extra_vehicles],
    })),
  );
  return best?.code ?? null;
}

/** The test days were simulated for 16–20 h only, so their result applies to evening windows. */
export function coversTestHours(run: SimRun) {
  const hour = (t: number) =>
    Number(
      new Intl.DateTimeFormat("en-GB", {
        timeZone: "Europe/Lisbon",
        hour: "2-digit",
        hourCycle: "h23",
      }).format(t),
    );
  return hour(run.startTimestamp) < 20 && hour(run.endTimestamp - 1) >= 16;
}

/** The one recommended change: tested over the test days when they apply, else this day's best. */
export function bestOverall(run: SimRun) {
  return (coversTestHours(run) ? bestTested(run) : null) ?? bestToday(run);
}
