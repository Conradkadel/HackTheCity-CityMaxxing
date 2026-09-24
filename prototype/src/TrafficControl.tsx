import { trafficBands, unknownTraffic } from "./traffic";
import type { useRouteTraffic } from "./useRouteTraffic";

export function TrafficControl({
  enabled,
  onChange,
  selectedCount,
  traffic,
}: {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  selectedCount: number;
  traffic: ReturnType<typeof useRouteTraffic>;
}) {
  const { data, loading, error, retry } = traffic;
  const matched =
    data?.routes.reduce((sum, route) => sum + route.matchedMeters, 0) ?? 0;
  const total =
    data?.routes.reduce((sum, route) => sum + route.totalMeters, 0) ?? 0;
  return (
    <section className="traffic-control" aria-label="Route traffic filter">
      <label>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        Typical traffic
      </label>
      {enabled && (
        <div className="traffic-details">
          <div
            className="traffic-legend"
            aria-label="Reported congestion colours"
          >
            {[...trafficBands].reverse().map((band) => (
              <span key={band.label}>
                <i style={{ background: band.color }} />
                {band.label}
              </span>
            ))}
            <span>
              <i style={{ background: unknownTraffic.color }} />
              No data
            </span>
          </div>
          <div role="status" aria-live="polite">
            {!selectedCount ? (
              <p>Select routes in the Routes tab to colour their sections.</p>
            ) : loading ? (
              <p>Matching Waze reports to routes…</p>
            ) : error ? (
              <p>
                {error} <button onClick={retry}>Retry</button>
              </p>
            ) : (
              data && (
                <>
                  <p>
                    {data.period.days
                      ? `${data.period.start} – ${data.period.end} · ${data.period.days} days · all hours`
                      : "No Waze reports imported yet."}
                  </p>
                  {!!data.period.days && (
                    <p>
                      {total ? Math.round((matched / total) * 100) : 0}% of
                      selected route geometry has matched reports.
                    </p>
                  )}
                  {!!data.ignoredReports && (
                    <p>
                      {data.ignoredReports.toLocaleString()} reports could not
                      be interpreted.
                    </p>
                  )}
                </>
              )
            )}
          </div>
          <p className="traffic-note">
            Average congestion on days with reports, across all imported dates.
            Grey means unknown, not clear traffic. Hover a section for evidence.
          </p>
        </div>
      )}
    </section>
  );
}
