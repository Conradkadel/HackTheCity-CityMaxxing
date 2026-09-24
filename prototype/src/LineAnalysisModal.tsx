import React, { useEffect, useMemo, useState } from "react";

import { clock } from "./replay";
import {
  DiagramTrafficControl,
  DiagramTrafficRects,
} from "./DiagramTrafficControl";
import { trafficPlotCells, type DiagramTraffic } from "./diagramTraffic";
import { useDiagramTraffic } from "./useDiagramTraffic";
import type {
  BunchingCandidate,
  LineDay,
  LineRun,
  LineScheduledStop,
} from "./workspaceTypes";

const series = [
  "#21b5a1",
  "#7772ec",
  "#e9a522",
  "#e76869",
  "#46a9e1",
  "#d06db3",
  "#8ab35b",
];

const serviceMinute = (timestamp: number) => {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Lisbon",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(timestamp);
  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? 0);
  const minute = Number(
    parts.find((part) => part.type === "minute")?.value ?? 0,
  );
  return (hour < 4 ? hour + 24 : hour) * 60 + minute;
};

const inputMinute = (value: string) => {
  const [hour, minute] = value.split(":").map(Number);
  return (hour < 4 ? hour + 24 : hour) * 60 + minute;
};

const formatGap = (seconds: number) => {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.round(seconds / 60)} min`;
};

const runColor = (run: LineRun, vehicles: string[]) =>
  series[Math.max(0, vehicles.indexOf(run.vehicleId)) % series.length];

type Props = {
  target: { operatorId: string; line: string };
  analysis: LineDay | null;
  loading: boolean;
  error: string;
  workspaceStart: string;
  workspaceEnd: string;
  onClose(): void;
};

export function LineAnalysisModal({
  target,
  analysis,
  loading,
  error,
  workspaceStart,
  workspaceEnd,
  onClose,
}: Props) {
  const [direction, setDirection] = useState("");
  const [windowMode, setWindowMode] = useState<"workspace" | "day">(
    "workspace",
  );
  const [selectedRunKey, setSelectedRunKey] = useState<string | null>(null);
  const [showTraffic, setShowTraffic] = useState(false);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);

  const directions = useMemo(
    () =>
      analysis
        ? [...new Set(analysis.runs.map((run) => run.directionId))].sort()
        : [],
    [analysis],
  );
  const activeDirection = directions.includes(direction)
    ? direction
    : (directions[0] ?? "");
  const directionRuns = useMemo(() => {
    if (!analysis) return [];
    const candidates = analysis.runs.filter(
      (run) => run.directionId === activeDirection,
    );
    if (windowMode === "day") return candidates;
    const start = inputMinute(workspaceStart);
    let end = inputMinute(workspaceEnd);
    if (end <= start) end += 24 * 60;
    return candidates.filter((run) => {
      const first = serviceMinute(run.firstReport);
      let last = serviceMinute(run.lastReport);
      if (last < first) last += 24 * 60;
      return last >= start && first <= end;
    });
  }, [analysis, activeDirection, windowMode, workspaceStart, workspaceEnd]);
  const candidates = useMemo(() => {
    const visibleTrips = new Set(directionRuns.map((run) => run.tripId));
    return (
      analysis?.bunchingCandidates.filter(
        (candidate) =>
          candidate.directionId === activeDirection &&
          visibleTrips.has(candidate.firstTripId) &&
          visibleTrips.has(candidate.secondTripId),
      ) ?? []
    );
  }, [analysis, activeDirection, directionRuns]);
  const selectedRun = directionRuns.find(
    (run) => `${run.vehicleId}:${run.tripId}` === selectedRunKey,
  );
  const canonicalRun = [...directionRuns].sort(
    (a, b) => b.scheduledStops.length - a.scheduledStops.length,
  )[0];
  const traffic = useDiagramTraffic(
    showTraffic,
    analysis && canonicalRun
      ? {
          date: analysis.date,
          agency: target.operatorId,
          line: target.line,
          direction: activeDirection,
          package_id: canonicalRun.packageId,
          trip_id: canonicalRun.tripId,
        }
      : null,
  );

  return (
    <div className="line-modal-backdrop" role="presentation">
      <section
        className="line-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="line-analysis-title"
      >
        <header className="line-modal-header">
          <div>
            <span className="eyebrow">SERVICE-DAY COMPARISON</span>
            <h1 id="line-analysis-title">
              Line {target.line} <small>{analysis?.operatorName}</small>
            </h1>
            <p>
              Planned paths are dashed. Reported stop evidence is solid; lines
              converging at one stop indicate a possible headway collapse.
            </p>
          </div>
          <button className="line-modal-close" onClick={onClose}>
            Close
          </button>
        </header>

        {loading && (
          <div className="line-analysis-state">Loading line day…</div>
        )}
        {error && <div className="line-analysis-state error">{error}</div>}
        {analysis && !loading && (
          <>
            <div className="line-summary-bar">
              <strong>{analysis.date}</strong>
              <span>{analysis.coverage.vehicles} vehicles</span>
              <span>{analysis.coverage.runs} observed trips</span>
              <span>
                {analysis.coverage.reportedStops} matched stop reports
              </span>
              <span>{analysis.bunchingCandidates.length} candidates</span>
            </div>
            <div className="line-analysis-controls">
              <div className="direction-switch" aria-label="Direction">
                {directions.map((value) => (
                  <button
                    key={value}
                    className={activeDirection === value ? "active" : ""}
                    onClick={() => {
                      setDirection(value);
                      setSelectedRunKey(null);
                    }}
                  >
                    Direction {value || "unknown"}
                  </button>
                ))}
              </div>
              <label>
                Time range
                <select
                  value={windowMode}
                  onChange={(event) =>
                    setWindowMode(event.target.value as "workspace" | "day")
                  }
                >
                  <option value="workspace">
                    Current map window · {workspaceStart}–{workspaceEnd}
                  </option>
                  <option value="day">Whole service day</option>
                </select>
              </label>
            </div>

            {analysis.warnings.map((warning) => (
              <p className="coverage-warning line-warning" key={warning}>
                {warning}
              </p>
            ))}

            <DiagramTrafficControl
              enabled={showTraffic}
              onChange={setShowTraffic}
              traffic={traffic}
            />

            {directionRuns.length ? (
              <TimeSpaceChart
                runs={directionRuns}
                candidates={candidates}
                traffic={traffic.data}
                selectedRunKey={selectedRunKey}
                onSelectRun={setSelectedRunKey}
              />
            ) : (
              <div className="line-analysis-state">
                No observed trips overlap this direction and time range.
              </div>
            )}

            <div className="line-analysis-lower">
              <section className="line-run-detail">
                <h2>Selected vehicle trip</h2>
                {selectedRun ? (
                  <dl>
                    <dt>Vehicle</dt>
                    <dd>{selectedRun.vehicleId}</dd>
                    <dt>Trip</dt>
                    <dd>{selectedRun.tripId}</dd>
                    <dt>Route</dt>
                    <dd>{selectedRun.routeId}</dd>
                    <dt>Planned</dt>
                    <dd>
                      {selectedRun.scheduledStart
                        ? `${clock(selectedRun.scheduledStart)}–${clock(selectedRun.scheduledEnd!)}`
                        : "No scheduled-stop times"}
                    </dd>
                    <dt>Observed</dt>
                    <dd>
                      {clock(selectedRun.firstReport)}–
                      {clock(selectedRun.lastReport)} ·{" "}
                      {selectedRun.reportedStops}
                      stop reports
                    </dd>
                  </dl>
                ) : (
                  <p>
                    Select a solid vehicle path or stop marker in the chart.
                  </p>
                )}
              </section>
              <section className="candidate-list">
                <h2>Bunching candidates in view</h2>
                {candidates.length ? (
                  candidates.slice(0, 30).map((candidate) => (
                    <article
                      key={`${candidate.firstTripId}:${candidate.secondTripId}:${candidate.stopId}`}
                    >
                      <strong>{candidate.stopName}</strong>
                      <span>
                        Vehicles {candidate.firstVehicleId} and{" "}
                        {candidate.secondVehicleId}
                      </span>
                      <small>
                        reported {formatGap(candidate.observedGapSeconds)} apart
                        · planned {formatGap(candidate.plannedGapSeconds)} apart
                      </small>
                    </article>
                  ))
                ) : (
                  <p>No candidates meet the current evidence thresholds.</p>
                )}
              </section>
            </div>
            <footer className="line-evidence-note">
              <strong>Interpretation limit.</strong> {analysis.evidenceNote}
            </footer>
          </>
        )}
      </section>
    </div>
  );
}

function TimeSpaceChart({
  runs,
  candidates,
  selectedRunKey,
  onSelectRun,
  traffic,
}: {
  runs: LineRun[];
  candidates: BunchingCandidate[];
  selectedRunKey: string | null;
  onSelectRun(value: string): void;
  traffic: DiagramTraffic | null;
}) {
  const canonical = [...runs].sort(
    (a, b) => b.scheduledStops.length - a.scheduledStops.length,
  )[0]?.scheduledStops;
  const stops = canonical ?? [];
  const stopIndex = new Map(stops.map((stop, index) => [stop.stopId, index]));
  const vehicles = [...new Set(runs.map((run) => run.vehicleId))].sort();
  const timestamps = runs.flatMap((run) =>
    run.scheduledStops.flatMap((stop) =>
      [stop.scheduledTime, stop.reportedTime].filter(
        (value): value is number => value != null,
      ),
    ),
  );
  if (!stops.length || !timestamps.length)
    return (
      <div className="line-analysis-state">No scheduled stops to chart.</div>
    );

  const minimum = Math.min(...timestamps) - 5 * 60_000;
  const maximum = Math.max(...timestamps) + 5 * 60_000;
  const durationHours = Math.max(1, (maximum - minimum) / 3_600_000);
  const width = Math.max(1000, stops.length * 56);
  const height = Math.max(480, Math.min(1800, durationHours * 130));
  const margin = { top: 44, right: 35, bottom: 150, left: 74 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const x = (stop: LineScheduledStop) => {
    const index = stopIndex.get(stop.stopId);
    if (index == null) return null;
    return margin.left + (index / Math.max(1, stops.length - 1)) * innerWidth;
  };
  const y = (timestamp: number) =>
    margin.top + ((timestamp - minimum) / (maximum - minimum)) * innerHeight;
  const points = (run: LineRun, key: "scheduledTime" | "reportedTime") =>
    run.scheduledStops
      .map((stop) => {
        const px = x(stop);
        const stamp = stop[key];
        return px == null || stamp == null ? null : `${px},${y(stamp)}`;
      })
      .filter(Boolean)
      .join(" ");
  const tickCount = Math.max(2, Math.ceil(durationHours * 2));
  const ticks = Array.from(
    { length: tickCount + 1 },
    (_, index) => minimum + ((maximum - minimum) * index) / tickCount,
  );
  const trafficCells = trafficPlotCells(
    traffic,
    stops.map((s) => ({ id: s.stopId, sequence: s.stopSequence })),
    minimum,
    maximum,
  );

  return (
    <div className="time-space-wrap">
      <div className="chart-legend">
        <span className="legend-planned">planned</span>
        <span className="legend-observed">reported stop evidence</span>
        <span className="legend-candidate">candidate convergence</span>
        <em>{runs.length} trips in view</em>
      </div>
      <div className="time-space-scroll">
        <svg
          className="time-space-chart"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Time-space chart comparing planned and reported stops for each observed vehicle trip"
        >
          <DiagramTrafficRects
            cells={trafficCells}
            time={y}
            stop={(index) =>
              margin.left + (index / Math.max(1, stops.length - 1)) * innerWidth
            }
          />
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                className="chart-time-grid"
                x1={margin.left}
                x2={width - margin.right}
                y1={y(tick)}
                y2={y(tick)}
              />
              <text
                className="chart-time-label"
                x={margin.left - 10}
                y={y(tick) + 4}
                textAnchor="end"
              >
                {clock(tick)}
              </text>
            </g>
          ))}
          {stops.map((stop, index) => {
            const px = x(stop)!;
            return (
              <g key={`${stop.stopId}:${index}`}>
                <line
                  className="chart-stop-grid"
                  x1={px}
                  x2={px}
                  y1={margin.top}
                  y2={height - margin.bottom}
                />
                <text
                  className="chart-stop-label"
                  transform={`translate(${px + 4} ${height - margin.bottom + 12}) rotate(55)`}
                >
                  {stop.stopName}
                </text>
              </g>
            );
          })}
          {runs.map((run) => {
            const key = `${run.vehicleId}:${run.tripId}`;
            const color = runColor(run, vehicles);
            const planned = points(run, "scheduledTime");
            const reported = points(run, "reportedTime");
            return (
              <g key={key}>
                {planned && (
                  <polyline
                    className="run-planned"
                    points={planned}
                    style={{ stroke: color }}
                  />
                )}
                {reported && (
                  <polyline
                    className={`run-observed ${selectedRunKey === key ? "selected" : ""}`}
                    points={reported}
                    style={{ stroke: color }}
                    onClick={() => onSelectRun(key)}
                  >
                    <title>
                      Vehicle {run.vehicleId} · trip {run.tripId} ·{" "}
                      {run.reportedStops}
                      reported stops
                    </title>
                  </polyline>
                )}
                {run.scheduledStops
                  .filter(
                    (stop) => stop.reportedTime != null && x(stop) != null,
                  )
                  .map((stop) => (
                    <circle
                      key={`${key}:${stop.stopSequence}`}
                      className="run-stop"
                      cx={x(stop)!}
                      cy={y(stop.reportedTime!)}
                      r={selectedRunKey === key ? 4 : 2.7}
                      style={{ fill: color }}
                      onClick={() => onSelectRun(key)}
                    >
                      <title>
                        Vehicle {run.vehicleId} · {stop.stopName} · reported{" "}
                        {clock(stop.reportedTime!)} · planned{" "}
                        {stop.scheduledTime == null
                          ? "unavailable"
                          : clock(stop.scheduledTime)}
                      </title>
                    </circle>
                  ))}
              </g>
            );
          })}
          {candidates.map((candidate) => {
            const index = stopIndex.get(candidate.stopId);
            if (index == null) return null;
            const px =
              margin.left +
              (index / Math.max(1, stops.length - 1)) * innerWidth;
            const stamp =
              (candidate.firstReportedTime + candidate.secondReportedTime) / 2;
            return (
              <circle
                key={`${candidate.firstTripId}:${candidate.secondTripId}:${candidate.stopId}`}
                className="bunching-mark"
                cx={px}
                cy={y(stamp)}
                r={8}
              >
                <title>
                  Candidate at {candidate.stopName}: reported{" "}
                  {formatGap(candidate.observedGapSeconds)} apart, planned{" "}
                  {formatGap(candidate.plannedGapSeconds)} apart
                </title>
              </circle>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
