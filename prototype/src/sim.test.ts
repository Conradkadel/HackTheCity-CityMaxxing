import { describe, expect, it } from "vitest";

import { bunchedSegments, scenarioCost, signed, simQuery } from "./sim";

describe("simulation helpers", () => {
  it("splits a trajectory into red (bunched) segments", () => {
    const segments = bunchedSegments([
      [0, 0, 0],
      [1, 10, 1],
      [2, 20, 1],
      [3, 30, 0],
      [4, 40, 1],
    ]);
    expect(segments).toEqual([
      [
        [0, 0, 0],
        [1, 10, 1],
        [2, 20, 1],
      ],
      [
        [3, 30, 0],
        [4, 40, 1],
      ],
    ]);
  });

  it("formats signed values and costs", () => {
    expect(signed(12.4)).toBe("+12");
    expect(signed(-3.25, 1)).toBe("−3.3");
    expect(signed(null)).toBe("–");
    expect(
      scenarioCost({
        kpis: {
          hold_s_per_trip: { mean: 30, min: 0, max: 0 },
          terminal_wait_s_per_trip: { mean: 12, min: 0, max: 0 },
        },
      } as never),
    ).toBe(42);
  });

  it("builds the run query", () => {
    expect(
      simQuery({
        date: "2026-09-04",
        start: "16:00",
        end: "20:00",
        line: "742",
        direction: "1",
        scenario: "D2",
        seeds: 10,
      }),
    ).toBe(
      "date=2026-09-04&start=16%3A00&end=20%3A00&line=742&direction=1&scenario=D2&seeds=10",
    );
  });
});
