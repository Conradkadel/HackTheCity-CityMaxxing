import { describe, it, expect } from "vitest";
import { geohashBounds } from "./geohash";

describe("geohashBounds", () => {
  it("decodes a cell around Lisbon and rejects invalid hashes", () => {
    const [[south, west], [north, east]] = geohashBounds("eycs2");
    expect(south).toBeLessThan(38.75);
    expect(north).toBeGreaterThan(38.72);
    expect(west).toBeLessThan(-9.12);
    expect(east).toBeGreaterThan(-9.14);
    expect(() => geohashBounds("eycs!")).toThrow("Invalid geohash");
  });
});
