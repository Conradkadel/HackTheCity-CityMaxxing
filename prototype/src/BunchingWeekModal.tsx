import { useEffect } from "react";

import { clock } from "./replay";
import type { BunchingWeek } from "./workspaceTypes";

const dayLabel = (value: string) =>
  new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Lisbon",
    weekday: "long",
    day: "2-digit",
    month: "short",
  }).format(new Date(`${value}T12:00:00Z`));

const gap = (seconds: number) =>
  seconds < 60 ? `${seconds}s` : `${Math.round(seconds / 60)} min`;

type Props = {
  target: { operatorId: string; line: string };
  week: BunchingWeek | null;
  loading: boolean;
  error: string;
  onClose(): void;
};

export function BunchingWeekModal({
  target,
  week,
  loading,
  error,
  onClose,
}: Props) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);

  return (
    <div className="line-modal-backdrop" role="presentation">
      <section
        className="line-modal week-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="week-analysis-title"
      >
        <header className="line-modal-header">
          <div>
            <span className="eyebrow">PRECOMPUTED WEEKLY HISTORY</span>
            <h1 id="week-analysis-title">Line {target.line}</h1>
            <p>
              Consolidated multi-stop candidate episodes. A day with no analysis
              is different from an analyzed day with zero candidates.
            </p>
          </div>
          <button className="line-modal-close" onClick={onClose}>
            Close
          </button>
        </header>

        {loading && (
          <div className="line-analysis-state">Loading weekly history…</div>
        )}
        {error && <div className="line-analysis-state error">{error}</div>}
        {week && !loading && (
          <>
            <div className="line-summary-bar">
              <strong>
                {week.weekStart}–{week.weekEnd}
              </strong>
              <span>{week.analyzedDays}/7 days analyzed</span>
              <span>{week.totalEpisodes} multi-stop candidates</span>
              <span>{week.detectorVersion}</span>
            </div>
            <div className="week-days">
              {week.days.map((day) => (
                <section
                  className={`week-day ${day.analysisAvailable ? "analyzed" : "missing"}`}
                  key={day.date}
                >
                  <header>
                    <div>
                      <strong>{dayLabel(day.date)}</strong>
                      <small>{day.date}</small>
                    </div>
                    <span>
                      {day.analysisAvailable
                        ? `${day.episodes.length} ${day.episodes.length === 1 ? "episode" : "episodes"}`
                        : "Not analyzed"}
                    </span>
                  </header>
                  {!day.analysisAvailable ? (
                    <p className="week-empty">
                      Run the batch analyzer for this date to distinguish no
                      bunching from missing analysis.
                    </p>
                  ) : day.episodes.length ? (
                    <div className="week-episodes">
                      {day.episodes.map((episode) => (
                        <article key={episode.id}>
                          <div className="week-episode-time">
                            <strong>
                              {clock(episode.startTimestamp)}–
                              {clock(episode.endTimestamp)}
                            </strong>
                            <span>
                              Direction {episode.directionId || "unknown"}
                            </span>
                          </div>
                          <div className="week-episode-route">
                            <span>
                              Vehicles {episode.vehicleAId} +{" "}
                              {episode.vehicleBId}
                            </span>
                            <small>
                              {episode.firstStopName}
                              {episode.firstStopId !== episode.lastStopId
                                ? ` → ${episode.lastStopName}`
                                : ""}
                            </small>
                          </div>
                          <div className="week-episode-metrics">
                            <span>{episode.distinctStopCount} stops</span>
                            <span>
                              closest report gap{" "}
                              {gap(episode.minimumObservedGapSeconds)}
                            </span>
                            <span>
                              planned separation up to{" "}
                              {gap(episode.maximumPlannedGapSeconds)}
                            </span>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="week-empty analyzed-empty">
                      Analysis completed: no multi-stop candidates found.
                    </p>
                  )}
                </section>
              ))}
            </div>
            <footer className="line-evidence-note">
              <strong>Interpretation limit.</strong> {week.evidenceNote}
            </footer>
          </>
        )}
      </section>
    </div>
  );
}
