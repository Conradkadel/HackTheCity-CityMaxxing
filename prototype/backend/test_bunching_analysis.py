from bunching_analysis import group_candidates


def candidate(stop, sequence, at, first_trip='trip-a', second_trip='trip-b'):
    return {
        'packageId': 8,
        'routeId': '118_0',
        'directionId': '0',
        'stopId': stop,
        'stopName': f'Stop {stop}',
        'stopSequence': sequence,
        'firstVehicleId': 'bus-a',
        'firstTripId': first_trip,
        'secondVehicleId': 'bus-b',
        'secondTripId': second_trip,
        'firstReportedTime': at,
        'secondReportedTime': at + 60_000,
        'firstScheduledTime': at - 600_000,
        'secondScheduledTime': at,
        'observedGapSeconds': 60,
        'plannedGapSeconds': 600,
        'latitude': 38.72,
        'longitude': -9.14,
    }


def test_repeated_stops_for_same_pair_become_one_multi_stop_episode():
    result = group_candidates([
        candidate('one', 1, 1_000_000),
        candidate('two', 2, 1_300_000),
    ])

    assert len(result) == 1
    assert result[0]['classification'] == 'multi_stop_candidate'
    assert result[0]['distinctStopCount'] == 2
    assert result[0]['evidenceCount'] == 2


def test_single_stop_is_kept_as_supporting_evidence_but_not_qualified():
    result = group_candidates([candidate('one', 1, 1_000_000)])

    assert result[0]['classification'] == 'single_point'


def test_large_time_gap_splits_same_pair_into_separate_episodes():
    result = group_candidates([
        candidate('one', 1, 1_000_000),
        candidate('two', 2, 1_000_000 + 1_201_000),
    ])

    assert len(result) == 2


def test_pair_identity_is_stable_when_report_order_switches():
    first = candidate('one', 1, 1_000_000)
    second = candidate('two', 2, 1_300_000)
    second['firstVehicleId'], second['secondVehicleId'] = (
        second['secondVehicleId'], second['firstVehicleId']
    )
    second['firstTripId'], second['secondTripId'] = (
        second['secondTripId'], second['firstTripId']
    )

    result = group_candidates([first, second])

    assert len(result) == 1
    assert result[0]['classification'] == 'multi_stop_candidate'

