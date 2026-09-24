import { useEffect, useMemo, useRef, useState } from "react";

import { LatestRequest } from "./api";
import {
  duration,
  heldTrajectory,
  loadBunchingDiagram,
  loadBunchingLines,
  loadSharedLines,
  percent,
  type BunchingDiagram,
  type BunchingLine,
  type BunchingPair,
  type BunchingPoint,
  type BunchingTrip,
  type HoldAction,
  type SharedLine,
} from "./bunching";
import { clock } from "./replay";
import "./bunching.css";

const HOLDS = [0, 30, 60, 90, 120, 180];
const MAX_EXTRA_LINES = 5;
/** one colour per selected line (categorical, in fixed order; orange is kept for "risk") */
const LINE_COLORS = [
  "#2a78d6",
  "#1baf7a",
  "#4a3aa7",
  "#e87ba4",
  "#008300",
  "#eda100",
];

type PanelProps = {
  date: string;
  start: string;
  end: string;
  result: BunchingDiagram | null;
  onResult(value: BunchingDiagram | null): void;
};

/** Sidebar tab: choose one line (+ lines on the same route), predict and compare holding times. */
export function BunchingPanel({
  date,
  start,
  end,
  result,
  onResult,
}: PanelProps) {
  // Only lines/directions with at least 3 recorded trips in the window (from the API).
  const [lines, setLines] = useState<BunchingLine[] | null>(null);
  const [line, setLine] = useState(result?.line ?? "");
  const [direction, setDirection] = useState(result?.direction ?? "");
  const [shared, setShared] = useState<SharedLine[] | null>(null);
  const [extra, setExtra] = useState<string[]>(
    result?.lines.slice(1).map((l) => `${l.line}:${l.direction}`) ?? [],
  );
  const [hold, setHold] = useState(result?.selected.hold_s ?? 60);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const linesRequest = useRef(new LatestRequest());
  const sharedRequest = useRef(new LatestRequest());
  const diagramRequest = useRef(new LatestRequest());

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

  const current =
    lines?.find((item) => item.line === line) ?? lines?.[0] ?? null;
  const currentDirection =
    current?.directions.find((item) => item.id === direction) ??
    current?.directions[0] ??
    null;
  const currentLine = current?.line;
  const currentDirectionId = currentDirection?.id;

  // Lines that serve at least 3 stops of the chosen route (candidates for the corridor view)
  useEffect(() => {
    const request = sharedRequest.current;
    setShared(null);
    if (!currentLine || !currentDirectionId) return;
    void request
      .run((signal) =>
        loadSharedLines(
          {
            date,
            start,
            end,
            line: currentLine,
            direction: currentDirectionId,
          },
          signal,
        ),
      )
      .then((value) => {
        if (value) setShared(value.shared);
      })
      .catch((reason) => setError((reason as Error).message));
    return () => request.cancel();
  }, [date, start, end, currentLine, currentDirectionId]);

  const chosenExtra = extra.filter((key) =>
    shared?.some((item) => `${item.line}:${item.direction}` === key),
  );

  async function run(nextHold = hold) {
    if (!currentLine || !currentDirectionId) return;
    setLoading(true);
    setError("");
    try {
      const value = await diagramRequest.current.run((signal) =>
        loadBunchingDiagram(
          {
            date,
            start,
            end,
            line: currentLine,
            direction: currentDirectionId,
            with: chosenExtra,
            hold: nextHold,
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

  const s = result?.summary;
  const m = result?.model.metrics;
  const a = result?.model.alerting;
  const base = result?.scenarios.find((scenario) => scenario.hold_s === 0);
  const change = (bunched: number) =>
    base?.bunched_passages
      ? (bunched - base.bunched_passages) / base.bunched_passages
      : null;
  return (
    <>
      <span className="eyebrow">PREDICTION · WHAT-IF</span>
      <h1>Bunching</h1>
      <p className="muted">
        For every bus at every stop, the model predicts the chance that it
        bunches within the <strong>next stops</strong> (10 on one line, 5 across
        lines), while the gap is still healthy. Choose one line, or add lines
        that share its route to see bunching <em>between</em> lines. Uses the
        date and time window above.
      </p>
      {lines === null && !error && (
        <p className="muted">Finding lines with data in this window…</p>
      )}
      {lines !== null && !lines.length && (
        <p className="error">
          No CARRIS line has at least 3 recorded trips in this window. Choose
          another date or a longer time window.
        </p>
      )}
      {!!lines?.length && current && (
        <>
          <div className="bunching-form">
            <label>
              Line
              <select
                value={current.line}
                onChange={(event) => {
                  setLine(event.target.value);
                  setDirection("");
                  setExtra([]);
                }}
              >
                {lines.map((item) => (
                  <option key={item.line} value={item.line}>
                    {item.line} · {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Direction
              <select
                value={currentDirection?.id ?? ""}
                onChange={(event) => {
                  setDirection(event.target.value);
                  setExtra([]);
                }}
              >
                {current.directions.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.trips} trips)
                  </option>
                ))}
              </select>
            </label>
          </div>
          <h2>Lines on the same route</h2>
          {shared === null ? (
            <p className="muted">Looking for lines that share this route…</p>
          ) : !shared.length ? (
            <p className="muted">
              No other line with data serves 3 or more of these stops. The
              prediction will look at this line alone.
            </p>
          ) : (
            <div className="bunching-shared">
              {shared.slice(0, 12).map((item) => {
                const key = `${item.line}:${item.direction}`;
                const checked = chosenExtra.includes(key);
                return (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={
                        !checked && chosenExtra.length >= MAX_EXTRA_LINES
                      }
                      onChange={() =>
                        setExtra((values) =>
                          checked
                            ? values.filter((value) => value !== key)
                            : [...values, key],
                        )
                      }
                    />
                    <span>
                      <strong>
                        {item.line} {item.directionName}
                      </strong>
                      <small>
                        shares {item.sharedStops} of {item.routeStops} stops ·{" "}
                        {item.trips} trips
                      </small>
                    </span>
                  </label>
                );
              })}
            </div>
          )}
          <button
            className="primary bunching-run"
            disabled={loading}
            onClick={() => void run()}
          >
            {loading
              ? "Predicting…"
              : chosenExtra.length
                ? `Predict bunching on ${chosenExtra.length + 1} lines`
                : "Predict bunching"}
          </button>
        </>
      )}
      {error && <p className="error">{error}</p>}

      {result && s && (
        <>
          <h2>
            {result.lines.map((l) => l.line).join(" + ")} ·{" "}
            {result.directionName}
          </h2>
          <div className="bunching-stats">
            <div>
              <strong>{s.bunchedPassages}</strong>
              <small>
                bunched passages
                {result.mode === "corridor"
                  ? ` (${s.crossLineBunched} between lines)`
                  : ""}
              </small>
            </div>
            <div>
              <strong>{s.alerts}</strong>
              <small>alerts (risk ≥ {percent(result.threshold)})</small>
            </div>
            <div>
              <strong>
                {s.alertsChecked
                  ? percent(s.alertsThatBunched / s.alertsChecked)
                  : "–"}
              </strong>
              <small>of alerts really bunched</small>
            </div>
            <div>
              <strong>{s.trips}</strong>
              <small>trips in window</small>
            </div>
          </div>
          <p className="muted bunching-alert-note">
            {result.mode === "corridor" ? (
              <>
                <strong>Across lines</strong>, two buses count as bunched when
                they pass the same stop less than 60 s apart although they were
                planned at least 2 min apart.
              </>
            ) : (
              <>
                <strong>Same line</strong>: bunched when the gap is below 25% of
                the planned gap.
              </>
            )}{" "}
            Alert level {percent(result.threshold)} is set from the data
            {a?.test
              ? ` (on unseen days ${percent(a.test.precision)} of alerts were right, ${percent(a.test.recall)} of bunching was caught)`
              : ""}
            .
          </p>

          <h2>What if we hold buses?</h2>
          <p className="muted">
            Simulation on the real trips: when a bus reaches the alert level it
            waits at that stop (never closer than 60 s to the bus behind, up to
            3 times per trip). It then runs that much later, and every gap is
            recomputed.
          </p>
          <table className="bunching-runs">
            <thead>
              <tr>
                <th>Hold</th>
                <th>Holds</th>
                <th>Holding</th>
                <th>Bunched</th>
                <th>Change</th>
              </tr>
            </thead>
            <tbody>
              {result.scenarios.map((scenario) => (
                <tr
                  key={scenario.hold_s}
                  className={[
                    scenario.hold_s === result.selected.hold_s
                      ? "selected"
                      : "",
                    scenario.hold_s === result.recommendation?.hold_s
                      ? "recommended"
                      : "",
                  ].join(" ")}
                  onClick={() => {
                    setHold(scenario.hold_s);
                    void run(scenario.hold_s);
                  }}
                >
                  <td>{scenario.hold_s ? `${scenario.hold_s} s` : "none"}</td>
                  <td>{scenario.holds_made}</td>
                  <td>{scenario.total_hold_min} min</td>
                  <td>{scenario.bunched_passages}</td>
                  <td>
                    {scenario.hold_s
                      ? percent(change(scenario.bunched_passages))
                      : "–"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="bunching-recommendation">
            {result.recommendation && base ? (
              <>
                <strong>
                  Recommendation: hold up to {result.recommendation.hold_s} s
                </strong>
                <span>
                  Bunched passages {base.bunched_passages} →{" "}
                  {result.recommendation.bunched_passages} (
                  {percent(change(result.recommendation.bunched_passages))})
                  with {result.recommendation.holds_made} holds on{" "}
                  {result.recommendation.buses_held} buses,{" "}
                  {result.recommendation.total_hold_min} min of holding in
                  total. It is the shortest hold that gets at least 75% of the
                  best reduction.
                </span>
              </>
            ) : (
              <span>
                No holding time reduced bunching in this window (or no bus
                reached the alert level).
              </span>
            )}
          </div>
          <label className="check-row">
            Show on diagram
            <select
              value={hold}
              onChange={(event) => {
                const value = Number(event.target.value);
                setHold(value);
                void run(value);
              }}
            >
              {HOLDS.map((value) => (
                <option key={value} value={value}>
                  {value ? `hold ${value} s` : "no holding"}
                </option>
              ))}
            </select>
          </label>

          {m && (
            <details className="bunching-model">
              <summary>How good is the model?</summary>
              <p>
                {result.mode === "corridor"
                  ? "Across-lines model"
                  : "Same-line model"}
                :{" "}
                {result.model.kind === "gradient_boosted_trees"
                  ? "gradient-boosted trees"
                  : "logistic regression"}
                , trained on other days and tested on{" "}
                {m.n_test.toLocaleString()} passages from days it never saw.
                {result.model.holdTrigger?.kind === "logistic_regression" &&
                  result.model.kind !== "logistic_regression" &&
                  " Holds in the what-if are triggered by the simpler logistic model, which chose better holds in the simulator."}
              </p>
              <dl className="details-grid">
                <dt>ROC-AUC</dt>
                <dd>
                  {m.roc_auc} (baseline {m.baseline_roc_auc})
                </dd>
                <dt>Avg. precision</dt>
                <dd>
                  {m.average_precision} (baseline {m.baseline_average_precision}
                  )
                </dd>
                <dt>Base rate</dt>
                <dd>
                  {percent(m.test_positive_rate, 1)} bunch within{" "}
                  {result.model.horizon ?? 5} stops
                </dd>
                {a?.test && a.baseline_test && (
                  <>
                    <dt>Alerts right</dt>
                    <dd>
                      {percent(a.test.precision)} (simple rule{" "}
                      {percent(a.baseline_test.precision)})
                    </dd>
                    <dt>Bunching caught</dt>
                    <dd>
                      {percent(a.test.recall)} (simple rule{" "}
                      {percent(a.baseline_test.recall)})
                    </dd>
                  </>
                )}
              </dl>
              <p className="muted">
                Baseline = “the smaller the gap now, the higher the risk”
                {a?.baseline_rule ? `; simple rule = ${a.baseline_rule}` : ""}.
                The simulation assumes a held bus keeps its observed running
                times afterwards.
              </p>
            </details>
          )}
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Time–space diagram (overlay on the map area)                       */
/* ------------------------------------------------------------------ */

const W = 1000;
const H = 560;
const M = { l: 150, r: 18, t: 14, b: 30 };

/** light -> dark orange: one hue for "risk" (sequential scale) */
function riskColor(prob: number) {
  const a = [254, 230, 206];
  const b = [166, 54, 3];
  const k = Math.min(Math.max(prob, 0), 1) ** 0.6;
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * k)).join(",")})`;
}

type Hover = { trip: BunchingTrip; point: BunchingPoint; x: number; y: number };

export function BunchingDiagramView({
  result,
  onClose,
}: {
  result: BunchingDiagram;
  onClose(): void;
}) {
  const [hover, setHover] = useState<Hover | null>(null);
  const [focus, setFocus] = useState<BunchingPair | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const colorOf = useMemo(
    () =>
      new Map(
        result.lines.map((l, i) => [
          l.line,
          LINE_COLORS[i % LINE_COLORS.length],
        ]),
      ),
    [result],
  );
  const stopName = useMemo(
    () => new Map(result.stops.map((stop) => [stop.y, stop.name])),
    [result],
  );
  const holdsByTrip = useMemo(() => {
    const map = new Map<string, HoldAction[]>();
    result.selected.holds.forEach((h) =>
      map.set(h.trip_id, [...(map.get(h.trip_id) ?? []), h]),
    );
    return map;
  }, [result]);
  const t0 = result.startTimestamp;
  const t1 = result.endTimestamp;
  const n = Math.max(result.stops.length - 1, 1);
  const X = (t: number) => M.l + ((t - t0) / (t1 - t0)) * (W - M.l - M.r);
  const Y = (y: number) => H - M.b - (y / n) * (H - M.t - M.b);
  const path = (points: { t: number; y: number }[]) =>
    points
      .map(
        (p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.y).toFixed(1)}`,
      )
      .join("");
  const inFocus = (trip: BunchingTrip) =>
    !focus ||
    trip.trip_id === focus.follower_trip ||
    trip.trip_id === focus.leader_trip;

  const ticks: number[] = [];
  const step = t1 - t0 > 2 * 3600e3 ? 30 * 60e3 : 15 * 60e3;
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) ticks.push(t);
  const labelEvery = Math.max(1, Math.ceil(result.stops.length / 14));
  const all = result.trips.flatMap((trip) =>
    trip.points.map((point) => ({ trip, point })),
  );
  const holdMarks = result.selected.holds.flatMap((h) => {
    const trip = result.trips.find((item) => item.trip_id === h.trip_id);
    const point = trip?.points.find((p) => p.seq === h.seq);
    return trip && point ? [{ h, trip, point }] : [];
  });

  function onMove(event: React.PointerEvent<SVGRectElement>) {
    const box = svg.current!.getBoundingClientRect();
    const sx = ((event.clientX - box.left) * W) / box.width;
    const sy = ((event.clientY - box.top) * H) / box.height;
    let best: Hover | null = null;
    let bestD = 400; // max 20 px away
    for (const { trip, point } of all) {
      if (point.t < t0 || point.t > t1 || !inFocus(trip)) continue;
      const d = (X(point.t) - sx) ** 2 + (Y(point.y) - sy) ** 2;
      if (d < bestD) {
        bestD = d;
        best = { trip, point, x: event.clientX, y: event.clientY };
      }
    }
    setHover(best);
  }

  const hoverHolds = hover ? (holdsByTrip.get(hover.trip.trip_id) ?? []) : [];
  return (
    <section className="bunching-overlay" aria-label="Time-space diagram">
      <header>
        <div>
          <span className="eyebrow">TIME–SPACE DIAGRAM</span>
          <h2>
            {result.lines.map((l) => l.line).join(" + ")} ·{" "}
            {result.directionName} · {result.date}
          </h2>
          <p>
            Each line is one bus moving along the route of line {result.line}
            {result.mode === "corridor"
              ? " (other lines are drawn where they share its stops)"
              : ""}
            . Lines that converge are bunching. Dots show the predicted risk of
            bunching within {result.model.horizon ?? 5} stops.
          </p>
        </div>
        <button onClick={onClose}>Show map</button>
      </header>
      <div className="bunching-legend">
        {result.lines.map((l) => (
          <span key={l.line}>
            <i
              className="key-line"
              style={{ background: colorOf.get(l.line) }}
            />{" "}
            {l.line} {l.directionName}
          </span>
        ))}
        <span>
          <i className="key-dot" style={{ background: riskColor(0.1) }} />
          <i className="key-dot" style={{ background: riskColor(0.5) }} />
          <i className="key-dot" style={{ background: riskColor(0.9) }} /> risk
          (low → high)
        </span>
        <span>
          <i className="key-dot ring" /> alert (≥ {percent(result.threshold)})
        </span>
        <span>
          <i className="key-dot bunched" /> bunched
        </span>
        {result.selected.hold_s > 0 && (
          <span>
            <i className="key-line dashed" /> simulated, holding up to{" "}
            {result.selected.hold_s} s
          </span>
        )}
      </div>
      <div className="bunching-body">
        <svg
          ref={svg}
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMin meet"
          role="img"
          aria-label="Bus trips over time and stops"
        >
          <defs>
            <clipPath id="bunching-clip">
              <rect x={M.l} y={0} width={W - M.l - M.r} height={H} />
            </clipPath>
          </defs>
          {result.stops.map((stop, index) =>
            index % labelEvery === 0 || index === result.stops.length - 1 ? (
              <g key={stop.y}>
                <line
                  className="grid"
                  x1={M.l}
                  x2={W - M.r}
                  y1={Y(stop.y)}
                  y2={Y(stop.y)}
                />
                <text x={M.l - 8} y={Y(stop.y) + 4} textAnchor="end">
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
                y1={M.t}
                y2={H - M.b}
              />
              <text x={X(t)} y={H - M.b + 18} textAnchor="middle">
                {clock(t).slice(0, 5)}
              </text>
            </g>
          ))}
          <g clipPath="url(#bunching-clip)">
            {result.trips.map((trip) => (
              <path
                key={trip.trip_id}
                className={`trip${inFocus(trip) ? "" : " faded"}${focus && inFocus(trip) ? " focus" : ""}`}
                stroke={colorOf.get(trip.line)}
                d={path(trip.points)}
              />
            ))}
            {result.trips.map((trip) => {
              const ghost = heldTrajectory(
                trip,
                holdsByTrip.get(trip.trip_id) ?? [],
              );
              return ghost.length && inFocus(trip) ? (
                <path
                  key={`held-${trip.trip_id}`}
                  className="trip held"
                  stroke={colorOf.get(trip.line)}
                  d={path(ghost)}
                />
              ) : null;
            })}
            {all.map(({ trip, point }) =>
              !inFocus(trip) ? null : point.bunched ? (
                <circle
                  key={`${trip.trip_id}-${point.seq}`}
                  className="bunched"
                  cx={X(point.t)}
                  cy={Y(point.y)}
                  r={4}
                />
              ) : point.prob != null ? (
                <circle
                  key={`${trip.trip_id}-${point.seq}`}
                  className={point.prob >= result.threshold ? "alert" : "risk"}
                  cx={X(point.t)}
                  cy={Y(point.y)}
                  r={point.prob >= result.threshold ? 5 : 3}
                  fill={riskColor(point.prob)}
                />
              ) : null,
            )}
            {holdMarks.map(({ h, trip, point }) =>
              inFocus(trip) ? (
                <g key={`h-${h.trip_id}-${h.seq}`} className="hold-mark">
                  <circle cx={X(point.t)} cy={Y(point.y)} r={8} />
                  <text x={X(point.t)} y={Y(point.y) + 3.5} textAnchor="middle">
                    H
                  </text>
                </g>
              ) : null,
            )}
          </g>
          <line
            className="axis"
            x1={M.l}
            x2={W - M.r}
            y1={H - M.b}
            y2={H - M.b}
          />
          <rect
            x={M.l}
            y={M.t}
            width={W - M.l - M.r}
            height={H - M.t - M.b}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
          />
          {hover && (
            <circle
              className="hover-ring"
              cx={X(hover.point.t)}
              cy={Y(hover.point.y)}
              r={7}
            />
          )}
        </svg>
        <aside className="bunching-pairs">
          <h3>Buses that bunch most</h3>
          {!result.pairs.length && <p>No bunching in this window.</p>}
          <ol>
            {result.pairs.map((pair) => {
              const active =
                focus?.follower_trip === pair.follower_trip &&
                focus?.leader_trip === pair.leader_trip;
              return (
                <li key={`${pair.follower_trip}-${pair.leader_trip}`}>
                  <button
                    className={active ? "active" : ""}
                    onClick={() => setFocus(active ? null : pair)}
                  >
                    <strong>
                      <i
                        className="key-dot"
                        style={{ background: colorOf.get(pair.follower_line) }}
                      />
                      Bus {pair.follower_vehicle} ({pair.follower_line})
                    </strong>
                    <span>
                      right behind{" "}
                      <i
                        className="key-dot"
                        style={{ background: colorOf.get(pair.leader_line) }}
                      />
                      bus {pair.leader_vehicle} ({pair.leader_line})
                    </span>
                    <small>
                      bunched at {pair.stops} stop{pair.stops > 1 ? "s" : ""} ·
                      closest {duration(pair.min_gap_s)} ·{" "}
                      {clock(pair.first).slice(0, 5)}–
                      {clock(pair.last).slice(0, 5)}
                    </small>
                  </button>
                </li>
              );
            })}
          </ol>
          {focus && (
            <button className="bunching-clear" onClick={() => setFocus(null)}>
              Show all buses
            </button>
          )}
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
            Bus {hover.trip.vehicle_id} · line {hover.trip.line} ·{" "}
            {stopName.get(hover.point.y)}
          </small>
          <div>
            <b>{clock(hover.point.t)}</b> passed this stop
          </div>
          <div>
            <b>{duration(hover.point.headway_s)}</b> behind bus{" "}
            {hover.point.leader_vehicle ?? "–"}
            {hover.point.leader_line ? ` (${hover.point.leader_line})` : ""}
            {hover.point.sched_headway_s != null
              ? `, planned ${duration(hover.point.sched_headway_s)}`
              : ""}
          </div>
          <div>
            <b>{hover.point.bunched ? "bunched" : percent(hover.point.prob)}</b>{" "}
            {hover.point.bunched
              ? "right now"
              : `risk within ${result.model.horizon ?? 5} stops`}
          </div>
          {hover.point.bunched_within_5 != null && (
            <div>
              Really bunched within {result.model.horizon ?? 5} stops:{" "}
              <b>{hover.point.bunched_within_5 ? "yes" : "no"}</b>
            </div>
          )}
          {hoverHolds.map((h) => (
            <div key={h.seq}>
              Held {h.hold_s} s at stop {h.seq}: risk {percent(h.prob_before)} →{" "}
              <b>{percent(h.prob_after)}</b>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
