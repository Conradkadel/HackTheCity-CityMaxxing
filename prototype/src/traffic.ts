export type TrafficSection = {
  shapeId: string;
  directionId: string;
  points: [number, number][];
  speedRatio: number | null;
  speedKmh: number | null;
  reports: number;
  days: number;
};

export type RouteTraffic = {
  period: {
    start: string | null;
    end: string | null;
    days: number;
    reports: number;
  };
  method: string;
  matchRadiusMeters: number;
  ignoredReports: number;
  routes: {
    key: string;
    sections: TrafficSection[];
    matchedMeters: number;
    totalMeters: number;
  }[];
};

export const trafficBands = [
  { label: "Very heavy", color: "#b91c1c", max: 20 },
  { label: "Heavy", color: "#ea580c", max: 40 },
  { label: "Moderate", color: "#f59e0b", max: 60 },
  { label: "Light", color: "#e2cf45", max: 100 },
];
export const unknownTraffic = { label: "No matched reports", color: "#88949d" };

export function trafficBand(ratio: number | null) {
  return ratio == null || !Number.isFinite(ratio)
    ? unknownTraffic
    : (trafficBands.find((band) => ratio <= band.max) ?? unknownTraffic);
}

export function trafficDescription(section: TrafficSection) {
  if (section.speedRatio == null) return "No matched Waze reports";
  return `${trafficBand(section.speedRatio).label} reported congestion · approximately ${Math.round(section.speedRatio)}% of free-flow speed${section.speedKmh == null ? "" : ` · ${section.speedKmh} km/h`} · ${section.reports.toLocaleString()} reports across ${section.days} day${section.days === 1 ? "" : "s"}`;
}
