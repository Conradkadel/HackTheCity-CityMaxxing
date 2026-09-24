import { expect, it } from "vitest";

import { buildBunchingTimeline, nearestTimelinePoint } from "./replayDock";
import type { Dataset, Observation } from "./replay";

const start = Date.UTC(2026, 8, 1, 7, 0, 0);

function observation(
  vehicleId: string,
  line: string,
  timestamp: number,
  longitude: number,
  scheduledTime: number,
): Observation {
  return {
    timestamp,
    receivedTimestamp: timestamp,
    operatorId: "operator",
    vehicleId,
    tripId: `trip-${vehicleId}`,
    stopId: "stop",
    latitude: 38.73,
    longitude,
    routeMatchStatus: "matched",
    schedule: {
      packageId: 1,
      routeId: `route-${line}`,
      line,
      routeName: line,
      directionId: "0",
      mode: "bus",
      stopSequence: 1,
      scheduledTime,
      reportedStopDifferenceSeconds: 0,
    },
  };
}

const dataset: Dataset = {
  schemaVersion: 1,
  metadata: {
    title: "Replay",
    sourcePartition: "test",
    operationalDate: "2026-09-01",
    timezone: "Europe/Lisbon",
    startTimestamp: start,
    endTimestamp: start + 60_000,
    historySeconds: 120,
    synthetic: false,
    operators: { operator: "Operator" },
    counts: {},
  },
  observations: [
    observation("a", "702", start, -9.1, start),
    observation("b", "702", start + 10_000, -9.1005, start + 600_000),
    observation("c", "742", start, -9.11, start),
    observation("d", "742", start + 10_000, -9.1105, start + 600_000),
  ].sort((a, b) => a.timestamp - b.timestamp),
};

it("builds a network total and a line-scoped timeline", () => {
  expect(
    buildBunchingTimeline(dataset, null).map((point) => point.count),
  ).toEqual([0, 2]);
  expect(
    buildBunchingTimeline(dataset, "702").map((point) => point.count),
  ).toEqual([0, 1]);
  expect(
    buildBunchingTimeline(dataset, "750").map((point) => point.count),
  ).toEqual([0, 0]);
});

it("finds the closest graph sample to the replay time", () => {
  const timeline = buildBunchingTimeline(dataset, null);
  expect(nearestTimelinePoint(timeline, start + 49_000)?.count).toBe(2);
  expect(nearestTimelinePoint([], start)).toBeNull();
});
