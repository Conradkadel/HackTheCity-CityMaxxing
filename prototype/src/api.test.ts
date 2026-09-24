import { expect, it } from "vitest";
import { LatestRequest, queryFor, type Selection } from "./api";

const selection: Selection = {
  date: "2026-09-01",
  start: "07:00",
  end: "09:00",
  areas: ["eycs2", "eyckp"],
  operators: ["IA9T6"],
  lines: ["755", "28E"],
  vehicleMode: "configured",
};

it("encodes explicit areas, operators, and configured public lines", () => {
  const params = new URLSearchParams(queryFor(selection));
  expect(params.getAll("area")).toEqual(["eycs2", "eyckp"]);
  expect(params.getAll("operator")).toEqual(["IA9T6"]);
  expect(params.getAll("line")).toEqual(["755", "28E"]);
});

it("omits line filters in all-vehicles mode", () => {
  expect(
    new URLSearchParams(queryFor({ ...selection, vehicleMode: "all" })).has(
      "line",
    ),
  ).toBe(false);
});

it("pins an explicitly requested preview version", () => {
  const params = new URLSearchParams(
    queryFor({ ...selection, preview: true, datasetVersion: 7 }),
  );
  expect(params.get("preview")).toBe("true");
  expect(params.get("dataset_version")).toBe("7");
});

it("ignores cancelled results even when transport completes late", async () => {
  const requests = new LatestRequest();
  let resolve!: (value: string) => void;
  let signal!: AbortSignal;
  const first = requests.run((current) => {
    signal = current;
    return new Promise<string>((done) => {
      resolve = done;
    });
  });
  const second = await requests.run(async () => "new");
  resolve("old");
  expect(signal.aborted).toBe(true);
  expect(await first).toBeUndefined();
  expect(second).toBe("new");
});
