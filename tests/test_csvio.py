"""M1 CSV contract tests (K9): seven stable error codes, source line numbers on every
error, all errors reported at once, and missingness that stays missing.

The doc-drift gate at the top is deliberate: data/README.md 4.4 is the single written
definition of the code table, so the code and the table are asserted equal rather than
trusted to stay in step.
"""

import io
import os
import re

import pytest

from anomaly_atlas import csvio

from conftest import MINIMAL_CSV, SERIES_CSV, read_text, repo_path

_DOCUMENTED_CODES = {
    "E_EMPTY_FILE",
    "E_MISSING_COLUMN",
    "E_DUPLICATE_COLUMN",
    "E_TS_UNPARSEABLE",
    "E_VALUE_UNPARSEABLE",
    "E_DUPLICATE_TIMESTAMP",
    "E_NON_MONOTONIC",
}

_HEADER = "timestamp,series_id,value\n"


def _row(timestamp, series_id, value):
    return "%s,%s,%s\n" % (timestamp, series_id, value)


def _errors(path, spec=None):
    with pytest.raises(csvio.CsvContractError) as excinfo:
        csvio.load_series(path, spec)
    return excinfo.value


def _codes(errors):
    return sorted(error.code for error in errors.errors)


class TestErrorCodeTable:
    def test_codes_are_exactly_the_documented_seven(self):
        assert set(csvio.ERROR_CODES) == _DOCUMENTED_CODES
        assert len(csvio.ERROR_CODES) == 7
        for code, description in csvio.ERROR_CODES.items():
            assert description and isinstance(description, str)

    def test_readme_table_and_module_agree(self):
        # Doc/code drift gate: the written table in data/README.md 4.4 is the definition,
        # so it must list exactly the codes the module defines.
        text = read_text(repo_path("data", "README.md"))
        section = text.split("### 4.4", 1)[1].split("###", 1)[0]
        listed = set(re.findall(r"`(E_[A-Z_]+)`", section))
        assert listed == _DOCUMENTED_CODES, sorted(listed ^ _DOCUMENTED_CODES)

    def test_unknown_code_is_rejected_loudly(self):
        with pytest.raises(KeyError):
            csvio.InputError("E_NOT_A_REAL_CODE", detail="nope")

    def test_every_error_describes_a_location(self):
        error = csvio.InputError("E_TS_UNPARSEABLE", row_no=7, column="timestamp", detail="'x'")
        assert error.describe().startswith("row 7: E_TS_UNPARSEABLE")
        column_only = csvio.InputError("E_MISSING_COLUMN", column="timestamp", detail="missing")
        assert column_only.describe().startswith("column 'timestamp':")


class TestColumnResolution:
    def test_synonyms_are_matched_case_insensitively(self, write_text_file):
        path = write_text_file("Time,Val\n2024-02-29T00:00:00Z,1.5\n")
        parsed = csvio.load_series(path)
        assert parsed.columns == {"timestamp": "Time", "value": "Val", "series_id": None}
        assert parsed.rows_by_series["series"][0][2] == 1.5

    def test_header_whitespace_is_normalised(self, write_text_file):
        path = write_text_file("  timestamp , value \n2024-02-29T00:00:00Z,2\n")
        parsed = csvio.load_series(path)
        assert parsed.columns["timestamp"] == "timestamp"
        assert parsed.columns["value"] == "value"

    def test_explicit_spec_overrides_the_whitelist(self, write_text_file):
        path = write_text_file("when,reading,device\n2024-02-29T00:00:00Z,3,probe-a\n")
        parsed = csvio.load_series(
            path,
            {"timestamp_column": "when", "value_column": "reading", "series_id_column": "device"},
        )
        assert parsed.columns == {"timestamp": "when", "value": "reading", "series_id": "device"}
        assert list(parsed.rows_by_series) == ["probe-a"]

    def test_explicit_missing_column_names_the_column(self, write_text_file):
        path = write_text_file(_HEADER + _row("2024-02-29T00:00:00Z", "a", "1"))
        errors = _errors(path, {"timestamp_column": "when"})
        assert _codes(errors) == ["E_MISSING_COLUMN"]
        assert errors.errors[0].column == "when"

    def test_ambiguous_role_is_an_error_not_a_guess(self, write_text_file):
        path = write_text_file(
            "timestamp,time,value\n2024-02-29T00:00:00Z,2024-02-29T00:00:00Z,1\n"
        )
        errors = _errors(path)
        assert _codes(errors) == ["E_DUPLICATE_COLUMN"]
        assert "refusing to guess" in errors.errors[0].detail

    def test_duplicate_header_name_is_an_error(self, write_text_file):
        path = write_text_file("timestamp,value,value\n2024-02-29T00:00:00Z,1,2\n")
        errors = _errors(path)
        assert _codes(errors) == ["E_DUPLICATE_COLUMN"]
        assert errors.errors[0].row_no == 1

    def test_both_missing_roles_are_reported_together(self, write_text_file):
        path = write_text_file("alpha,beta\n1,2\n")
        errors = _errors(path)
        assert _codes(errors) == ["E_MISSING_COLUMN", "E_MISSING_COLUMN"]
        assert sorted(error.column for error in errors.errors) == ["timestamp", "value"]

    def test_absent_series_column_uses_the_declared_default_id(self, write_text_file):
        path = write_text_file("timestamp,value\n2024-02-29T00:00:00Z,1\n")
        parsed = csvio.load_series(path)
        assert parsed.columns["series_id"] is None
        assert list(parsed.rows_by_series) == ["series"]

    def test_empty_series_cell_falls_back_and_is_counted(self, write_text_file):
        path = write_text_file(_HEADER + _row("2024-02-29T00:00:00Z", "", "1"))
        parsed = csvio.load_series(path)
        assert list(parsed.rows_by_series) == ["series"]
        assert parsed.stats["n_missing_series_cells"] == 1


class TestFileShape:
    def test_empty_file(self, write_text_file):
        errors = _errors(write_text_file(""))
        assert _codes(errors) == ["E_EMPTY_FILE"]

    def test_header_only(self, write_text_file):
        errors = _errors(write_text_file(_HEADER))
        assert _codes(errors) == ["E_EMPTY_FILE"]
        assert errors.errors[0].row_no == 1

    def test_blank_lines_are_counted_not_rejected(self, write_text_file):
        path = write_text_file(_HEADER + _row("2024-02-29T00:00:00Z", "a", "1") + "\n")
        parsed = csvio.load_series(path)
        assert parsed.n_rows == 1
        assert parsed.stats["n_blank_rows"] == 1

    def test_ragged_rows_are_padded_and_counted(self, write_text_file):
        path = write_text_file(
            _HEADER
            + "2024-02-29T00:00:00Z,a\n"
            + _row("2024-02-29T00:05:00Z", "a", "2")
            + "2024-02-29T00:10:00Z,a,3,extra\n"
        )
        parsed = csvio.load_series(path)
        assert parsed.n_rows == 3
        assert parsed.stats["n_ragged_rows"] == 2
        assert parsed.rows_by_series["a"][0][2] is None, "a padded value cell must read as missing"

    def test_byte_order_mark_is_tolerated(self, write_text_file):
        path = write_text_file("\ufeff" + _HEADER + _row("2024-02-29T00:00:00Z", "a", "1"))
        parsed = csvio.load_series(path)
        assert parsed.columns["timestamp"] == "timestamp"
        assert parsed.stats["n_values_present"] == 1

    def test_row_numbers_are_physical_line_numbers(self, write_text_file):
        path = write_text_file(
            _HEADER
            + "\n"
            + _row("2024-02-29T00:00:00Z", "a", "1")
            + _row("2024-02-29T00:05:00Z", "a", "2")
        )
        parsed = csvio.load_series(path)
        assert [row[0] for row in parsed.rows_by_series["a"]] == [3, 4]
        assert parsed.stats["n_blank_rows"] == 1


class TestRowErrors:
    def test_unparseable_timestamp_carries_row_and_text(self, write_text_file):
        path = write_text_file(
            _HEADER + _row("not-a-time", "a", "1") + _row("2024-02-29T00:05:00Z", "a", "2")
        )
        errors = _errors(path)
        assert _codes(errors) == ["E_TS_UNPARSEABLE"]
        assert errors.errors[0].row_no == 2
        assert "not-a-time" in errors.errors[0].detail

    def test_unparseable_value_carries_row_and_text(self, write_text_file):
        path = write_text_file(_HEADER + _row("2024-02-29T00:00:00Z", "a", "twelve"))
        errors = _errors(path)
        assert _codes(errors) == ["E_VALUE_UNPARSEABLE"]
        assert errors.errors[0].row_no == 2
        assert "twelve" in errors.errors[0].detail

    def test_all_row_errors_are_reported_at_once_in_row_order(self, write_text_file):
        # The whole point of K9: never first-error-and-stop.
        path = write_text_file(
            _HEADER
            + _row("bad-one", "a", "1")
            + _row("2024-02-29T00:05:00Z", "a", "nope")
            + _row("bad-two", "a", "3")
            + _row("2024-02-29T00:15:00Z", "a", "also-bad")
        )
        errors = _errors(path)
        assert _codes(errors) == [
            "E_TS_UNPARSEABLE",
            "E_TS_UNPARSEABLE",
            "E_VALUE_UNPARSEABLE",
            "E_VALUE_UNPARSEABLE",
        ]
        assert [error.row_no for error in errors.errors] == [2, 3, 4, 5]

    def test_every_row_error_has_a_row_number(self, write_text_file):
        path = write_text_file(
            _HEADER + _row("bad", "a", "1") + _row("2024-02-29T00:05:00Z", "a", "bad")
        )
        for error in _errors(path).errors:
            assert error.row_no is not None

    @pytest.mark.parametrize("token", ["", " ", "NA", "na", "NaN", "nan", "null", "None", "-", "--"])
    def test_missing_markers_become_none(self, write_text_file, token):
        path = write_text_file(_HEADER + _row("2024-02-29T00:00:00Z", "a", token))
        parsed = csvio.load_series(path)
        assert parsed.rows_by_series["a"][0][2] is None
        assert parsed.stats["n_values_missing"] == 1

    @pytest.mark.parametrize("token", ["1_000", "0x10", "inf", "-inf", "1e999", "1,5", "12 34"])
    def test_non_finite_and_non_portable_numbers_are_rejected(self, write_text_file, token):
        path = write_text_file(_HEADER + _row("2024-02-29T00:00:00Z", "a", '"%s"' % token))
        errors = _errors(path)
        assert _codes(errors) == ["E_VALUE_UNPARSEABLE"]

    @pytest.mark.parametrize("token,expected", [("12.5", 12.5), ("-0.25", -0.25), (".5", 0.5), ("+3", 3.0), ("1e2", 100.0)])
    def test_portable_number_forms(self, write_text_file, token, expected):
        path = write_text_file(_HEADER + _row("2024-02-29T00:00:00Z", "a", token))
        assert csvio.load_series(path).rows_by_series["a"][0][2] == expected

    def test_undecodable_bytes_surface_as_a_row_level_error(self, write_bytes_file):
        # A replacement character must not be silently swallowed: it lands in a field and
        # is reported with the row number that produced it.
        payload = _HEADER.encode("utf-8") + b"2024-02-29T00:00:00Z,a,\xff\n"
        errors = _errors(write_bytes_file(payload))
        assert _codes(errors) == ["E_VALUE_UNPARSEABLE"]
        assert errors.errors[0].row_no == 2


class TestTimelineChecks:
    def test_duplicate_timestamp_beyond_the_tolerance(self, write_text_file):
        path = write_text_file(
            _HEADER
            + _row("2024-02-29T00:00:00Z", "a", "1")
            + _row("2024-02-29T00:00:00Z", "a", "2")
            + _row("2024-02-29T00:00:00Z", "a", "3")
        )
        errors = _errors(path)
        assert _codes(errors) == ["E_DUPLICATE_TIMESTAMP"]
        assert errors.errors[0].row_no == 4
        assert "row 2" in errors.errors[0].detail

    def test_one_duplicate_is_inside_the_default_tolerance(self, write_text_file):
        path = write_text_file(
            _HEADER + _row("2024-02-29T00:00:00Z", "a", "1") + _row("2024-02-29T00:00:00Z", "a", "2")
        )
        parsed = csvio.load_series(path)
        assert parsed.n_rows == 2

    def test_zero_tolerance_rejects_even_one_duplicate(self, write_text_file):
        path = write_text_file(
            _HEADER + _row("2024-02-29T00:00:00Z", "a", "1") + _row("2024-02-29T00:00:00Z", "a", "2")
        )
        assert _codes(_errors(path, {"duplicate_timestamp_max": 0})) == ["E_DUPLICATE_TIMESTAMP"]

    def test_duplicates_are_tracked_per_series(self, write_text_file):
        # The same instant in two different series is normal long-format data, not a
        # duplicate; only a repeat inside one series counts.
        path = write_text_file(
            _HEADER
            + _row("2024-02-29T00:00:00Z", "a", "1")
            + _row("2024-02-29T00:00:00Z", "b", "1")
        )
        assert csvio.load_series(path).stats["n_series"] == 2

    def test_non_monotonic_beyond_the_tolerance(self, write_text_file):
        path = write_text_file(
            _HEADER
            + _row("2024-02-29T00:10:00Z", "a", "1")
            + _row("2024-02-29T00:00:00Z", "a", "2")
        )
        errors = _errors(path)
        assert _codes(errors) == ["E_NON_MONOTONIC"]
        assert errors.errors[0].row_no == 3

    def test_non_monotonic_tolerance_is_honoured(self, write_text_file):
        path = write_text_file(
            _HEADER
            + _row("2024-02-29T00:10:00Z", "a", "1")
            + _row("2024-02-29T00:00:00Z", "a", "2")
        )
        parsed = csvio.load_series(path, {"non_monotonic_max": 1})
        stamps = [row[1] for row in parsed.rows_by_series["a"]]
        assert stamps[0] > stamps[1], "source order must be preserved, not silently sorted"


class TestSpecHandling:
    def test_defaults_are_complete_and_typed(self):
        resolved = csvio.resolve_spec()
        assert set(resolved) == set(csvio.DEFAULT_SPEC)
        for key in ("timezone_offset_min", "duplicate_timestamp_max", "non_monotonic_max"):
            assert isinstance(resolved[key], int)

    def test_unknown_key_is_rejected(self):
        with pytest.raises(KeyError):
            csvio.resolve_spec({"no_such_parameter": 1})

    def test_declared_timezone_applies_to_offset_less_rows(self, write_text_file):
        path = write_text_file(
            _HEADER
            + _row("2024-02-29T08:00:00", "a", "1")
            + _row("2024-02-29T08:00:00+08:00", "a", "1")
        )
        parsed = csvio.load_series(path, {"timezone_offset_min": 480, "duplicate_timestamp_max": 1})
        assert parsed.rows_by_series["a"][0][1] == parsed.rows_by_series["a"][1][1]
        assert parsed.offset_records == [(2, 480, False), (3, 480, True)]


class TestFrozenFixtures:
    def test_synthetic_series_loads_within_its_planted_tolerances(self):
        parsed = csvio.load_series(SERIES_CSV)
        assert parsed.columns == {
            "timestamp": "timestamp",
            "value": "value",
            "series_id": "series_id",
        }
        assert parsed.series_order == ["energy_kwh", "humidity", "temperature"]
        assert len(parsed.rows_by_series["temperature"]) == 988
        assert len(parsed.rows_by_series["humidity"]) == 987
        assert len(parsed.rows_by_series["energy_kwh"]) == 985
        assert parsed.n_rows == 2960
        assert parsed.stats["n_ragged_rows"] == 0
        assert parsed.stats["n_blank_rows"] == 0

    def test_the_planted_duplicate_is_tolerated_but_visible(self):
        parsed = csvio.load_series(SERIES_CSV)
        stamps = [row[1] for row in parsed.rows_by_series["temperature"]]
        repeated = [stamp for stamp in set(stamps) if stamps.count(stamp) > 1]
        assert len(repeated) == 1

    def test_zero_tolerance_would_reject_the_frozen_fixture(self):
        # Falsifiability: the tolerance parameter is consulted, not decorative.
        assert _codes(_errors(SERIES_CSV, {"duplicate_timestamp_max": 0})) == [
            "E_DUPLICATE_TIMESTAMP"
        ]

    def test_minimal_sample_loads_as_a_single_default_series(self):
        parsed = csvio.load_series(MINIMAL_CSV)
        assert list(parsed.rows_by_series) == ["series"]
        assert parsed.n_rows == 16
        assert parsed.stats["n_values_missing"] == 1

    def test_minimal_sample_is_small_enough_to_check_by_eye(self):
        lines = [line for line in read_text(MINIMAL_CSV).split("\n") if line]
        assert len(lines) <= 20
        assert os.path.basename(MINIMAL_CSV) == "minimal.csv"
