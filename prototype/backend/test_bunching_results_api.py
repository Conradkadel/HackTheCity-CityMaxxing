from datetime import date

from bunching_results_api import completed_runs, monday_for, week_line_totals


class Result:
    def fetchall(self):
        return []


class Connection:
    def __init__(self):
        self.query = ''
        self.params = []

    def execute(self, query, params):
        self.query = query
        self.params = params
        return Result()


def test_unfiltered_summary_requires_complete_all_line_run():
    connection = Connection()

    completed_runs(connection, 4, date(2026, 9, 1), 'IA9T6')

    assert "scope='all_observed_lines'" in connection.query
    assert connection.params == [4, date(2026, 9, 1), 'stop-headway-v1', 'IA9T6']


def test_line_summary_can_use_latest_run_containing_that_line():
    connection = Connection()

    completed_runs(connection, 4, date(2026, 9, 1), 'IA9T6', line='755')

    assert '%s=ANY(selected_lines)' in connection.query
    assert connection.params[-1] == '755'


def test_week_containing_tuesday_starts_on_previous_monday():
    assert monday_for(date(2026, 9, 1)) == date(2026, 8, 31)


def test_week_totals_choose_one_latest_run_per_line_and_day():
    connection = Connection()

    week_line_totals(connection, 4, date(2026, 8, 31), 'IA9T6')

    assert 'unnest(r.selected_lines)' in connection.query
    assert 'DISTINCT ON (operational_date,operator_id,public_line)' in connection.query
    assert 'count(DISTINCT r.operational_date)' in connection.query
    assert "e.classification='multi_stop_candidate'" in connection.query
    assert connection.params == [
        4,
        date(2026, 8, 31),
        date(2026, 9, 6),
        'stop-headway-v1',
        'IA9T6',
    ]
