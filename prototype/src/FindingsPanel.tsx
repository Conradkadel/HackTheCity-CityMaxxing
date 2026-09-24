import React, { useState } from "react";

import {
  CAUSES,
  CORRIDOR_COLOR,
  DAYS,
  heat,
  pct,
  problemTitle,
  stopLabel,
  type Cause,
  fixOf,
  type Findings,
  type Problem,
} from "./findings";

export type MapFocus =
  | { kind: "problem"; index: number }
  | { kind: "corridor"; index: number }
  | { kind: "area"; index: number }
  | null;

const range = (from: number, to: number) =>
  Array.from({ length: to - from }, (_, i) => from + i);

const plural = (n: number, word: string) =>
  `${n} ${word}${n === 1 ? "" : word.endsWith("s") ? "es" : "s"}`;

function CauseChip({ cause }: { cause: Cause }) {
  const info = CAUSES[cause];
  return (
    <i className="cause-chip" style={{ background: info.color }}>
      {info.label}
    </i>
  );
}

/** Round a share to "n in 10" (at least 1 when there is any). */
const inTen = (value: number) =>
  value > 0 ? Math.max(1, Math.round(value * 10)) : 0;

/** The one number that shows the cause, as "this line vs all lines". */
function measureOf(p: Problem, f: Findings) {
  const h = f.headline;
  if (p.cause === "turnaround")
    return {
      question: "Trips that start late because the previous trip arrived late",
      line: p.evidence.prevTripLate,
      network: h.networkPrevTripLate,
    };
  if (p.cause === "dispatch")
    return {
      question:
        "Trips that leave the terminal too close behind the bus in front",
      line: p.evidence.departTooClose,
      network: h.networkDepartTooClose,
    };
  return null;
}

/** One plain sentence of evidence for the cause of a problem line. */
function evidence(p: Problem, f: Findings) {
  const m = measureOf(p, f);
  if (p.cause === "turnaround" && m)
    return `${inTen(m.line)} in 10 trips start late because the previous trip arrived more than 5 min late. On an average line it is ${inTen(m.network)} in 10.`;
  if (p.cause === "dispatch" && m)
    return `${inTen(m.line)} in 10 trips leave the terminal too close behind the bus in front. On an average line it is ${inTen(m.network)} in 10.`;
  return `Most trips leave on time; bunching usually starts about ${pct(p.evidence.onsetMedianProgress)} of the way along the route.`;
}

/** Lines per recommended change, for the "three moves" summary. */
function movesOf(f: Findings) {
  const by: Record<Cause, string[]> = {
    dispatch: [],
    turnaround: [],
    road: [],
  };
  f.problems.forEach((p) => {
    if (!by[p.cause].includes(p.line)) by[p.cause].push(p.line);
  });
  return by;
}

/* ------------------------------------------------------------------ */
/* Sidebar: the story, each problem clickable on the map               */
/* ------------------------------------------------------------------ */

export function FindingsPanel({
  findings,
  error,
  focus,
  onFocus,
  onOpenPlan,
  onTest,
}: {
  findings: Findings | null;
  error: string;
  focus: MapFocus;
  onFocus(value: MapFocus): void;
  onOpenPlan(): void;
  onTest(problem: Problem): void;
}) {
  if (error)
    return (
      <>
        <span className="eyebrow">FINDINGS</span>
        <h1>Where to act</h1>
        <p className="error">{error}</p>
      </>
    );
  if (!findings) return <p className="muted">Loading the week's findings…</p>;
  const h = findings.headline;
  return (
    <>
      <span className="eyebrow">
        FINDINGS · {findings.source.operator.split(" ")[0]} ·{" "}
        {findings.source.from} → {findings.source.to}
      </span>
      <h1>Where to act</h1>
      <p className="muted">
        One week of real GPS data ({findings.source.passages.toLocaleString()}{" "}
        bus stop visits). Bunching is not random: it happens on the same lines,
        at the same stops, in the same hours, <b>every weekday</b>.
      </p>
      <div className="finding-stats">
        <div>
          <strong>{pct(h.topLinesBunchingShare)}</strong>
          <span>
            of all bunching happens on just 5 of {findings.source.lines} lines (
            {h.topLines.join(", ")}), which make only{" "}
            {pct(h.topLinesPassageShare)} of all stop visits
          </span>
        </div>
        <div>
          <strong>{h.peakHours.join(", ")}</strong>
          <span>
            is the worst time on weekdays; {pct(h.weekdayRate, 1)} of stop
            visits are bunched on weekdays, {pct(h.weekendRate, 1)} at weekends
          </span>
        </div>
        <div>
          <strong>{pct(h.departTooCloseBunchingShare)}</strong>
          <span>
            of bunching comes from the {pct(h.departTooCloseTripShare)} of trips
            that <b>left the terminal too soon</b> after the bus in front
          </span>
        </div>
      </div>
      <button className="primary finding-plan" onClick={onOpenPlan}>
        Open the action plan
      </button>

      <h2 className="finding-h2">
        <span>1</span> Problem lines · click one to see it on the map
      </h2>
      <ol className="problem-list">
        {findings.problems.map((p, index) => {
          const active = focus?.kind === "problem" && focus.index === index;
          return (
            <li key={`${p.line}-${p.direction}-${p.block}`}>
              <button
                className={active ? "active" : ""}
                onClick={() =>
                  onFocus(active ? null : { kind: "problem", index })
                }
                aria-expanded={active}
              >
                <span className="problem-line">{p.line}</span>
                <span className="problem-body">
                  <b>{problemTitle(p).replace(`Line ${p.line} `, "")}</b>
                  <small>
                    {p.hours.join(", ")} · {p.timesNetwork}× the average ·{" "}
                    {p.daysHot}/5 weekdays
                  </small>
                  <CauseChip cause={p.cause} />
                </span>
              </button>
              {active && (
                <div className="problem-detail">
                  <p>
                    <b>Why:</b> {CAUSES[p.cause].problem}.{" "}
                    {evidence(p, findings)}
                  </p>
                  <p>
                    <b>Change:</b> {fixOf(p).name}. {fixOf(p).how}
                  </p>
                  {p.stretch.length > 0 && (
                    <p>
                      <b>Worst stops:</b>{" "}
                      {p.stretch.map((s) => stopLabel(s)).join(" → ")}
                    </p>
                  )}
                  <button className="finding-test" onClick={() => onTest(p)}>
                    Open in Simulation →
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ol>

      <h2 className="finding-h2">
        <span>2</span> Shared streets · different lines arrive together
      </h2>
      <p className="muted">
        About {Math.round(h.corridorEventsPerWeekday).toLocaleString()} times
        per weekday, buses of two lines that share a street run together for 3
        or more stops (less than 60 s apart). In{" "}
        {pct(h.corridorPlannedTogether)} of these cases the timetable already
        plans them less than 2 min apart.
      </p>
      <ol className="problem-list">
        {findings.corridors.slice(0, 5).map((c, index) => {
          const active = focus?.kind === "corridor" && focus.index === index;
          return (
            <li key={c.pair}>
              <button
                className={active ? "active" : ""}
                onClick={() =>
                  onFocus(active ? null : { kind: "corridor", index })
                }
                aria-pressed={active}
              >
                <span
                  className="problem-line pair"
                  style={{ background: CORRIDOR_COLOR }}
                >
                  {c.lines.join(" + ")}
                </span>
                <span className="problem-body">
                  <b>
                    Together {Math.round(c.eventsPerWeekday)}× per weekday ·{" "}
                    {c.sharedStops.length} shared stops
                  </b>
                  <small>
                    peaks {c.peakHours.slice(0, 2).join(", ")} ·{" "}
                    {c.daysWithEvents}/5 weekdays
                  </small>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {(findings.areas ?? []).length > 0 && (
        <>
          <h2 className="finding-h2">
            <span>3</span> Areas where buses catch up more than expected
          </h2>
          <p className="muted">
            Bunching is mostly spread across the city, but in these places buses
            that left on time catch up with the bus in front far more often than
            expected, on most weekdays.
          </p>
          <ol className="problem-list">
            {(findings.areas ?? []).map((area, index) => {
              const active = focus?.kind === "area" && focus.index === index;
              return (
                <li key={`${area.lat}-${area.lon}`}>
                  <button
                    className={active ? "active" : ""}
                    onClick={() =>
                      onFocus(active ? null : { kind: "area", index })
                    }
                    aria-pressed={active}
                  >
                    <span className="problem-line area">{area.ratio}×</span>
                    <span className="problem-body">
                      <b>
                        Around{" "}
                        {area.stops[0] ? stopLabel(area.stops[0]) : "this area"}
                      </b>
                      <small>
                        {area.days}/5 weekdays · {area.lines} lines · worst{" "}
                        {area.peakHours.slice(0, 2).join(", ")}
                      </small>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </>
      )}
      <p className="muted finding-foot">{findings.source.definition}</p>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Why one line bunches: evidence vs the network and where on the route */
/* ------------------------------------------------------------------ */

/** Ten dots per row: this line vs an average line. */
function DotCompare({
  question,
  line,
  network,
  color,
}: {
  question: string;
  line: number;
  network: number;
  color: string;
}) {
  const row = (filled: number, fill: string) =>
    Array.from({ length: 10 }, (_, i) => (
      <i key={i} style={i < filled ? { background: fill } : undefined} />
    ));
  return (
    <div className="dot-compare">
      <p>{question}, out of 10:</p>
      <div>
        <span>This line</span>
        <span className="dots">{row(inTen(line), color)}</span>
        <b>{inTen(line)} in 10</b>
      </div>
      <div>
        <span>Average line</span>
        <span className="dots">{row(inTen(network), "#9aa9ad")}</span>
        <b>{inTen(network)} in 10</b>
      </div>
    </div>
  );
}

/** Bunching rate at every stop along the route in the problem hours; ▲ = where bunching starts. */
function RouteStrip({ problem, base }: { problem: Problem; base: number }) {
  const stops = problem.profile;
  if (stops.length < 2) return null;
  const W = 600;
  const H = 110;
  const pad = { l: 4, r: 4, t: 8, b: 28 };
  const max = Math.max(...stops.map((s) => s.rate), base * 2);
  const maxOnsets = Math.max(1, ...stops.map((s) => s.onsets));
  const bw = (W - pad.l - pad.r) / stops.length;
  const y = (v: number) => pad.t + (1 - v / max) * (H - pad.t - pad.b);
  const worst = new Map(problem.stretch.map((s, i) => [s.stop_id, i + 1]));
  return (
    <figure className="route-strip">
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Bunching along the route"
      >
        <line
          x1={pad.l}
          x2={W - pad.r}
          y1={y(base)}
          y2={y(base)}
          className="route-strip-base"
        />
        {stops.map((s, i) => {
          const x = pad.l + i * bw;
          const rank = worst.get(s.stop_id);
          return (
            <g key={s.stop_id}>
              <title>
                {`${stopLabel(s)} · ${pct(s.rate, 1)} of visits bunched · ${plural(s.onsets, "start")} of bunching`}
              </title>
              <rect
                x={x + 0.5}
                y={y(s.rate)}
                width={Math.max(1, bw - 1)}
                height={H - pad.b - y(s.rate)}
                fill={heat(s.rate, base)}
                stroke={rank ? "#183741" : "none"}
              />
              {s.onsets > 0 && (
                <path
                  d={`M${x + bw / 2},${H - pad.b + 4} l4,7 h-8 z`}
                  fill="#183741"
                  opacity={0.25 + (0.75 * s.onsets) / maxOnsets}
                />
              )}
              {rank && (
                <text x={x + bw / 2} y={y(s.rate) - 2} textAnchor="middle">
                  {rank}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption>
        <span>
          {problem.terminal ? stopLabel(problem.terminal) : "First stop"}
        </span>
        <span>
          taller, redder bar = more bunching at that stop · ▲ = where it starts
        </span>
        <span>Last stop</span>
      </figcaption>
    </figure>
  );
}

function LineReason({
  problem,
  findings,
  onMap,
  onTest,
}: {
  problem: Problem;
  findings: Findings;
  onMap(): void;
  onTest(): void;
}) {
  const cause = CAUSES[problem.cause];
  const fix = fixOf(problem);
  const measure = measureOf(problem, findings);
  const t = problem.tested;
  return (
    <section className="board-card line-reason" aria-live="polite">
      <h3>
        <span>WHY THIS LINE</span> {problemTitle(problem)} · weekdays{" "}
        {problem.hours.join(", ")}
      </h3>
      <p className="reason-lead">
        {pct(problem.rate)} of stop visits are bunched here,{" "}
        <b>{problem.timesNetwork}× the average</b>, on every weekday of the
        week.
      </p>
      <div className="reason-grid">
        <div className="reason-block">
          <h4>The problem</h4>
          <p className="reason-cause">
            <b>{cause.problem}.</b>
          </p>
          {measure ? (
            <DotCompare
              question={measure.question}
              line={measure.line}
              network={measure.network}
              color={cause.color}
            />
          ) : (
            <p>{evidence(problem, findings)}</p>
          )}
        </div>
        <div className="reason-block">
          <h4>Where on the route</h4>
          <RouteStrip problem={problem} base={findings.headline.weekdayRate} />
          {problem.stretch.length > 0 && (
            <p className="reason-worst">
              Worst stops (numbered):{" "}
              {problem.stretch.map((stop) => stopLabel(stop)).join(", ")}
            </p>
          )}
        </div>
      </div>
      <div className="reason-fix" style={{ borderColor: cause.color }}>
        <h4>{fix.tested ? "Best fix (tested)" : "Suggested fix"}</h4>
        <p>
          <b>{fix.name}.</b> {fix.how}
        </p>
        <p className="reason-impact">
          {t ? (
            <>
              Of all the changes we simulated, this one cut waiting the most:
              passengers wait <b>{Math.round(t.ewtSaved)} s less</b> on average,{" "}
              {t.extraVehicles
                ? `with ${plural(t.extraVehicles, "extra bus")}.`
                : "with no extra bus."}
            </>
          ) : (
            "Suggested from the data; not simulated yet for these hours. Open it in the Simulation tab to see which change works best."
          )}
        </p>
        <div className="reason-actions">
          <button onClick={onMap}>Show on the map</button>
          <button className="finding-test" onClick={onTest}>
            Open in Simulation →
          </button>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Where bunching comes from: terminal vs on the road                  */
/* ------------------------------------------------------------------ */

function WhereFrom({ findings }: { findings: Findings }) {
  const dep = findings.departure;
  const tooSoon = dep
    .filter((d) => d.key === "too close" || d.key === "close")
    .reduce(
      (a, d) => ({
        trips: a.trips + d.tripShare,
        bunching: a.bunching + d.bunchingShare,
      }),
      { trips: 0, bunching: 0 },
    );
  const onPlan = dep.find((d) => d.key === "on plan");
  // the rest builds up on the road (trips that left on plan or late); shares add up to 100 %
  const road = Math.max(0, 1 - tooSoon.bunching);
  const riskSoon = dep[0]?.pBunch ?? 0;
  const riskPlan = onPlan?.pBunch ?? 0;
  return (
    <section className="board-card board-why">
      <h3>
        <span>WHERE IT COMES FROM</span> Two sources of bunching
      </h3>
      <div
        className="source-bar"
        role="img"
        aria-label="Share of all bunching by source"
      >
        <i className="soon" style={{ width: `${tooSoon.bunching * 100}%` }}>
          {pct(tooSoon.bunching)}
        </i>
        <i className="road" style={{ width: `${road * 100}%` }}>
          {pct(road)}
        </i>
      </div>
      <div className="source-grid">
        <div>
          <h4 className="soon">
            {pct(tooSoon.bunching)} starts at the terminal
          </h4>
          <p>
            Only {pct(tooSoon.trips)} of trips leave too close behind the bus in
            front, but they cause {pct(tooSoon.bunching)} of all bunching. A
            trip that leaves with less than half the planned gap bunches later
            in {pct(riskSoon)} of cases; a trip that leaves on plan in only{" "}
            {pct(riskPlan, 1)}.
          </p>
          <p className="board-note">
            Fix: at the terminal (wait for a proper gap, more break time).
          </p>
        </div>
        <div>
          <h4 className="road">{pct(road)} builds up on the road</h4>
          <p>
            Most trips ({pct(onPlan?.tripShare ?? 0)}) leave on plan. Each one
            has a small risk, but because there are so many they still add up to{" "}
            {pct(road)} of bunching: gaps close on the way (traffic, busy stops,
            a slow bus in front).
          </p>
          <p className="board-note">
            Fix: on the route (short holds mid-route, spread out the timetables
            of lines that share a street, see the areas below).
          </p>
        </div>
      </div>
    </section>
  );
}

function HotAreas({
  findings,
  onFocus,
  onClose,
}: {
  findings: Findings;
  onFocus(value: MapFocus): void;
  onClose(): void;
}) {
  const areas = findings.areas ?? [];
  const s = findings.areaSummary;
  if (!s) return null;
  return (
    <section className="board-card board-areas">
      <h3>
        <span>WHERE IN THE CITY</span> Is there one area where bunching
        concentrates?
      </h3>
      <p className="board-note area-answer">
        <b>Mostly no.</b> Bunching is spread across the city: the 10 busiest
        areas (of {s.cells}, about 500 m each) hold {pct(s.top10BunchingShare)}{" "}
        of bunching and {pct(s.top10VisitShare)} of bus stop visits, so they are
        busy, not special. It follows the lines and the terminals more than the
        place.
        {areas.length > 0 &&
          ` But ${areas.length === 1 ? "one area stands out" : `${areas.length} areas stand out`}: there, buses that left on time catch up with the bus in front much more often than the lines passing through would lead us to expect, on at least 4 of 5 weekdays.`}
      </p>
      {areas.length > 0 && (
        <ol className="area-list">
          {areas.map((a, index) => (
            <li key={`${a.lat}-${a.lon}`}>
              <button
                onClick={() => {
                  onFocus({ kind: "area", index });
                  onClose();
                }}
                title="Show on the map"
              >
                <b>
                  {index + 1}. Around{" "}
                  {a.stops[0] ? stopLabel(a.stops[0]) : "this area"}
                </b>
                <span>
                  <strong>{a.ratio}×</strong> more catch-ups than expected ·{" "}
                  {a.days}/5 weekdays · about {Math.round(a.onsetsPerWeekday)}{" "}
                  per weekday
                </span>
                <small>
                  {a.lines} lines pass here (most affected:{" "}
                  {a.topLines.slice(0, 4).join(", ")}) · worst{" "}
                  {a.peakHours.slice(0, 2).join(", ")}
                </small>
              </button>
            </li>
          ))}
        </ol>
      )}
      {areas.length > 0 && (
        <p className="board-note">
          Together these areas explain about {pct(s.hotAreaShareOfOnRoad)} of
          the bunching that builds up on the road. Worth a site visit: a traffic
          light, a busy junction or a stop where many passengers board may be
          slowing buses down here.
        </p>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Overlay: the one-page action plan for the operator                  */
/* ------------------------------------------------------------------ */

export function FindingsBoard({
  findings,
  onClose,
  onFocus,
  onTest,
}: {
  findings: Findings;
  onClose(): void;
  onFocus(value: MapFocus): void;
  onTest(problem: Problem): void;
}) {
  const [selected, setSelected] = useState(0);
  const h = findings.headline;
  const base = h.weekdayRate;
  const hours = range(6, 24);
  const moves = movesOf(findings);
  const problem = findings.problems[selected];
  const showOnMap = (index: number) => {
    onFocus({ kind: "problem", index });
    onClose();
  };
  return (
    <section
      className="bunching-overlay findings-board"
      aria-label="Action plan"
    >
      <header>
        <div>
          <span className="eyebrow">
            ACTION PLAN · {findings.source.operator} · {findings.source.from} –{" "}
            {findings.source.to}
          </span>
          <h2>
            Bunching is predictable: same lines, same stops, same hours, every
            weekday
          </h2>
          <p>
            {findings.source.definition} Weekday average: {pct(base, 1)} of stop
            visits.
          </p>
        </div>
        <button onClick={onClose}>Show map</button>
      </header>

      <div className="board-kpis">
        <div>
          <strong>{pct(h.topLinesBunchingShare)}</strong>
          <span>
            of all bunching happens on just 5 of {findings.source.lines} lines
          </span>
        </div>
        <div>
          <strong>{h.recurringBlocks}</strong>
          <span>
            problem slots: a line in a time window at 2× the average or more, on{" "}
            <b>all 5 weekdays</b>
          </span>
        </div>
        <div>
          <strong>{pct(findings.departure[0].pBunch)}</strong>
          <span>
            of trips that leave less than half the planned gap behind the bus in
            front bunch later (vs {pct(findings.departure[2].pBunch, 1)} when on
            plan)
          </span>
        </div>
        <div>
          <strong>
            {Math.round(h.corridorEventsPerWeekday).toLocaleString()}
          </strong>
          <span>times per weekday two different lines run together</span>
        </div>
      </div>

      <section className="board-card board-moves">
        <h3>
          <span>THE FIX</span> Four changes, all at the terminal or in the
          timetable
        </h3>
        <ol>
          {moves.dispatch.length > 0 && (
            <li>
              <b>Wait for a proper gap</b> on {moves.dispatch.join(", ")}: a bus
              leaves the terminal only when the bus in front is far enough
              ahead.
            </li>
          )}
          {moves.turnaround.length > 0 && (
            <li>
              <b>More break time at the terminal</b> (2–4 min) on{" "}
              {moves.turnaround.join(", ")} in the evening peak, so a late
              arrival does not delay the next trip.
            </li>
          )}
          {moves.road.length > 0 && (
            <li>
              <b>Short holds mid-route</b> on {moves.road.join(", ")} when the
              early warning says a bus is catching up (max 90 s).
            </li>
          )}
          <li>
            <b>Spread out the timetables</b> of lines that share a street (
            {findings.corridors
              .slice(0, 3)
              .map((c) => c.lines.join(" + "))
              .join(", ")}
            ) so their buses alternate.
          </li>
        </ol>
      </section>

      <section className="board-card board-when">
        <h3>
          <span>WHEN</span> Share of stop visits bunched, by hour and by day ·
          click a line to see why
        </h3>
        <div className="heat-scroll">
          <div className="heatmap">
            <span className="heat-corner">Line · starts at</span>
            <div className="heat-hours">
              {hours.map((hour) => (
                <span key={hour} className="heat-head">
                  {hour % 3 === 0 ? `${hour}h` : ""}
                </span>
              ))}
            </div>
            <div className="heat-days">
              {DAYS.map((d) => (
                <span key={d} className="heat-head">
                  {d.slice(0, 2)}
                </span>
              ))}
            </div>
            {findings.problems.map((p, index) => (
              <React.Fragment key={`${p.line}-${p.direction}-${p.block}`}>
                <button
                  className={`heat-label${index === selected ? " active" : ""}`}
                  onClick={() => setSelected(index)}
                  aria-pressed={index === selected}
                  title="Show why this line bunches"
                >
                  <b>{p.line}</b>
                  <span>
                    {p.terminal ? stopLabel(p.terminal) : `dir. ${p.direction}`}
                  </span>
                </button>
                <div
                  className={`heat-hours${index === selected ? " active" : ""}`}
                  onClick={() => setSelected(index)}
                >
                  {hours.map((hour) => {
                    const value = p.byHour[String(hour)];
                    return (
                      <span
                        key={hour}
                        className={`heat-cell${p.hotHours.includes(hour) ? " hot" : ""}`}
                        style={{ background: heat(value, base) }}
                        title={`Line ${p.line} · ${hour}:00–${hour + 1}:00 · ${pct(value, 1)} bunched`}
                      />
                    );
                  })}
                </div>
                <div
                  className={`heat-days${index === selected ? " active" : ""}`}
                  onClick={() => setSelected(index)}
                >
                  {DAYS.map((d) => (
                    <span
                      key={d}
                      className="heat-cell"
                      style={{ background: heat(p.byDay[d], base) }}
                      title={`Line ${p.line} · ${d}, ${p.block} · ${pct(p.byDay[d], 1)} bunched`}
                    />
                  ))}
                </div>
              </React.Fragment>
            ))}
          </div>
        </div>
        <div className="heat-legend">
          <span>average</span>
          <i style={{ background: heat(base, base) }} />
          <i style={{ background: heat(2 * base, base) }} />
          <i style={{ background: heat(4 * base, base) }} />
          <i style={{ background: heat(6 * base, base) }} />
          <span>6× or more</span>
          <em>
            Outlined = the problem hours (2× the average or more on at least 4
            of 5 weekdays). Right: each day of the week in the line's problem
            hours.
          </em>
        </div>
      </section>

      {problem && (
        <LineReason
          problem={problem}
          findings={findings}
          onMap={() => showOnMap(selected)}
          onTest={() => onTest(problem)}
        />
      )}

      <WhereFrom findings={findings} />
      <HotAreas findings={findings} onFocus={onFocus} onClose={onClose} />

      <section className="board-card">
        <h3>
          <span>WHAT TO CHANGE</span> One action per problem line, tested in the
          simulator where possible
        </h3>
        <div className="action-table-wrap">
          <table className="action-table">
            <colgroup>
              <col className="c-line" />
              <col className="c-where" />
              <col className="c-when" />
              <col className="c-why" />
              <col className="c-fix" />
              <col className="c-impact" />
              <col className="c-test" />
            </colgroup>
            <thead>
              <tr>
                <th>Line</th>
                <th>Where</th>
                <th>When (weekdays)</th>
                <th>Why</th>
                <th>Change</th>
                <th>Tested impact</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {findings.problems.map((p, index) => (
                <tr key={`${p.line}-${p.direction}-${p.block}`}>
                  <td>
                    <button
                      className="line-pill"
                      onClick={() => showOnMap(index)}
                      title="Show on the map"
                    >
                      {p.line}
                    </button>
                  </td>
                  <td>
                    <b>From {p.terminal ? stopLabel(p.terminal) : "–"}</b>
                    {p.stretch.length > 0 && (
                      <small>
                        worst: {p.stretch.map((s) => stopLabel(s)).join(", ")}
                      </small>
                    )}
                  </td>
                  <td>
                    <b>{p.hours.join(", ")}</b>
                    <small>
                      {pct(p.rate)} bunched · {p.timesNetwork}× the average
                    </small>
                  </td>
                  <td>
                    <CauseChip cause={p.cause} />
                  </td>
                  <td className="action-fix">
                    <b>{fixOf(p).name}</b>
                    <small>{fixOf(p).how}</small>
                  </td>
                  <td>
                    {p.tested ? (
                      <>
                        <b>−{Math.round(p.tested.ewtSaved)} s wait</b>
                        <small>
                          per passenger ({Math.round(p.tested.ewtSavedRange[0])}
                          –{Math.round(p.tested.ewtSavedRange[1])} s),{" "}
                          {p.tested.extraVehicles
                            ? `+${plural(p.tested.extraVehicles, "bus")}`
                            : "no extra bus"}
                        </small>
                      </>
                    ) : (
                      <small>not simulated yet</small>
                    )}
                  </td>
                  <td>
                    <button className="finding-test" onClick={() => onTest(p)}>
                      Simulate →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="board-note">
          Tested impact = held-out days (Fri 4 and Sun 6 Sep, 16–20 h), 30
          random seeds and both values of the dwell parameter. Extra wait = how
          much longer a passenger arriving at random waits than with evenly
          spaced buses. Not modelled: passenger loads, driver breaks.
        </p>
      </section>

      <section className="board-card">
        <h3>
          <span>BETWEEN LINES</span> Coordinate the timetables of lines that
          share a street
        </h3>
        <div className="action-table-wrap">
          <table className="action-table corridors">
            <thead>
              <tr>
                <th>Lines</th>
                <th>Shared stretch</th>
                <th>Run together</th>
                <th>Peak hours</th>
                <th>Planned &lt; 2 min apart</th>
              </tr>
            </thead>
            <tbody>
              {findings.corridors.slice(0, 6).map((c, index) => (
                <tr key={c.pair}>
                  <td>
                    <button
                      className="line-pill"
                      style={{ background: CORRIDOR_COLOR }}
                      onClick={() => {
                        onFocus({ kind: "corridor", index });
                        onClose();
                      }}
                      title="Show on the map"
                    >
                      {c.lines.join(" + ")}
                    </button>
                  </td>
                  <td>
                    <b>{c.sharedStops.length} stops</b>
                    <small>
                      {stopLabel(c.sharedStops[0])} →{" "}
                      {stopLabel(c.sharedStops[c.sharedStops.length - 1])}
                    </small>
                  </td>
                  <td>
                    <b>{Math.round(c.eventsPerWeekday)}× per weekday</b>
                    <small>{c.daysWithEvents}/5 weekdays</small>
                  </td>
                  <td>{c.peakHours.slice(0, 3).join(", ")}</td>
                  <td>{pct(c.plannedTogetherShare)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="board-note">
          Change: offset the two timetables on the shared stretch so the buses
          alternate. Start with the trips the timetable already plans less than
          2 min apart.
        </p>
      </section>
      <p className="board-note">
        Data: {findings.source.operator} GPS positions and operation plan,{" "}
        {findings.source.from} – {findings.source.to} (one week),{" "}
        {findings.source.lines} lines. Stops without a plan match show their id.
        {findings.stopNames === false &&
          " Stop names are unavailable because the database is not reachable."}
      </p>
    </section>
  );
}
