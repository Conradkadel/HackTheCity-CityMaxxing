import { describe, expect, it } from "vitest";

import { detectMapBunching, distanceMeters } from "./bunching";
import type { Observation } from "./replay";

const observation = (
  vehicleId: string,
  timestamp: number,
  scheduledTime: number,
  latitude = 38.72,
): Observation & { age: number; stale: boolean } => ({
  timestamp,
  receivedTimestamp: timestamp,
  operatorId: "IA9T6",
  vehicleId,
  tripId: `trip-${vehicleId}`,
  stopId: "stop-1",
  latitude,
  longitude: -9.14,
  routeMatchStatus: "matched",
  isFocus: true,
  age: 5,
  stale: false,
  route: {
    packageId: 8,
    routeId: "118_0",
    line: "755",
    routeName: "Example",
    directionId: "0",
    mode: "bus",
  },
  schedule: {
    packageId: 8,
    routeId: "118_0",
    line: "755",
    routeName: "Example",
    directionId: "0",
    mode: "bus",
    stopSequence: 12,
    scheduledTime,
    reportedStopDifferenceSeconds: 0,
  },
});

describe("map bunching detection", () => {
  it("flags nearby vehicles reporting the same stop after planned headway collapse", () => {
    const base = Date.UTC(2026, 8, 1, 7);
    const first = observation("2671", base, base);
    const second = observation(
      "2762",
      base + 90_000,
      base + 15 * 60_000,
      38.721,
    );

    const result = detectMapBunching([first, second]);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      line: "755",
      observedGapSeconds: 90,
      plannedGapSeconds: 900,
    });
    expect(result[0].distanceMeters).toBeLessThan(300);
  });

  it("rejects vehicles that are close in time but geographically far apart", () => {
    const base = Date.UTC(2026, 8, 1, 7);
    const first = observation("2671", base, base);
    const second = observation(
      "2762",
      base + 90_000,
      base + 15 * 60_000,
      38.73,
    );

    expect(distanceMeters(first, second)).toBeGreaterThan(300);
    expect(detectMapBunching([first, second])).toEqual([]);
  });

  it("rejects vehicles whose timetable already placed them together", () => {
    const base = Date.UTC(2026, 8, 1, 7);
    expect(
      detectMapBunching([
        observation("2671", base, base),
        observation("2762", base + 60_000, base + 4 * 60_000),
      ]),
    ).toEqual([]);
  });
});
