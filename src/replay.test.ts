import { describe, it, expect } from "vitest";
import {
  clock,
  indexObservations,
  snapshot,
  validate,
  type Observation,
} from "./replay";
import { demo } from "./demo";
const row = (
  timestamp: number,
  extra: Partial<Observation> = {},
): Observation => ({
  timestamp,
  receivedTimestamp: timestamp + 10,
  operatorId: "IA9T6",
  vehicleId: "001",
  tripId: "trip",
  stopId: "0002",
  latitude: 38.7,
  longitude: -9.1,
  ...extra,
});
describe("replay", () => {
  it("never uses a future event and scrubs backward deterministically", () => {
    const idx = indexObservations([row(0), row(20000), row(40000)]),
      ops = new Set(["IA9T6"]);
    expect(snapshot(idx, -1, ops)).toHaveLength(0);
    expect(snapshot(idx, 30000, ops)[0].timestamp).toBe(20000);
    snapshot(idx, 50000, ops);
    expect(snapshot(idx, 10000, ops)[0].timestamp).toBe(0);
  });
  it("implements strict fade and expiry boundaries", () => {
    const idx = indexObservations([row(0)]),
      ops = new Set(["IA9T6"]);
    expect(snapshot(idx, 60000, ops)[0].stale).toBe(false);
    expect(snapshot(idx, 60001, ops)[0].stale).toBe(true);
    expect(snapshot(idx, 120000, ops)).toHaveLength(1);
    expect(snapshot(idx, 120001, ops)).toHaveLength(0);
  });
  it("keys vehicles by operator and filters correctly", () => {
    const idx = indexObservations([
      row(0),
      row(1),
      row(0, { operatorId: "LA77N" }),
    ]);
    expect(snapshot(idx, 10, new Set(["IA9T6", "LA77N"]))).toHaveLength(2);
    expect(snapshot(idx, 10, new Set(["IA9T6"]))).toHaveLength(1);
    expect(snapshot(idx, 10, new Set())).toHaveLength(0);
  });
  it("formats Lisbon summer time and accepts genuine empty selections", () => {
    expect(clock(Date.parse("2026-09-01T06:00:00Z"))).toBe("07:00:00");
    expect(validate(demo)).toBe(demo);
    expect(validate({ ...demo, observations: [] }).observations).toEqual([]);
    expect(() =>
      validate({ ...demo, observations: [row(100), row(0)] }),
    ).toThrow();
  });
});
