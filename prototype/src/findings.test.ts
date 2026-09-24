import { describe, expect, it } from "vitest";

import { heat, simWindow, stopLabel, type Problem } from "./findings";

describe("findings helpers", () => {
  it("colours rates relative to the network and caps at 6x", () => {
    expect(heat(null, 0.026)).toBe("transparent");
    expect(heat(0, 0.026)).toBe("rgb(250, 246, 234)");
    expect(heat(1, 0.026)).toBe("rgb(178, 34, 45)");
  });

  it("opens the simulator on a held-out weekday in the problem hours, max 4 h", () => {
    const problem = { hotHours: [17, 18, 19, 20] } as Problem;
    expect(simWindow(problem)).toEqual({
      date: "2026-09-04",
      start: "17:00",
      end: "21:00",
    });
    expect(simWindow({ hotHours: [21, 22, 23] } as Problem)).toEqual({
      date: "2026-09-04",
      start: "20:00",
      end: "23:59",
    });
  });

  it("names stops by the plan when known", () => {
    expect(stopLabel({ stop_id: "8316", name: "Cais do Sodré" })).toBe(
      "Cais do Sodré",
    );
    expect(stopLabel({ stop_id: "8316" })).toBe("stop 8316");
  });
});
