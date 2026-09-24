import { trafficBand } from "./traffic";

export type DiagramTrafficRequest = {
  date: string;
  agency: string;
  line: string;
  direction: string;
  package_id?: number;
  trip_id?: string;
};
export type TrafficTimeCell = {
  minute: number;
  speedRatio: number;
  days: number;
  reports: number;
  coverage: number;
};
export type DiagramTraffic = {
  period: {
    start: string | null;
    end: string | null;
    days: number;
    reports: number;
  };
  bucketMinutes: number;
  timezone: string;
  referenceTripId: string;
  packageId: number;
  ignoredReports: number;
  sections: {
    fromStopId: string;
    toStopId: string;
    fromSequence: number;
    toSequence: number;
    fromName: string;
    toName: string;
    geometryAvailable: boolean;
    lengthMeters: number;
    cells: TrafficTimeCell[];
  }[];
};
export type DiagramStop = { id: string; sequence?: number };
export type TrafficPlotCell = {
  index: number;
  start: number;
  end: number;
  color: string;
  opacity: number;
  description: string;
};
const lisbonTime = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Lisbon",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
export function lisbonMinute(timestamp: number) {
  const parts = lisbonTime.formatToParts(timestamp);
  return (
    Number(parts.find((p) => p.type === "hour")!.value) * 60 +
    Number(parts.find((p) => p.type === "minute")!.value)
  );
}
const minuteLabel = (minute: number) =>
  `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;

export function trafficPlotCells(
  data: DiagramTraffic | null,
  stops: DiagramStop[],
  minimum: number,
  maximum: number,
): TrafficPlotCell[] {
  if (!data || maximum <= minimum) return [];
  const result: TrafficPlotCell[] = [];
  const step = data.bucketMinutes * 60_000;
  for (let index = 0; index < stops.length - 1; index++) {
    const from = stops[index],
      to = stops[index + 1];
    const matches = data.sections.filter(
      (s) =>
        s.fromStopId === from.id &&
        s.toStopId === to.id &&
        (from.sequence == null || s.fromSequence === from.sequence) &&
        (to.sequence == null || s.toSequence === to.sequence),
    );
    // Ambiguous repeated stop pairs must not borrow evidence from another leg.
    if (matches.length !== 1) continue;
    const section = matches[0];
    for (
      let stamp = Math.floor(minimum / step) * step;
      stamp < maximum;
      stamp += step
    ) {
      const minute =
        Math.floor(lisbonMinute(stamp) / data.bucketMinutes) *
        data.bucketMinutes;
      const cell = section.cells.find((c) => c.minute === minute);
      const heavy = cell != null && cell.speedRatio <= 40;
      const description =
        `${section.fromName} → ${section.toName} · ${minuteLabel(minute)}–${minuteLabel(minute + data.bucketMinutes)} Lisbon time · ` +
        (!section.geometryAvailable
          ? "Route geometry unavailable"
          : !cell
            ? "No matched Waze reports"
            : `${trafficBand(cell.speedRatio).label} reported congestion · approximately ${Math.round(cell.speedRatio)}% of free-flow speed · ${cell.reports} reports across ${cell.days} of ${data.period.days} imported days · ${Math.round(cell.coverage * 100)}% of section covered${cell.days < 2 ? " · Single-day evidence" : ""}`);
      result.push({
        index,
        start: Math.max(minimum, stamp),
        end: Math.min(maximum, stamp + step),
        color: heavy ? trafficBand(cell.speedRatio).color : "transparent",
        opacity: heavy ? (cell.days < 2 ? 0.08 : 0.1 + 0.1 * cell.coverage) : 0,
        description,
      });
    }
  }
  return result;
}
