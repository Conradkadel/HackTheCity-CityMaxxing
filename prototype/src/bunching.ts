import { jsonRequest } from "./api";

/** One bus passing one stop, scored by the model (see backend/bunching.py). */
export type BunchingPoint = {
  t: number;
  /** position on the y axis = index in the first selected line's stop list */
  y: number;
  /** stop sequence within this bus's own trip */
  seq: number;
  stop_id: string;
  headway_s: number | null;
  sched_headway_s: number | null;
  ratio: number | null;
  delay_s: number | null;
  leader_vehicle: string | null;
  leader_line: string | null;
  bunched: boolean;
  /** P(bunched within the next `model.horizon` stops); null = not scored (no bus in front, bad data or already bunched). */
  prob: number | null;
  /** What really happened next (from the data), null at the end of a trip. */
  bunched_within_5: boolean | null;
};
export type BunchingTrip = {
  trip_id: string;
  vehicle_id: string;
  line: string;
  direction: string;
  points: BunchingPoint[];
};
/** One simulated test run of a holding time (replayed on the real trajectories). */
export type HoldRun = {
  hold_s: number;
  threshold: number;
  holds_made: number;
  buses_held: number;
  total_hold_min: number;
  bunched_passages: number;
  passages: number;
  bunched_pairs: number;
};
export type HoldAction = {
  trip_id: string;
  vehicle_id: string;
  line: string;
  stop_id: string;
  seq: number;
  t: number;
  hold_s: number;
  prob_before: number;
  prob_after: number;
};
export type BunchingPair = {
  follower_vehicle: string;
  follower_line: string;
  follower_trip: string;
  leader_vehicle: string;
  leader_line: string;
  leader_trip: string;
  stops: number;
  min_gap_s: number;
  first: number;
  last: number;
};
export type AlertQuality = {
  precision: number;
  recall: number;
  f1: number;
  alerts_per_100: number;
};
export type BunchingDiagram = {
  date: string;
  mode: "line" | "corridor";
  line: string;
  direction: string;
  directionName: string;
  lines: { line: string; direction: string; directionName: string }[];
  threshold: number;
  startTimestamp: number;
  endTimestamp: number;
  stops: { y: number; stop_id: string; name: string }[];
  trips: BunchingTrip[];
  pairs: BunchingPair[];
  summary: {
    trips: number;
    passages: number;
    bunchedPassages: number;
    crossLineBunched: number;
    scoredPassages: number;
    alerts: number;
    alertsThatBunched: number;
    alertsChecked: number;
  };
  scenarios: HoldRun[];
  selected: HoldRun & { holds: HoldAction[] };
  recommendation: HoldRun | null;
  model: {
    mode: "line" | "corridor";
    target: string;
    /** the prediction looks this many stops ahead (same line 10, across lines 5) */
    horizon?: number;
    trained_at: string;
    /** "gradient_boosted_trees" (same line, v4) or "logistic_regression" */
    kind?: string;
    /** the model that decides where a bus is held in the what-if */
    holdTrigger?: { kind?: string; threshold: number };
    alerting?: {
      threshold: number;
      chosen_by: string;
      test: AlertQuality;
      baseline_rule: string;
      baseline_test: AlertQuality;
    };
    metrics: {
      roc_auc: number;
      average_precision: number;
      baseline_roc_auc: number;
      baseline_average_precision: number;
      test_positive_rate: number;
      n_train: number;
      n_test: number;
    };
  };
};
export type BunchingLine = {
  line: string;
  name: string;
  directions: { id: string; name: string; trips: number }[];
};
export type SharedLine = {
  line: string;
  name: string;
  direction: string;
  directionName: string;
  trips: number;
  sharedStops: number;
  routeStops: number;
};
export type BunchingQuery = {
  date: string;
  start: string;
  end: string;
  line: string;
  direction: string;
  /** extra lines on the same route, as "LINE:DIRECTION" */
  with?: string[];
  hold: number;
  /** omit to use the alert level chosen during training */
  threshold?: number;
};

export function bunchingQuery(query: BunchingQuery) {
  const params = new URLSearchParams({
    date: query.date,
    start: query.start,
    end: query.end,
    line: query.line,
    direction: query.direction,
    hold: String(query.hold),
  });
  query.with?.forEach((value) => params.append("with", value));
  if (query.threshold != null) params.set("threshold", String(query.threshold));
  return params.toString();
}

/** A plain FastAPI "Not Found" means the running API is older than this frontend. */
async function bunchingRequest<T>(url: string, signal: AbortSignal) {
  try {
    return await jsonRequest<T>(url, signal);
  } catch (error) {
    if ((error as Error).message === "Not Found")
      throw Error(
        "The API does not have the Bunching endpoints yet. Rebuild it: docker compose up -d --build",
        { cause: error },
      );
    throw error;
  }
}

type Window = { date: string; start: string; end: string };

export function loadBunchingLines(window: Window, signal: AbortSignal) {
  return bunchingRequest<{ lines: BunchingLine[] }>(
    `/api/bunching/lines?${new URLSearchParams(window)}`,
    signal,
  );
}

export function loadSharedLines(
  query: Window & { line: string; direction: string },
  signal: AbortSignal,
) {
  return bunchingRequest<{ shared: SharedLine[]; routeStops: number }>(
    `/api/bunching/shared?${new URLSearchParams(query)}`,
    signal,
  );
}

export function loadBunchingDiagram(query: BunchingQuery, signal: AbortSignal) {
  return bunchingRequest<BunchingDiagram>(
    `/api/bunching/diagram?${bunchingQuery(query)}`,
    signal,
  );
}

/** A held bus: from each hold stop onwards it runs that many seconds later (holds add up). */
export function heldTrajectory(trip: BunchingTrip, holds: HoldAction[]) {
  if (!holds.length) return [];
  const first = Math.min(...holds.map((hold) => hold.seq));
  return trip.points
    .filter((point) => point.seq >= first)
    .map((point) => ({
      ...point,
      t:
        point.t +
        holds
          .filter((hold) => hold.seq <= point.seq)
          .reduce((sum, hold) => sum + hold.hold_s * 1000, 0),
    }));
}

export const percent = (value: number | null | undefined, digits = 0) =>
  value == null ? "–" : `${(value * 100).toFixed(digits)}%`;

export const duration = (seconds: number | null | undefined) => {
  if (seconds == null) return "–";
  const sign = seconds < 0 ? "−" : "";
  const value = Math.abs(Math.round(seconds));
  return value < 60
    ? `${sign}${value} s`
    : `${sign}${Math.floor(value / 60)} min ${String(value % 60).padStart(2, "0")} s`;
};
