"""Read-only API for versioned precomputed bunching analysis."""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from bunching_analysis import DETECTOR_VERSION
from db import active_version, connect


router = APIRouter(prefix='/api/bunching')


def milliseconds(value):
    return int(value.timestamp() * 1000)


def monday_for(value):
    return value - timedelta(days=value.weekday())


def week_line_totals(conn, version, week_start, operator_id=None,
                     detector_version=DETECTOR_VERSION):
    operator_clause = 'AND r.operator_id=%s' if operator_id else ''
    params = [version, week_start, week_start + timedelta(days=6),
              detector_version]
    if operator_id:
        params.append(operator_id)
    return conn.execute(f'''WITH expanded_runs AS (
      SELECT r.id,r.operational_date,r.operator_id,r.completed_at,
        unnest(r.selected_lines) AS public_line
      FROM analysis_runs r
      WHERE r.dataset_version=%s
        AND r.operational_date BETWEEN %s AND %s
        AND r.detector_version=%s AND r.status='completed' {operator_clause}
    ), latest_runs AS (
      SELECT DISTINCT ON (operational_date,operator_id,public_line)
        id,operational_date,operator_id,public_line
      FROM expanded_runs
      ORDER BY operational_date,operator_id,public_line,completed_at DESC,id DESC
    )
    SELECT r.operator_id,r.public_line,
      count(DISTINCT r.operational_date)::integer AS analyzed_days,
      count(e.id) FILTER (
        WHERE e.classification='multi_stop_candidate'
      )::integer AS candidate_episodes,
      coalesce(sum(e.evidence_count) FILTER (
        WHERE e.classification='multi_stop_candidate'
      ),0)::bigint AS evidence_points
    FROM latest_runs r
    LEFT JOIN bunching_episodes e ON e.analysis_run_id=r.id
      AND e.public_line=r.public_line
    GROUP BY r.operator_id,r.public_line
    ORDER BY candidate_episodes DESC,r.operator_id,r.public_line''', params).fetchall()


def completed_runs(conn, version, day, operator_id=None,
                   detector_version=DETECTOR_VERSION, line=None):
    operator_clause = 'AND operator_id=%s' if operator_id else ''
    params = [version, day, detector_version]
    if operator_id:
        params.append(operator_id)
    if line:
        scope_clause = 'AND %s=ANY(selected_lines)'
        params.append(line)
    else:
        scope_clause = "AND scope='all_observed_lines'"
    return conn.execute(f'''SELECT DISTINCT ON (operator_id)
      id,dataset_version,operational_date,operator_id,detector_version,scope,
      selected_lines,parameters,started_at,completed_at,counts
      FROM analysis_runs WHERE dataset_version=%s AND operational_date=%s
        AND detector_version=%s AND status='completed' {operator_clause} {scope_clause}
      ORDER BY operator_id,completed_at DESC,id DESC''', params).fetchall()


@router.get('/summary')
def bunching_summary(date_value: date = Query(..., alias='date'),
                     operator: Optional[str] = None,
                     line: Optional[str] = None,
                     detector_version: str = DETECTOR_VERSION):
    with connect() as conn:
        version = active_version(conn)
        if version is None:
            raise HTTPException(503, 'No completed vehicle dataset is available.')
        runs = completed_runs(
            conn, version, date_value, operator, detector_version, line
        )
        run_ids = [row['id'] for row in runs]
        rows = []
        if run_ids:
            line_clause = 'AND public_line=%s' if line else ''
            params = [run_ids]
            if line:
                params.append(line)
            rows = conn.execute(f'''SELECT operator_id,public_line,
              count(*) FILTER (WHERE classification='multi_stop_candidate') AS candidate_episodes,
              count(*) FILTER (WHERE classification='single_point') AS single_point_episodes,
              count(*) AS all_episodes,sum(evidence_count)::bigint AS evidence_points,
              min(minimum_observed_gap_seconds) AS minimum_observed_gap_seconds,
              max(maximum_planned_gap_seconds) AS maximum_planned_gap_seconds
              FROM bunching_episodes WHERE analysis_run_id=ANY(%s) {line_clause}
              GROUP BY operator_id,public_line ORDER BY operator_id,public_line''', params).fetchall()
    return {
        'date': date_value.isoformat(),
        'datasetVersion': version,
        'detectorVersion': detector_version,
        'runs': runs,
        'lines': rows,
        'totals': {
            'candidateEpisodes': sum(row['candidate_episodes'] for row in rows),
            'singlePointEpisodes': sum(row['single_point_episodes'] for row in rows),
            'evidencePoints': sum(row['evidence_points'] or 0 for row in rows),
        },
        'warning': (
            'No completed pre-analysis exists for this selection. Run analyze_bunching.py.'
            if not runs else None
        ),
    }


@router.get('/episodes')
def bunching_episodes(date_value: date = Query(..., alias='date'),
                      operator: str = Query(...),
                      line: Optional[str] = None,
                      include_single_point: bool = False,
                      detector_version: str = DETECTOR_VERSION,
                      limit: int = Query(1000, ge=1, le=5000)):
    with connect() as conn:
        version = active_version(conn)
        if version is None:
            raise HTTPException(503, 'No completed vehicle dataset is available.')
        runs = completed_runs(
            conn, version, date_value, operator, detector_version, line
        )
        if not runs:
            return {'date': date_value.isoformat(), 'operatorId': operator,
                    'detectorVersion': detector_version, 'episodes': [],
                    'warning': 'No completed pre-analysis exists for this selection.'}
        clauses = ['analysis_run_id=%s']
        params = [runs[0]['id']]
        if line:
            clauses.append('public_line=%s')
            params.append(line)
        if not include_single_point:
            clauses.append("classification='multi_stop_candidate'")
        params.append(limit)
        episodes = conn.execute(f'''SELECT id,operator_id,public_line,package_id,
          route_id,direction_id,vehicle_a_id,trip_a_id,vehicle_b_id,trip_b_id,
          started_at,ended_at,first_stop_id,first_stop_name,last_stop_id,last_stop_name,
          evidence_count,distinct_stop_count,minimum_observed_gap_seconds,
          maximum_planned_gap_seconds,classification,latitude,longitude
          FROM bunching_episodes WHERE {' AND '.join(clauses)}
          ORDER BY started_at,id LIMIT %s''', params).fetchall()
    return {'date': date_value.isoformat(), 'operatorId': operator,
            'detectorVersion': detector_version, 'run': runs[0],
            'episodes': episodes}


@router.get('/week')
def bunching_week(date_value: date = Query(..., alias='date'),
                  operator: str = Query(...), line: str = Query(...),
                  detector_version: str = DETECTOR_VERSION):
    week_start = monday_for(date_value)
    days = []
    with connect() as conn:
        version = active_version(conn)
        if version is None:
            raise HTTPException(503, 'No completed vehicle dataset is available.')
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            runs = completed_runs(
                conn, version, day, operator, detector_version, line
            )
            episodes = []
            if runs:
                rows = conn.execute('''SELECT id,route_id,direction_id,
                  vehicle_a_id,trip_a_id,vehicle_b_id,trip_b_id,started_at,ended_at,
                  first_stop_id,first_stop_name,last_stop_id,last_stop_name,
                  evidence_count,distinct_stop_count,minimum_observed_gap_seconds,
                  maximum_planned_gap_seconds,latitude,longitude
                  FROM bunching_episodes WHERE analysis_run_id=%s
                    AND public_line=%s AND classification='multi_stop_candidate'
                  ORDER BY started_at,id''', (runs[0]['id'], line)).fetchall()
                episodes = [{
                    'id': row['id'],
                    'routeId': row['route_id'],
                    'directionId': row['direction_id'],
                    'vehicleAId': row['vehicle_a_id'],
                    'tripAId': row['trip_a_id'],
                    'vehicleBId': row['vehicle_b_id'],
                    'tripBId': row['trip_b_id'],
                    'startTimestamp': milliseconds(row['started_at']),
                    'endTimestamp': milliseconds(row['ended_at']),
                    'firstStopId': row['first_stop_id'],
                    'firstStopName': row['first_stop_name'],
                    'lastStopId': row['last_stop_id'],
                    'lastStopName': row['last_stop_name'],
                    'evidenceCount': row['evidence_count'],
                    'distinctStopCount': row['distinct_stop_count'],
                    'minimumObservedGapSeconds': row['minimum_observed_gap_seconds'],
                    'maximumPlannedGapSeconds': row['maximum_planned_gap_seconds'],
                    'latitude': row['latitude'],
                    'longitude': row['longitude'],
                } for row in rows]
            days.append({
                'date': day.isoformat(),
                'analysisAvailable': bool(runs),
                'analysisRunId': runs[0]['id'] if runs else None,
                'episodes': episodes,
            })
    return {
        'datasetVersion': version,
        'detectorVersion': detector_version,
        'operatorId': operator,
        'line': line,
        'weekStart': week_start.isoformat(),
        'weekEnd': (week_start + timedelta(days=6)).isoformat(),
        'analyzedDays': sum(day['analysisAvailable'] for day in days),
        'totalEpisodes': sum(len(day['episodes']) for day in days),
        'days': days,
        'evidenceNote': (
            'Times are precomputed multi-stop candidate evidence, not confirmed '
            'door-open arrivals or confirmed operational incidents.'
        ),
    }


@router.get('/week-summary')
def bunching_week_summary(date_value: date = Query(..., alias='date'),
                          operator: Optional[str] = None,
                          detector_version: str = DETECTOR_VERSION):
    week_start = monday_for(date_value)
    with connect() as conn:
        version = active_version(conn)
        if version is None:
            raise HTTPException(503, 'No completed vehicle dataset is available.')
        rows = week_line_totals(
            conn, version, week_start, operator, detector_version
        )
    return {
        'datasetVersion': version,
        'detectorVersion': detector_version,
        'weekStart': week_start.isoformat(),
        'weekEnd': (week_start + timedelta(days=6)).isoformat(),
        'lines': [{
            'operatorId': row['operator_id'],
            'line': row['public_line'],
            'analyzedDays': row['analyzed_days'],
            'candidateEpisodes': row['candidate_episodes'],
            'evidencePoints': row['evidence_points'],
        } for row in rows],
        'evidenceNote': (
            'Counts are multi-stop investigation candidates, not confirmed '
            'incidents. Raw totals are not normalized for service frequency.'
        ),
    }


@router.get('/episodes/{episode_id}/evidence')
def bunching_episode_evidence(episode_id: int):
    with connect() as conn:
        version = active_version(conn)
        row = conn.execute('''SELECT e.* FROM bunching_episodes e
          JOIN analysis_runs r ON r.id=e.analysis_run_id
          WHERE e.id=%s AND r.dataset_version=%s AND r.status='completed' ''',
          (episode_id, version)).fetchone()
        if not row:
            raise HTTPException(404, 'Bunching episode not found in the active dataset.')
        evidence = conn.execute('''SELECT * FROM bunching_evidence
          WHERE episode_id=%s ORDER BY evidence_sequence''', (episode_id,)).fetchall()
    return {'episode': row, 'evidence': evidence}
