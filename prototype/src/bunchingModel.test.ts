import { describe, expect, it } from "vitest";

import { bunchingQuery, duration, heldTrajectory, percent } from "./bunching";

const point = (seq: number, t: number) => ({
  t,
  y: seq,
  seq,
  stop_id: `S${seq}`,
  headway_s: 300,
  sched_headway_s: 600,
  ratio: 0.5,
  delay_s: 0,
  leader_vehicle: "1",
  leader_line: "736",
  bunched: false,
  prob: 0.2,
  bunched_within_5: false,
});

describe("bunching model helpers", () => {
  it("encodes the diagram query", () => {
    const query = bunchingQuery({
      date: "2026-09-04",
      start: "17:00",
      end: "20:00",
      line: "15E",
      direction: "0",
      with: ["738:0", "747:0"],
      hold: 60,
    });
    expect(query).toBe(
      "date=2026-09-04&start=17%3A00&end=20%3A00&line=15E&direction=0&hold=60&with=738%3A0&with=747%3A0",
    );
  });

  it("shifts a held trip from each hold stop onwards", () => {
    const trip = {
      trip_id: "A",
      vehicle_id: "1",
      line: "736",
      direction: "0",
      points: [point(1, 0), point(2, 1000), point(3, 2000), point(4, 3000)],
    };
    const hold = (seq: number, hold_s: number) => ({
      trip_id: "A",
      vehicle_id: "1",
      line: "736",
      stop_id: `S${seq}`,
      seq,
      t: 0,
      hold_s,
      prob_before: 0.6,
      prob_after: 0.3,
    });
    const held = heldTrajectory(trip, [hold(2, 30), hold(4, 10)]);
    expect(held.map((p) => [p.seq, p.t])).toEqual([
      [2, 31000],
      [3, 32000],
      [4, 43000],
    ]);
    expect(heldTrajectory(trip, [])).toEqual([]);
  });

  it("formats values", () => {
    expect(percent(0.456)).toBe("46%");
    expect(percent(null)).toBe("–");
    expect(duration(45)).toBe("45 s");
    expect(duration(125)).toBe("2 min 05 s");
  });
});
