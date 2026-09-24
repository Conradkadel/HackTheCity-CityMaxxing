import { detectMapBunching } from "./bunching";
import { indexObservations, snapshot, type Dataset } from "./replay";

export type BunchingTimelinePoint = { t: number; count: number };

export function buildBunchingTimeline(
  data: Dataset | null,
  line: string | null,
  stepMilliseconds = 60_000,
): BunchingTimelinePoint[] {
  if (!data || stepMilliseconds <= 0) return [];

  const index = indexObservations(data.observations);
  const operators = new Set(Object.keys(data.metadata.operators));
  const points: BunchingTimelinePoint[] = [];

  for (
    let timestamp = data.metadata.startTimestamp;
    timestamp <= data.metadata.endTimestamp;
    timestamp += stepMilliseconds
  ) {
    let visible = snapshot(index, timestamp, operators);
    if (line) {
      visible = visible.filter(
        (observation) =>
          observation.schedule?.line === line ||
          observation.route?.line === line,
      );
    }
    points.push({
      t: timestamp,
      count: detectMapBunching(visible).length,
    });
  }

  return points;
}

export function nearestTimelinePoint(
  timeline: BunchingTimelinePoint[],
  timestamp: number,
) {
  if (!timeline.length) return null;
  return timeline.reduce((nearest, point) =>
    Math.abs(point.t - timestamp) < Math.abs(nearest.t - timestamp)
      ? point
      : nearest,
  );
}
