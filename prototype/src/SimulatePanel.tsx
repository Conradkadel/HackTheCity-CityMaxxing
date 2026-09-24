import { useEffect, useMemo, useRef, useState } from "react";

import { LatestRequest } from "./api";
import { loadBunchingLines, type BunchingLine } from "./bunching";
import { clock } from "./replay";
import {
  bunchedSegments,
  loadSimRun,
  loadSimScenarios,
  PACKAGE_TEXT,
  SCENARIO_TEXT,
  scenarioCost,
  scenarioShort,
  bestOverall,
  bestTested,
  bestToday,
  coversTestHours,
  signed,
  type SimPoint,
  type SimRun,
  type SimScenario,
  type SimScenarioInfo,
} from "./sim";
import "./bunching.css";
import "./sim.css";

const PACKAGE_COLORS: Record<string, string> = {
  "no cost": "#1baf7a",
  "low cost": "#2a78d6",
  investment: "#4a3aa7",
  ceiling: "#9aa5a8",
};

/** Opened from the Findings tab: this line, direction and timing change, run straight away. */
export type SimPreset = { line: string; direction: string; scenario: string };

type PanelProps = {
  date: string;
  start: string;
  end: string;
  result: SimRun | null;
  /** a scenario clicked in the trade-off chart (a new object for every click) */
  pick?: { code: string } | null;
  preset?: SimPreset | null;
  onPresetDone?(): void;
  onResult(value: SimRun | null): void;
};

/** Sidebar tab: pick a line and a timing change, replay the day with it. */
export function SimulatePanel({
  date,
  start,
  end,
  result,
  pick,
  preset,
  onPresetDone,
  onResult,
}: PanelProps) {
  const [catalog, setCatalog] = useState<SimScenarioInfo[]>([]);
  const [scope, setScope] = useState<string[]>([]);
  const [lines, setLines] = useState<BunchingLine[] | null>(null);
  const [line, setLine] = useState(result?.line ?? "");
  const [direction, setDirection] = useState(result?.direction ?? "");
  const [scenario, setScenario] = useState(result?.scenario ?? "D2");
  const [seeds, setSeeds] = useState(result?.seeds ?? 10);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const infoRequest = useRef(new LatestRequest());
  const linesRequest = useRef(new LatestRequest());
  const runRequest = useRef(new LatestRequest());

  useEffect(() => {
    const request = infoRequest.current;
    void request
      .run((signal) => loadSimScenarios(signal))
      .then((value) => {
        if (!value) return;
        setCatalog(value.scenarios.filter((s) => s.code !== "AS"));
        setScope(value.scopeLines);
      })
      .catch((reason) => setError((reason as Error).message));
    return () => request.cancel();
  }, []);

  useEffect(() => {
    const request = linesRequest.current;
    setLines(null);
    void request
      .run((signal) => loadBunchingLines({ date, start, end }, signal))
      .then((value) => {
        if (value) setLines(value.lines);
      })
      .catch((reason) => setError((reason as Error).message));
    return () => request.cancel();
  }, [date, start, end]);

  // validated lines (the plan's scope) first
  const ordered = useMemo(() => {
    const all = lines ?? [];
    return [
      ...scope.flatMap((l) => all.filter((item) => item.line === l)),
      ...all.filter((item) => !scope.includes(item.line)),
    ];
  }, [lines, scope]);
  const current =
    ordered.find((item) => item.line === line) ?? ordered[0] ?? null;
  const currentDirection =
    current?.directions.find((item) => item.id === direction) ??
    current?.directions[0] ??
    null;

  async function run(nextScenario = scenario) {
    if (!current || !currentDirection) return;
    setLoading(true);
    setError("");
    try {
      const value = await runRequest.current.run((signal) =>
        loadSimRun(
          {
            date,
            start,
            end,
            line: current.line,
            direction: currentDirection.id,
            scenario: nextScenario,
            seeds,
          },
          signal,
        ),
      );
      if (value) onResult(value);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function choose(code: string) {
    setScenario(code);
    if (result) void run(code);
  }

  // a click on a dot in the trade-off chart (ignore the one handled before this panel was opened)
  const handledPick = useRef(pick);
  useEffect(() => {
    if (!pick || pick === handledPick.current) return;
    handledPick.current = pick;
    choose(pick.code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pick]);

  // a problem opened from the Findings tab: select it and run once its line is loaded
  const [pending, setPending] = useState<SimPreset | null>(null);
  useEffect(() => {
    if (!preset) return;
    setLine(preset.line);
    setDirection(preset.direction);
    setScenario(preset.scenario);
    setPending(preset);
    onPresetDone?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset]);
  useEffect(() => {
    if (!pending || !lines) return;
    if (!lines.some((item) => item.line === pending.line)) {
      setPending(null);
      setError(
        `Line ${pending.line} has too few recorded trips in this window.`,
      );
      return;
    }
    if (
      current?.line === pending.line &&
      currentDirection?.id === pending.direction
    ) {
      setPending(null);
      void run(pending.scenario);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, lines, current, currentDirection]);

  const rows = result?.scenarios.filter((s) => s.code !== "AS") ?? [];
  // one rule everywhere (sim.ts bestChange): the biggest reliable cut in waiting
  const testedCode =
    result && coversTestHours(result) ? bestTested(result) : null;
  const todayCode = result ? bestToday(result) : null;
  const bestCode = testedCode ?? todayCode;
  const best = rows.find((s) => s.code === bestCode);
  const todayBest = rows.find((s) => s.code === todayCode);
  const testedBest = testedCode
    ? result?.recommendation.heldOutScenarios?.[testedCode]
    : null;
  return (
    <>
      <span className="eyebrow">
        SIMULATION · WHAT IF WE CHANGE THE TIMETABLE?
      </span>
      <h1>Simulation</h1>
      <p className="muted">
        Replays a real day bus by bus with one change: <b>when</b> buses leave
        the terminal or wait at a stop. Everything else (traffic, stop times) is
        what really happened. The date and time window are in the bar under the
        map.
      </p>
      {error && <p className="error">{error}</p>}
      {!lines && !error && <p className="muted">Loading lines…</p>}
      {lines && !ordered.length && (
        <p className="muted">No line has enough trips in this window.</p>
      )}
      {current && (
        <div className="bunching-form">
          <label>
            Line
            <select
              value={current.line}
              onChange={(event) => {
                setLine(event.target.value);
                setDirection("");
              }}
            >
              {scope.length > 0 && (
                <optgroup label="Validated (plan scope)">
                  {ordered
                    .filter((item) => scope.includes(item.line))
                    .map((item) => (
                      <option key={item.line} value={item.line}>
                        {item.line} · {item.name}
                      </option>
                    ))}
                </optgroup>
              )}
              <optgroup label="Other lines">
                {ordered
                  .filter((item) => !scope.includes(item.line))
                  .map((item) => (
                    <option key={item.line} value={item.line}>
                      {item.line} · {item.name}
                    </option>
                  ))}
              </optgroup>
            </select>
          </label>
          <label>
            Direction
            <select
              value={currentDirection?.id ?? ""}
              onChange={(event) => setDirection(event.target.value)}
            >
              {current.directions.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.trips} trips)
                </option>
              ))}
            </select>
          </label>
          <label>
            Precision
            <select
              value={seeds}
              onChange={(event) => setSeeds(Number(event.target.value))}
            >
              <option value={10}>Fast (10 repeats)</option>
              <option value={30}>Precise (30 repeats)</option>
            </select>
          </label>
        </div>
      )}
      <h2>Choose a change</h2>
      <div className="sim-cards" role="radiogroup" aria-label="Change to test">
        {catalog
          .filter((s) => SCENARIO_TEXT[s.code]?.main)
          .map((s) => (
            <ScenarioCard
              key={s.code}
              scenario={s}
              active={scenario === s.code}
              best={bestCode === s.code}
              onChoose={choose}
            />
          ))}
      </div>
      <details
        className="sim-more"
        open={!!scenario && !SCENARIO_TEXT[scenario]?.main}
      >
        <summary>
          More variants (
          {catalog.filter((s) => !SCENARIO_TEXT[s.code]?.main).length})
        </summary>
        <div className="sim-cards" role="radiogroup" aria-label="More variants">
          {catalog
            .filter((s) => !SCENARIO_TEXT[s.code]?.main)
            .map((s) => (
              <ScenarioCard
                key={s.code}
                scenario={s}
                active={scenario === s.code}
                best={bestCode === s.code}
                onChoose={choose}
              />
            ))}
        </div>
      </details>
      <button
        className="primary bunching-run"
        disabled={!current || loading}
        onClick={() => void run()}
      >
        {loading ? "Simulating…" : "Run the simulation"}
      </button>
      {loading && !result && (
        <p className="muted">
          The first run of a line takes about 15 s (it tries every change at
          once). Switching between changes afterwards is instant.
        </p>
      )}
      {result && (
        <>
          <div className="bunching-recommendation">
            {best ? (
              <>
                <strong>Best change: {best.name}</strong>
                <p>
                  {testedBest ? (
                    <>
                      Over the test days (
                      {result.validation?.testDays.join(" and ")}, 16–20 h)
                      passengers waited{" "}
                      <b>{Math.round(testedBest.ewt_saved)} s less</b> on
                      average. On this day:{" "}
                    </>
                  ) : (
                    <>On this day: </>
                  )}
                  {Math.round(best.ewtSaved ?? 0)} s less waiting, bunched stop
                  visits {result.baseline.bunched_pct?.toFixed(1)} % →{" "}
                  {best.kpis.bunched_pct?.mean.toFixed(1)} %.
                  {best.extraVehicles
                    ? ` Needs ${best.extraVehicles} extra bus${best.extraVehicles > 1 ? "es" : ""}.`
                    : " No extra bus needed."}
                </p>
                {todayBest && todayBest.code !== best.code && (
                  <p className="muted">
                    On this single day, “{todayBest.name}” cut waiting slightly
                    more ({Math.round(todayBest.ewtSaved ?? 0)} s). One day is
                    noisy, so we recommend the change that worked best over the
                    test days.
                  </p>
                )}
              </>
            ) : (
              <strong>No change helps reliably on this day and line.</strong>
            )}
            <details>
              <summary>How we pick the best change</summary>
              <p className="muted">
                Keep the changes that cut waiting reliably (in at least 95 % of
                the repeats, and on both test days where available). Of those,
                pick the one with the <b>biggest cut</b>. If two are practically
                equal (within 1 s or 5 %), the cheaper one wins. “Leave exactly
                on time” is only a best case for comparison. The Findings tab
                uses the same rule.
              </p>
            </details>
          </div>
          <details className="sim-compare">
            <summary>Compare all changes</summary>
            <table className="bunching-runs">
              <thead>
                <tr>
                  <th>Change</th>
                  <th>Bunched</th>
                  <th>Wait saved</th>
                  <th>Delay / trip</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>As run</td>
                  <td>{result.baseline.bunched_pct?.toFixed(1)}%</td>
                  <td>–</td>
                  <td>–</td>
                </tr>
                {rows.map((s) => (
                  <tr
                    key={s.code}
                    className={`${s.code === result.scenario ? "selected" : ""}${s.code === bestCode ? " recommended" : ""}`}
                    onClick={() => choose(s.code)}
                  >
                    <td title={s.name}>{scenarioShort(s.code)}</td>
                    <td>{s.kpis.bunched_pct?.mean.toFixed(1)}%</td>
                    <td className={(s.ewtSaved ?? 0) > 0 ? "good" : "bad"}>
                      {signed(s.ewtSaved)} s
                    </td>
                    <td>
                      {Math.round(scenarioCost(s))} s
                      {s.extraVehicles ? ` +${s.extraVehicles} bus` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              Wait saved = seconds less waiting per passenger. Delay per trip =
              seconds a bus spends waiting at the terminal or at a stop because
              of the change.
            </p>
          </details>
          <GateNote run={result} />
        </>
      )}
    </>
  );
}

function ScenarioCard({
  scenario,
  active,
  best,
  onChoose,
}: {
  scenario: SimScenarioInfo;
  active: boolean;
  best: boolean;
  onChoose(code: string): void;
}) {
  return (
    <button
      role="radio"
      aria-checked={active}
      className={active ? "active" : ""}
      onClick={() => onChoose(scenario.code)}
    >
      <span>
        <b>{scenario.name}</b>
        {best && <em className="sim-star"> ★ best</em>}
      </span>
      <small>{scenario.lever}.</small>
      {scenario.package && (
        <i
          className="sim-pill"
          style={{ background: PACKAGE_COLORS[scenario.package] }}
        >
          {PACKAGE_TEXT[scenario.package] ?? scenario.package}
        </i>
      )}
    </button>
  );
}

function GateNote({ run }: { run: SimRun }) {
  const v = run.validation;
  if (!v)
    return (
      <p className="muted">
        The simulator has not been validated yet (run
        backend/validate_simulator.py).
      </p>
    );
  return (
    <details className="bunching-model">
      <summary>
        Validation gate:{" "}
        <span className={`sim-gate ${v.status}`}>{v.status}</span>
      </summary>
      <p>
        With no change the replay reproduces every day exactly. A resampled
        baseline (every run time drawn from the day&apos;s traffic record)
        reproduces which departure gaps bunch most and how bunching grows along
        the route on the held-out days {v.testDays.join(", ")}. Stop-time
        feedback k = {v.k} was fitted on {v.fitDays.join(", ")}.
      </p>
      {v.note && <p className="muted">{v.note}</p>}
      <p className="muted">
        Not modelled: passenger loads, driver rules and breaks, other operators
        at shared stops. Leave-on-schedule and turnaround assume the bus could
        leave as soon as it was back (+ at most 1 min).
      </p>
    </details>
  );
}

/* ------------------------------------------------------------------ */
/* Overlay: KPI cards, as run vs scenario diagrams, trade-off chart    */
/* ------------------------------------------------------------------ */

export function SimulationView({
  run,
  onPick,
  onClose,
}: {
  run: SimRun;
  onPick(code: string): void;
  onClose(): void;
}) {
  const scenario = run.scenarios.find((s) => s.code === run.scenario)!;
  const [hover, setHover] = useState<HoverInfo | null>(null);
  return (
    <section className="bunching-overlay sim-overlay" aria-label="Simulation">
      <header>
        <div>
          <span className="eyebrow">SIMULATION · {run.date}</span>
          <h2>
            Line {run.line} {run.directionName}: {scenario.name}
          </h2>
          <p>
            {scenario.lever}. Top: what really happened. Bottom: the same day
            with this change (grey = where the buses really were). Red = bunched
            (gap below 25 % of plan).
          </p>
        </div>
        <button onClick={onClose}>Show map</button>
      </header>
      <KpiCards run={run} scenario={scenario} />
      <div className="sim-body">
        <div className="sim-diagrams">
          <SimDiagram run={run} which="asRun" onHover={setHover} />
          <SimDiagram run={run} which="simulated" onHover={setHover} />
        </div>
        <aside className="sim-side">
          <TradeOff run={run} onPick={onPick} />
          <p className="muted">
            Each dot is one change: how many seconds of waiting it saves per
            passenger (higher is better) against how long buses have to wait
            because of it (further right costs more). Bars = range over{" "}
            {run.seeds} repeats. ★ = best change. Click a dot to see it.
          </p>
        </aside>
      </div>
      {hover && (
        <div
          className="bunching-tip"
          style={{
            left: Math.min(hover.x + 14, window.innerWidth - 250),
            top: hover.y + 14,
          }}
        >
          <small>
            Bus {hover.vehicle} · {hover.stop}
          </small>
          <div>
            <b>{clock(hover.t)}</b>{" "}
            {hover.which === "asRun" ? "really passed" : "simulated"}
          </div>
          {hover.shift != null && (
            <div>
              <b>{signed(hover.shift / 60, 1)} min</b> vs what really happened
            </div>
          )}
          {hover.bunched && <div className="bad">bunched here</div>}
        </div>
      )}
    </section>
  );
}

function KpiCards({ run, scenario }: { run: SimRun; scenario: SimScenario }) {
  const b = run.baseline;
  const k = scenario.kpis;
  const cards: {
    label: string;
    base: number | null;
    value?: { mean: number; min: number; max: number };
    unit: string;
    digits: number;
    better: "down" | "up" | "cost";
  }[] = [
    {
      label: "Bunched stop visits",
      base: b.bunched_pct,
      value: k.bunched_pct,
      unit: "%",
      digits: 1,
      better: "down",
    },
    {
      label: "Extra waiting per passenger",
      base: b.ewt_s,
      value: k.ewt_s,
      unit: " s",
      digits: 0,
      better: "down",
    },
    {
      label: "Irregular gaps (0 = perfectly even)",
      base: b.headway_cv,
      value: k.headway_cv,
      unit: "",
      digits: 2,
      better: "down",
    },
    {
      label: "Held at stops, per trip",
      base: 0,
      value: k.hold_s_per_trip,
      unit: " s",
      digits: 0,
      better: "cost",
    },
    {
      label: "Waiting at terminal, per trip",
      base: 0,
      value: k.terminal_wait_s_per_trip,
      unit: " s",
      digits: 0,
      better: "cost",
    },
    {
      label: "Trip time",
      base: b.trip_time_min,
      value: k.trip_time_min,
      unit: " min",
      digits: 1,
      better: "cost",
    },
  ];
  return (
    <div className="sim-kpis">
      {cards.map((card) => {
        const delta =
          card.value && card.base != null ? card.value.mean - card.base : null;
        const good =
          delta == null || Math.abs(delta) < 1e-9
            ? ""
            : card.better === "cost"
              ? "cost"
              : delta < 0
                ? "good"
                : "bad";
        return (
          <div key={card.label} className={`sim-kpi ${good}`}>
            <small>{card.label}</small>
            <strong>
              {card.value ? card.value.mean.toFixed(card.digits) : "–"}
              {card.unit}
            </strong>
            <span>
              {signed(delta, card.digits)}
              {card.unit} vs as run {card.base?.toFixed(card.digits)}
              {card.unit}
            </span>
            {card.value && card.value.max - card.value.min > 0 && (
              <em>
                range {card.value.min.toFixed(card.digits)}–
                {card.value.max.toFixed(card.digits)}
              </em>
            )}
          </div>
        );
      })}
      <div className="sim-kpi">
        <small>Extra buses</small>
        <strong>{scenario.extraVehicles}</strong>
        <span>{run.baseline.trips} trips in the window</span>
      </div>
    </div>
  );
}

type HoverInfo = {
  which: "asRun" | "simulated";
  vehicle: string;
  stop: string;
  t: number;
  shift: number | null;
  bunched: boolean;
  x: number;
  y: number;
};

const DW = 1000;
const DH = 320;
const DM = { l: 150, r: 14, t: 22, b: 22 };

function SimDiagram({
  run,
  which,
  onHover,
}: {
  run: SimRun;
  which: "asRun" | "simulated";
  onHover(value: HoverInfo | null): void;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const t0 = run.startTimestamp;
  const t1 = run.endTimestamp;
  const n = Math.max(run.stops.length - 1, 1);
  const X = (t: number) => DM.l + ((t - t0) / (t1 - t0)) * (DW - DM.l - DM.r);
  const Y = (y: number) => DH - DM.b - (y / n) * (DH - DM.t - DM.b);
  const path = (points: SimPoint[]) =>
    points
      .map(
        (p, i) => `${i ? "L" : "M"}${X(p[1]).toFixed(1)},${Y(p[0]).toFixed(1)}`,
      )
      .join("");
  const stopName = new Map(run.stops.map((s) => [s.y, s.name]));
  const ticks: number[] = [];
  const step = t1 - t0 > 2 * 3600e3 ? 30 * 60e3 : 15 * 60e3;
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) ticks.push(t);
  const labelEvery = Math.max(1, Math.ceil(run.stops.length / 7));
  const bunchedCount = run.trips.reduce(
    (sum, trip) =>
      sum + trip[which].filter((p) => p[2] && p[1] >= t0 && p[1] <= t1).length,
    0,
  );
  const clip = `sim-clip-${which}`;

  function onMove(event: React.PointerEvent<SVGRectElement>) {
    const box = svg.current!.getBoundingClientRect();
    const sx = ((event.clientX - box.left) * DW) / box.width;
    const sy = ((event.clientY - box.top) * DH) / box.height;
    let best: HoverInfo | null = null;
    let bestD = 300;
    for (const trip of run.trips) {
      const real = new Map(trip.asRun.map((p) => [p[0], p[1]]));
      for (const p of trip[which]) {
        const d = (X(p[1]) - sx) ** 2 + (Y(p[0]) - sy) ** 2;
        if (d < bestD) {
          bestD = d;
          const r = real.get(p[0]);
          best = {
            which,
            vehicle: trip.vehicle,
            stop: stopName.get(p[0]) ?? "",
            t: p[1],
            shift:
              which === "simulated" && r != null ? (p[1] - r) / 1000 : null,
            bunched: !!p[2],
            x: event.clientX,
            y: event.clientY,
          };
        }
      }
    }
    onHover(best);
  }

  return (
    <figure className={`sim-diagram ${which}`}>
      <figcaption>
        <b>
          {which === "asRun"
            ? "As run"
            : `With the change: ${scenarioShort(run.scenario)}`}
        </b>
        <span className="bad">{bunchedCount} bunched passages</span>
      </figcaption>
      <svg
        ref={svg}
        viewBox={`0 0 ${DW} ${DH}`}
        preserveAspectRatio="xMidYMin meet"
        role="img"
        aria-label={
          which === "asRun"
            ? "Buses as they really ran"
            : "Buses with the timing change"
        }
      >
        <defs>
          <clipPath id={clip}>
            <rect x={DM.l} y={0} width={DW - DM.l - DM.r} height={DH} />
          </clipPath>
        </defs>
        {run.stops.map((stop, index) =>
          index % labelEvery === 0 ||
          (index === run.stops.length - 1 &&
            index % labelEvery > labelEvery / 2) ? (
            <g key={stop.y}>
              <line
                className="grid"
                x1={DM.l}
                x2={DW - DM.r}
                y1={Y(stop.y)}
                y2={Y(stop.y)}
              />
              <text x={DM.l - 8} y={Y(stop.y) + 4} textAnchor="end">
                {stop.name.length > 22
                  ? `${stop.name.slice(0, 21)}…`
                  : stop.name}
              </text>
            </g>
          ) : null,
        )}
        {ticks.map((t) => (
          <g key={t}>
            <line
              className="grid"
              x1={X(t)}
              x2={X(t)}
              y1={DM.t}
              y2={DH - DM.b}
            />
            <text x={X(t)} y={DH - DM.b + 16} textAnchor="middle">
              {clock(t).slice(0, 5)}
            </text>
          </g>
        ))}
        <g clipPath={`url(#${clip})`}>
          {which === "simulated" &&
            run.trips.map((trip) => (
              <path
                key={`g-${trip.id}`}
                className="trip ghost"
                d={path(trip.asRun)}
              />
            ))}
          {run.trips.map((trip) => (
            <path
              key={trip.id}
              className={`trip ${which}`}
              d={path(trip[which])}
            />
          ))}
          {run.trips.flatMap((trip) =>
            bunchedSegments(trip[which]).map((segment, i) => (
              <path
                key={`b-${trip.id}-${i}`}
                className="trip red"
                d={path(segment)}
              />
            )),
          )}
          {which === "simulated" &&
            run.dispatch.map((d) =>
              d.y == null ? null : (
                <g key={`d-${d.trip}`} className="sim-mark dispatch">
                  <line
                    x1={X(d.t)}
                    x2={X(d.t + d.shift_s * 1000)}
                    y1={Y(d.y)}
                    y2={Y(d.y)}
                  />
                  <circle cx={X(d.t + d.shift_s * 1000)} cy={Y(d.y)} r={7} />
                  <text
                    x={X(d.t + d.shift_s * 1000)}
                    y={Y(d.y) + 3}
                    textAnchor="middle"
                  >
                    D
                  </text>
                </g>
              ),
            )}
          {which === "simulated" &&
            run.holds.map((h, i) =>
              h.y == null ? null : (
                <g key={`h-${i}`} className="sim-mark hold">
                  <circle cx={X(h.t)} cy={Y(h.y)} r={7} />
                  <text x={X(h.t)} y={Y(h.y) + 3} textAnchor="middle">
                    H
                  </text>
                </g>
              ),
            )}
        </g>
        <line
          className="axis"
          x1={DM.l}
          x2={DW - DM.r}
          y1={DH - DM.b}
          y2={DH - DM.b}
        />
        <rect
          x={DM.l}
          y={DM.t}
          width={DW - DM.l - DM.r}
          height={DH - DM.t - DM.b}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => onHover(null)}
        />
      </svg>
    </figure>
  );
}

const TW = 340;
const TH = 250;
const TM = { l: 44, r: 12, t: 12, b: 34 };

function TradeOff({
  run,
  onPick,
}: {
  run: SimRun;
  onPick(code: string): void;
}) {
  const rows = run.scenarios.filter(
    (s) => s.code !== "AS" && s.ewtSaved != null,
  );
  const values = rows.flatMap((s) => {
    const e = s.kpis.ewt_s;
    const base = run.baseline.ewt_s ?? 0;
    return e
      ? [base - e.max, base - e.min, s.ewtSaved ?? 0]
      : [s.ewtSaved ?? 0];
  });
  const yMin = Math.min(0, ...values);
  const yMax = Math.max(1, ...values);
  const xMax = Math.max(30, ...rows.map(scenarioCost)) * 1.1;
  const X = (v: number) => TM.l + (v / xMax) * (TW - TM.l - TM.r);
  const Y = (v: number) =>
    TH - TM.b - ((v - yMin) / (yMax - yMin)) * (TH - TM.t - TM.b);
  const base = run.baseline.ewt_s ?? 0;
  return (
    <svg
      className="sim-tradeoff"
      viewBox={`0 0 ${TW} ${TH}`}
      role="img"
      aria-label="Benefit vs cost of each timing change"
    >
      <line className="axis" x1={TM.l} x2={TW - TM.r} y1={Y(0)} y2={Y(0)} />
      <line className="axis" x1={TM.l} x2={TM.l} y1={TM.t} y2={TH - TM.b} />
      <text x={TM.l - 6} y={Y(yMax) + 4} textAnchor="end">
        {Math.round(yMax)}
      </text>
      <text x={TM.l - 6} y={Y(0) + 4} textAnchor="end">
        0
      </text>
      {yMin < 0 && (
        <text x={TM.l - 6} y={Y(yMin) + 4} textAnchor="end">
          {Math.round(yMin)}
        </text>
      )}
      <text x={TW - TM.r} y={TH - 8} textAnchor="end">
        cost: seconds buses wait per trip → {Math.round(xMax)}
      </text>
      <text
        x={12}
        y={TM.t + 2}
        transform={`rotate(-90 12 ${TM.t + 2})`}
        textAnchor="end"
      >
        waiting saved (s per passenger)
      </text>
      {rows.map((s) => {
        const x = X(scenarioCost(s));
        const e = s.kpis.ewt_s;
        const active = s.code === run.scenario;
        const star = s.code === bestOverall(run);
        return (
          <g
            key={s.code}
            className={`sim-dot${active ? " active" : ""}`}
            onClick={() => onPick(s.code)}
            role="button"
            aria-label={`${s.name}: saves ${s.ewtSaved} s`}
          >
            {e && (
              <line x1={x} x2={x} y1={Y(base - e.min)} y2={Y(base - e.max)} />
            )}
            <circle
              cx={x}
              cy={Y(s.ewtSaved ?? 0)}
              r={active ? 7 : 5.5}
              fill={PACKAGE_COLORS[s.package] ?? "#6b8790"}
              strokeDasharray={s.extraVehicles ? "2 2" : undefined}
            />
            <text
              x={x > TW - 90 ? x - 9 : x + 9}
              y={Y(s.ewtSaved ?? 0) + 4}
              textAnchor={x > TW - 90 ? "end" : "start"}
            >
              {scenarioShort(s.code)}
              {star ? " ★" : ""}
              {s.extraVehicles ? ` (+${s.extraVehicles} bus)` : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
