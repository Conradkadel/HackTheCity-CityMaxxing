import type { useDiagramTraffic } from "./useDiagramTraffic";
import type { TrafficPlotCell } from "./diagramTraffic";

export function DiagramTrafficControl({
  enabled,
  onChange,
  traffic,
}: {
  enabled: boolean;
  onChange(value: boolean): void;
  traffic: ReturnType<typeof useDiagramTraffic>;
}) {
  const { data, loading, error, retry } = traffic;
  return (
    <div className="diagram-traffic-control">
      <label>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        Typical traffic by time of day
      </label>
      {enabled && (
        <>
          <div className="diagram-traffic-legend">
            <span>
              <i style={{ background: "#ea580c" }} />
              Heavy
            </span>
            <span>
              <i style={{ background: "#b91c1c" }} />
              Very heavy
            </span>
            <span>30-minute bands · Lisbon time</span>
          </div>
          <div role="status">
            {loading ? (
              "Loading traffic history…"
            ) : error ? (
              <>
                {error} <button onClick={retry}>Retry</button>
              </>
            ) : (
              data &&
              (data.period.days
                ? `${data.period.start} – ${data.period.end} · ${data.period.days} imported days · average across days with reports`
                : "No Waze reports imported.")
            )}
          </div>
          {data && !data.sections.some((s) => s.cells.length) && (
            <p>No matching traffic evidence for this route.</p>
          )}
          {!!data?.ignoredReports && (
            <p>{data.ignoredReports} reports could not be interpreted.</p>
          )}
          <p>
            Hover the background for evidence. Unshaded areas may lack data;
            pale shading can reflect sparse coverage. Compare with later
            bunching markers—this does not establish a cause.
          </p>
        </>
      )}
    </div>
  );
}

export function DiagramTrafficRects({
  cells,
  time,
  stop,
  horizontalTime = false,
}: {
  cells: TrafficPlotCell[];
  time(value: number): number;
  stop(index: number): number;
  horizontalTime?: boolean;
}) {
  return (
    <g className="diagram-traffic-background">
      {cells.map((cell) => {
        const a = stop(cell.index),
          b = stop(cell.index + 1);
        return (
          <rect
            key={`${cell.index}:${cell.start}`}
            x={horizontalTime ? time(cell.start) : Math.min(a, b)}
            y={horizontalTime ? Math.min(a, b) : time(cell.start)}
            width={
              horizontalTime
                ? time(cell.end) - time(cell.start)
                : Math.abs(b - a)
            }
            height={
              horizontalTime
                ? Math.abs(b - a)
                : time(cell.end) - time(cell.start)
            }
            fill={cell.color}
            fillOpacity={cell.opacity}
          >
            <title>{cell.description}</title>
          </rect>
        );
      })}
    </g>
  );
}
