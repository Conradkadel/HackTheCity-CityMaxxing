"""Pure grouping logic for versioned, precomputed bunching candidates."""

from collections import defaultdict


DETECTOR_VERSION = 'stop-headway-v1'
DEFAULT_PARAMETERS = {
    'maximumObservedGapSeconds': 180,
    'minimumPlannedGapSeconds': 300,
    'maximumEvidenceGapSeconds': 1200,
    'minimumDistinctStops': 2,
    'usesPositionInterpolation': False,
}


def _pair(candidate):
    members = sorted((
        (candidate['firstTripId'], candidate['firstVehicleId']),
        (candidate['secondTripId'], candidate['secondVehicleId']),
    ))
    return tuple(members)


def group_candidates(candidates, maximum_evidence_gap_seconds=1200,
                     minimum_distinct_stops=2):
    """Collapse repeated stop detections for a vehicle-trip pair into episodes."""
    grouped = defaultdict(list)
    for candidate in candidates:
        grouped[(
            candidate['routeId'],
            candidate['directionId'],
            _pair(candidate),
        )].append(candidate)

    episodes = []
    maximum_gap_ms = maximum_evidence_gap_seconds * 1000
    for (route_id, direction_id, members), rows in grouped.items():
        rows.sort(key=lambda item: item['firstReportedTime'])
        chunks = []
        current = []
        for row in rows:
            if current and row['firstReportedTime'] - current[-1]['firstReportedTime'] > maximum_gap_ms:
                chunks.append(current)
                current = []
            current.append(row)
        if current:
            chunks.append(current)

        for evidence in chunks:
            distinct_stops = len({item['stopId'] for item in evidence})
            coordinates = [
                (item.get('latitude'), item.get('longitude'))
                for item in evidence
                if item.get('latitude') is not None and item.get('longitude') is not None
            ]
            episodes.append({
                'routeId': route_id,
                'directionId': direction_id,
                'tripAId': members[0][0],
                'vehicleAId': members[0][1],
                'tripBId': members[1][0],
                'vehicleBId': members[1][1],
                'startedAt': min(item['firstReportedTime'] for item in evidence),
                'endedAt': max(item['secondReportedTime'] for item in evidence),
                'firstStopId': evidence[0]['stopId'],
                'firstStopName': evidence[0]['stopName'],
                'lastStopId': evidence[-1]['stopId'],
                'lastStopName': evidence[-1]['stopName'],
                'evidenceCount': len(evidence),
                'distinctStopCount': distinct_stops,
                'minimumObservedGapSeconds': min(item['observedGapSeconds'] for item in evidence),
                'maximumPlannedGapSeconds': max(item['plannedGapSeconds'] for item in evidence),
                'classification': (
                    'multi_stop_candidate'
                    if distinct_stops >= minimum_distinct_stops
                    else 'single_point'
                ),
                'latitude': (
                    sum(item[0] for item in coordinates) / len(coordinates)
                    if coordinates else None
                ),
                'longitude': (
                    sum(item[1] for item in coordinates) / len(coordinates)
                    if coordinates else None
                ),
                'evidence': evidence,
            })
    return sorted(episodes, key=lambda item: (item['startedAt'], item['routeId']))

