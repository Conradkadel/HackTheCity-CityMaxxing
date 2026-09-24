import pytest

from export_database import (
    CHALLENGE_PARENT_AREAS,
    CONFIGURED_LINES,
    build,
    vehicle_predicate,
)


def test_all_carris_predicate_keeps_context():
    predicate, params = vehicle_predicate("all-carris")
    assert predicate == "e.version_id=%s AND e.agency_id=%s"
    assert params == []


def test_configured_line_predicate_resolves_exact_trips():
    predicate, params = vehicle_predicate("configured-lines")
    assert "schedule_trips" in predicate
    assert "e.trip_id" in predicate
    assert "line_short_name=ANY" in predicate
    assert params == [CONFIGURED_LINES]


def test_challenge_area_predicate_uses_parent_cells():
    predicate, params = vehicle_predicate("challenge-areas")
    assert "e.geohash_5=ANY" in predicate
    assert params == [CHALLENGE_PARENT_AREAS]


def test_unknown_mode_is_rejected_by_builder_contract():
    with pytest.raises(ValueError, match="Unknown subset mode"):
        build("unused", "anything-else")
