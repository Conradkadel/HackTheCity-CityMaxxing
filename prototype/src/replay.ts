export type ScheduleMatch = {
  packageId: number;
  routeId: string;
  line: string;
  routeName: string;
  directionId: string;
  mode: string;
  stopSequence: number;
  scheduledTime: number | null;
  reportedStopDifferenceSeconds: number | null;
};
export type RouteMatch = {
  packageId: number;
  routeId: string;
  line: string;
  routeName: string;
  directionId: string;
  mode: string;
};
export type Observation = {
  timestamp: number;
  receivedTimestamp: number;
  operatorId: string;
  vehicleId: string;
  tripId: string;
  stopId: string;
  latitude: number;
  longitude: number;
  geohash?: string;
  schedule?: ScheduleMatch;
  route?: RouteMatch;
  routeMatchStatus?: "matched" | "unmatched";
  isFocus?: boolean;
};
export type Dataset = {
  schemaVersion: 1;
  metadata: {
    title: string;
    sourcePartition: string;
    operationalDate: string;
    calendarDate?: string;
    areas?: string[];
    datasetVersion?: number;
    timezone: string;
    startTimestamp: number;
    endTimestamp: number;
    historySeconds: number;
    synthetic: boolean;
    operators: Record<string, string>;
    counts: Record<string, number>;
    scheduleReplay?: boolean;
    presetId?: string;
    includeContext?: boolean;
    routeCoverage?: {
      matchedObservations: number;
      unmatchedObservations: number;
    };
  };
  observations: Observation[];
};
export const keyOf = (o: Observation) =>
  JSON.stringify([o.operatorId, o.vehicleId]);
export function validate(value: unknown): Dataset {
  const d = value as Dataset;
  if (d?.schemaVersion !== 1 || !d.metadata || !Array.isArray(d.observations))
    throw Error("Unsupported replay data.");
  const m = d.metadata;
  if (
    m.timezone !== "Europe/Lisbon" ||
    !Number.isFinite(m.startTimestamp) ||
    !Number.isFinite(m.endTimestamp) ||
    m.endTimestamp <= m.startTimestamp ||
    !m.operators ||
    typeof m.synthetic !== "boolean"
  )
    throw Error("Invalid replay metadata.");
  let previous = -Infinity;
  for (const o of d.observations) {
    if (
      !Number.isFinite(o.timestamp) ||
      !Number.isFinite(o.receivedTimestamp) ||
      o.timestamp < previous ||
      !Number.isFinite(o.latitude) ||
      Math.abs(o.latitude) > 90 ||
      !Number.isFinite(o.longitude) ||
      Math.abs(o.longitude) > 180 ||
      !o.vehicleId ||
      typeof o.vehicleId !== "string" ||
      typeof o.operatorId !== "string" ||
      !m.operators[o.operatorId] ||
      typeof o.tripId !== "string" ||
      typeof o.stopId !== "string"
    )
      throw Error("Invalid or unsorted observations. Regenerate the extract.");
    previous = o.timestamp;
  }
  return d;
}
export function indexObservations(data: Observation[]) {
  const index = new Map<string, Observation[]>();
  for (const o of data) {
    const key = keyOf(o);
    if (!index.has(key)) index.set(key, []);
    index.get(key)!.push(o);
  }
  return index;
}
export function snapshot(
  index: Map<string, Observation[]>,
  time: number,
  operators: Set<string>,
) {
  const result: Array<Observation & { age: number; stale: boolean }> = [];
  for (const rows of index.values()) {
    if (!operators.has(rows[0].operatorId)) continue;
    let low = 0,
      high = rows.length;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (rows[mid].timestamp <= time) low = mid + 1;
      else high = mid;
    }
    if (!low) continue;
    const o = rows[low - 1],
      age = (time - o.timestamp) / 1000;
    if (age <= 120) result.push({ ...o, age, stale: age > 60 });
  }
  return result;
}
export const clock = (ts: number) =>
  new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Lisbon",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(ts);
export const colors: Record<string, string> = {
  IA9T6: "#e9a522",
  LA77N: "#21b5a1",
  BNA17: "#7772ec",
  YA15B: "#e76869",
  A2L1N: "#46a9e1",
};
