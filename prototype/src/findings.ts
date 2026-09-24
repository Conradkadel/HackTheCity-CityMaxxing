import { jsonRequest } from "./api";
import { SCENARIO_TEXT } from "./sim";

/** A stop referenced by the findings; name/position come from the plan when the database is up. */
export type FindingStop = {
  stop_id: string;
  name?: string | null;
  lat: number | null;
  lon: number | null;
};
export type Cause = "dispatch" | "turnaround" | "road";

export type Problem = {
  line: string;
  direction: string;
  block: string;
  /** exact hours with >= 2x the network rate on >= 4 of 5 weekdays, e.g. ["16:00–20:00"] */
  hours: string[];
  hotHours: number[];
  rate: number;
  timesNetwork: number;
  daysHot: number;
  bunchedPerWeekday: number;
  tripsPerWeekday: number | null;
  schedHeadwayMin: number | null;
  byDay: Record<string, number | null>;
  byHour: Record<string, number | null>;
  evidence: {
    departTooClose: number;
    prevTripLate: number;
    onsetMedianProgress: number | null;
    onsetFirstQuarter: number | null;
  };
  cause: Cause;
  causeText: string;
  fix: string;
  tested: {
    scenario: string;
    ewtSaved: number;
    ewtSavedRange: [number, number];
    bunchedPctChange: number;
    extraVehicles: number;
    holdPerTrip: number;
    terminalWaitPerTrip: number;
    robust: boolean;
    days: string;
    alsoRobust: string[];
  } | null;
  terminal: FindingStop | null;
  stretch: (FindingStop & { seq: number; rate: number; days: number })[];
  profile: (FindingStop & { seq: number; rate: number; onsets: number })[];
};
export type Corridor = {
  pair: string;
  lines: [string, string];
  directions: [string, string];
  eventsPerWeekday: number;
  daysWithEvents: number;
  plannedTogetherShare: number;
  peakHours: string[];
  byHour: Record<string, number>;
  byDay: Record<string, number>;
  closeShare: number;
  sharedStops: FindingStop[];
};
export type Hotspot = FindingStop & {
  bunchedPerWeekday: number;
  rate: number;
  lines: string[];
  peakHour: number | null;
};
export type Findings = {
  generatedAt: string;
  stopNames?: boolean;
  source: {
    operator: string;
    from: string;
    to: string;
    passages: number;
    lines: number;
    definition: string;
  };
  headline: {
    weekdayRate: number;
    weekendRate: number;
    bunchedPerWeekday: number;
    topLines: string[];
    topLinesBunchingShare: number;
    topLinesPassageShare: number;
    recurringBlocks: number;
    recurringBlocksShare: number;
    peakHours: string[];
    departTooCloseTripShare: number;
    departTooCloseBunchingShare: number;
    networkDepartTooClose: number;
    networkPrevTripLate: number;
    corridorEventsPerWeekday: number;
    corridorPlannedTogether: number;
  };
  hours: { hour: number; rate: number }[];
  byDay: Record<string, number>;
  lines: {
    line: string;
    direction: string;
    bunchedPerWeekday: number;
    rate: number;
    share: number;
    schedHeadwayMin: number;
  }[];
  departure: {
    key: string;
    label: string;
    trips: number;
    tripShare: number;
    pBunch: number;
    bunchingShare: number;
  }[];
  problems: Problem[];
  hotspots: Hotspot[];
  corridors: Corridor[];
  areas?: HotArea[];
  areaSummary?: {
    cells: number;
    top10BunchingShare: number;
    top10VisitShare: number;
    onRoadOnsetsPerWeekday: number;
    hotAreaShareOfOnRoad: number;
  };
};

/** An area (~500 m) where buses that left on time catch up with the bus in front unusually often. */
export type HotArea = {
  lat: number;
  lon: number;
  ratio: number;
  days: number;
  onsetsPerWeekday: number;
  lines: number;
  topLines: string[];
  peakHours: string[];
  stops: (FindingStop & { onsets: number })[];
};

export const loadFindings = (signal?: AbortSignal) =>
  jsonRequest<Findings>("/api/findings", signal);

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];
export const DAYS = [...WEEKDAYS, "Sat", "Sun"];

/** Plain-language cause and fix per problem type (shown instead of the technical terms). */
export const CAUSES: Record<
  Cause,
  {
    label: string;
    problem: string;
    fix: string;
    fixShort: string;
    color: string;
  }
> = {
  dispatch: {
    label: "Leaves too soon",
    problem: "Buses leave the terminal too soon after the bus in front",
    fix: "At the terminal, let a bus leave only when the bus in front is far enough ahead (wait at most 3–5 min).",
    fixShort: "Wait for a proper gap at the terminal",
    color: "#2a78d6",
  },
  turnaround: {
    label: "Break too short",
    problem:
      "The previous trip arrives late and the bus has to leave again straight away",
    fix: "Give buses 2 more minutes of break at the terminal in these hours, so a late arrival does not delay the next trip.",
    fixShort: "2 more minutes of break at the terminal",
    color: "#7a4fd0",
  },
  road: {
    label: "Delays on the route",
    problem: "Buses leave on time, but gaps close up on the way",
    fix: "Let a bus wait up to 90 s at one or two stops mid-route when the early warning says it is catching up.",
    fixShort: "Short holds mid-route on early warning",
    color: "#e0772f",
  },
};
export const CORRIDOR_COLOR = "#0f9a8a";

/** Stop label: plan name when known, otherwise the stop id. */
export const stopLabel = (stop: { stop_id: string; name?: string | null }) =>
  stop.name ? stop.name : `stop ${stop.stop_id}`;

export const pct = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined
    ? "–"
    : `${(value * 100).toFixed(digits)} %`;

/** "Line 742 from Terminal X" (the direction is named by where it starts). */
export const problemTitle = (p: Problem) =>
  `Line ${p.line} from ${p.terminal ? stopLabel(p.terminal) : `direction ${p.direction}`}`;

/** Heat colour for a bunching rate, measured against the network's weekday rate. */
export function heat(rate: number | null | undefined, base: number) {
  if (rate === null || rate === undefined) return "transparent";
  const x = Math.max(0, Math.min(1, rate / base / 6));
  // cream -> amber -> red
  const stops = [
    [250, 246, 234],
    [246, 196, 106],
    [226, 111, 64],
    [178, 34, 45],
  ];
  const at = x * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(at));
  const f = at - i;
  const c = stops[i].map((v, k) => Math.round(v + (stops[i + 1][k] - v) * f));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

/** Which simulator window to open for a problem: a held-out weekday in its hot hours (max 4 h). */
export function simWindow(p: Problem) {
  const first = p.hotHours.length ? Math.min(...p.hotHours) : 16;
  const start = Math.max(0, Math.min(first, 20));
  const end = Math.min(start + 4, 24);
  const two = (h: number) => `${String(h).padStart(2, "0")}:00`;
  return {
    date: "2026-09-04",
    start: two(start),
    end: end === 24 ? "23:59" : two(end),
  };
}

/**
 * The one change to show for a problem line. When the simulator tested this line in these hours,
 * it is the change with the biggest reliable cut in waiting (same rule as the Simulation tab);
 * otherwise the change suggested by the cause.
 */
export function fixOf(p: Problem) {
  const code = p.tested?.scenario;
  const text = code ? SCENARIO_TEXT[code] : undefined;
  if (text)
    return { name: text.name, how: `${text.lever}.`, code, tested: true };
  return {
    name: CAUSES[p.cause].fixShort,
    how: CAUSES[p.cause].fix,
    code: null,
    tested: false,
  };
}
