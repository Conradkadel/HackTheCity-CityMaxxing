import { expect, it } from "vitest";
import {
  lisbonMinute,
  trafficPlotCells,
  type DiagramTraffic,
} from "./diagramTraffic";

const data: DiagramTraffic = {
  period: { start: "2026-08-31", end: "2026-09-06", days: 7, reports: 100 },
  bucketMinutes: 30,
  timezone: "Europe/Lisbon",
  referenceTripId: "trip",
  packageId: 1,
  ignoredReports: 0,
  sections: [
    {
      fromStopId: "a",
      toStopId: "b",
      fromSequence: 1,
      toSequence: 2,
      fromName: "A",
      toName: "B",
      geometryAvailable: true,
      lengthMeters: 400,
      cells: [
        { minute: 480, speedRatio: 30.5, days: 3, reports: 12, coverage: 0.6 },
        { minute: 510, speedRatio: 70.5, days: 1, reports: 2, coverage: 0.2 },
        { minute: 0, speedRatio: 10.5, days: 1, reports: 1, coverage: 1 },
      ],
    },
  ],
};
const stops = [{ id: "a" }, { id: "b" }];

it("places congestion in Lisbon wall-clock bands and clips to the chart window", () => {
  const start = Date.parse("2026-09-01T07:10:00Z"),
    end = Date.parse("2026-09-01T08:10:00Z");
  const cells = trafficPlotCells(data, stops, start, end);
  expect(cells).toHaveLength(3);
  expect(cells[0].start).toBe(start);
  expect(cells[0].opacity).toBeGreaterThan(0);
  expect(cells[0].description).toContain("08:00–08:30");
  expect(cells[1].opacity).toBe(0); // light reports are inspectable but not shaded
  expect(cells[2].end).toBe(end);
  expect(cells[2].description).toContain("No matched Waze reports");
});

it("handles midnight and both summer and winter offsets", () => {
  expect(lisbonMinute(Date.parse("2026-09-01T23:10:00Z"))).toBe(10);
  expect(lisbonMinute(Date.parse("2026-01-01T08:10:00Z"))).toBe(490);
  const start = Date.parse("2026-09-01T23:00:00Z");
  const cell = trafficPlotCells(data, stops, start, start + 30 * 60_000)[0];
  expect(cell.opacity).toBe(0.08);
  expect(cell.description).toContain("Single-day evidence");
});

it("never shades a reversed or different section or ambiguous loop leg", () => {
  const start = Date.parse("2026-09-01T07:00:00Z"),
    end = start + 30 * 60_000;
  expect(trafficPlotCells(data, [...stops].reverse(), start, end)).toEqual([]);
  expect(
    trafficPlotCells(data, [{ id: "a" }, { id: "c" }], start, end),
  ).toEqual([]);
  const repeated = {
    ...data,
    sections: [
      ...data.sections,
      { ...data.sections[0], fromSequence: 5, toSequence: 6 },
    ],
  };
  expect(trafficPlotCells(repeated, stops, start, end)).toEqual([]);
  expect(
    trafficPlotCells(
      repeated,
      [
        { id: "a", sequence: 1 },
        { id: "b", sequence: 2 },
      ],
      start,
      end,
    ),
  ).toHaveLength(1);
  expect(trafficPlotCells(null, stops, start, end)).toEqual([]);
});
