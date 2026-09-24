import { expect, it } from "vitest";
import { trafficBand, trafficDescription, unknownTraffic } from "./traffic";

it("distinguishes missing evidence from the strongest reported congestion", () => {
  expect(trafficBand(null)).toEqual(unknownTraffic);
  expect(trafficBand(NaN)).toEqual(unknownTraffic);
  expect(trafficBand(0).label).toBe("Very heavy");
  expect(trafficBand(20).label).toBe("Very heavy");
  expect(trafficBand(20.1).label).toBe("Heavy");
  expect(trafficBand(40.5).label).toBe("Moderate");
  expect(trafficBand(70.5).label).toBe("Light");
});

it("explains the evidence without inventing a missing speed", () => {
  const section = {
    shapeId: "a",
    directionId: "0",
    points: [],
    speedRatio: 30.5,
    speedKmh: null,
    reports: 12,
    days: 2,
  };
  expect(trafficDescription(section)).toContain("12 reports across 2 days");
  expect(trafficDescription(section)).not.toContain("km/h");
  expect(trafficDescription({ ...section, speedRatio: null })).toBe(
    "No matched Waze reports",
  );
});
