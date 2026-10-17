"""M1 profile tests: byte-identical double runs, canonical-JSON form, no hidden defaults,
and a cross-check of every interval the profile reports against the planted truth.

The cross-check is the part that matters: a profile that merely "looks plausible" while
listing the wrong gaps would pass a shape-only test suite.
"""

import csv
import io
import json
import os
import re

import pytest

from anomaly_atlas import canon, cli, csvio, profile

from conftest import (
    MINIMAL_CSV,
    SERIES_CSV,
    TRUTH_JSON,
    iter_floats,
    read_bytes,
    read_text,
)

_FORBIDDEN_CLOCK_KEYS = {
    "generated",
    "generated_at",
    "created",
    "created_at",
    "built_at",
    "build_time",
    "run_time",
    "now",
}
_ISO_STRING_RE = re.compile(r"\d{4}-\d{2}-\d{2}T")


def _all_keys(obj, found=None):
    if found is None:
        found = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.add(key)
            _all_keys(value, found)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _all_keys(value, found)
    return found


def _all_strings(obj, found=None):
    if found is None:
        found = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            found.append(key)
            _all_strings(value, found)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _all_strings(value, found)
    return found


def _csv_rows(path):
    with io.open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _build(csv_path, spec=None):
    return profile.build_profile(csvio.load_series(csv_path), spec)


def _by_series(profile_document, series_id):
    for item in profile_document["series"]:
        if item["series_id"] == series_id:
            return item
    raise AssertionError("series %r missing from the profile" % series_id)


# Module-scoped so the frozen fixture is parsed and profiled once per test session
# instead of once per assertion.
@pytest.fixture(scope="module")
def document():
    return _build(SERIES_CSV)


@pytest.fixture(scope="module")
def truth():
    return json.loads(read_text(TRUTH_JSON))


@pytest.fixture(scope="module")
def rows():
    return _csv_rows(SERIES_CSV)


class TestDoubleRunIsByteIdentical:
    def test_frozen_fixture_profiles_identically_twice(self, tmp_path, capsys):
        first = str(tmp_path / "a.json")
        second = str(tmp_path / "b.json")
        assert cli.main(["profile", SERIES_CSV, "-o", first]) == cli.EXIT_OK
        assert cli.main(["profile", SERIES_CSV, "-o", second]) == cli.EXIT_OK
        capsys.readouterr()
        assert read_bytes(first) == read_bytes(second)
        assert len(read_bytes(first)) > 1000

    def test_minimal_sample_profiles_identically_twice(self, tmp_path, capsys):
        first = str(tmp_path / "a.json")
        second = str(tmp_path / "b.json")
        assert cli.main(["profile", MINIMAL_CSV, "-o", first]) == cli.EXIT_OK
        assert cli.main(["profile", MINIMAL_CSV, "-o", second]) == cli.EXIT_OK
        capsys.readouterr()
        assert read_bytes(first) == read_bytes(second)

    def test_output_is_lf_utf8_without_bom_and_ends_with_a_newline(self, tmp_path):
        target = str(tmp_path / "profile.json")
        assert cli.main(["profile", MINIMAL_CSV, "-o", target]) == cli.EXIT_OK
        payload = read_bytes(target)
        assert not payload.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in payload
        assert payload.endswith(b"\n")
        assert payload.decode("utf-8")

    def test_output_is_exactly_the_canonical_json_form(self, tmp_path):
        target = str(tmp_path / "profile.json")
        cli.main(["profile", MINIMAL_CSV, "-o", target])
        payload = read_bytes(target)
        reparsed = json.loads(payload.decode("utf-8"))
        assert payload == canon.canonical_json_bytes(reparsed)


class TestProfileDocumentShape:
    def test_contains_only_integers_and_strings(self):
        document = _build(SERIES_CSV)
        assert list(iter_floats(document)) == []
        canon.assert_hashable(document)

    def test_has_no_clock_fields_and_no_iso_string_anywhere(self):
        document = _build(SERIES_CSV)
        assert not (_all_keys(document) & _FORBIDDEN_CLOCK_KEYS)
        offenders = [text for text in _all_strings(document) if _ISO_STRING_RE.search(text)]
        assert offenders == [], offenders

    def test_parameters_are_the_resolved_values_not_the_raw_spec(self):
        document = _build(SERIES_CSV)
        assert document["params"] == profile.resolve_spec()
        assert set(document["params"]) == set(profile.DEFAULT_SPEC)
        for key in profile._INT_KEYS:
            assert isinstance(document["params"][key], int)

    def test_reported_default_offset_is_the_one_that_was_applied(self):
        document = _build(SERIES_CSV)
        assert document["time"]["default_offset_min"] == document["params"]["timezone_offset_min"]

    def test_source_is_identified_by_digest_not_by_path(self):
        document = _build(SERIES_CSV)
        assert document["source"]["file"] == "series.csv"
        assert document["source"]["sha256"] == csvio.load_series(SERIES_CSV).stats["sha256"]
        assert document["source"]["size_bytes"] == os.path.getsize(SERIES_CSV)

    def test_schema_version_is_pinned(self):
        assert _build(SERIES_CSV)["schema_version"] == profile.PROFILE_VERSION


class TestDefaultsArePinned:
    """Every default is spelled out here, so drifting one is a deliberate two-file edit.

    Without a golden copy, a "no hidden defaults" test that reads its expectation out of
    the document it is checking will happily agree with whatever the default became.
    """

    def test_profile_defaults_are_exactly_these(self):
        assert profile.resolve_spec() == {
            "timestamp_column": None,
            "value_column": None,
            "series_id_column": None,
            "timezone_offset_min": 0,
            "duplicate_timestamp_max": 1,
            "non_monotonic_max": 0,
            "default_series_id": "series",
            "gap_factor": 3,
            "zero_run_min": 2,
            "missing_run_min": 1,
        }

    def test_csv_contract_defaults_are_exactly_these(self):
        assert csvio.resolve_spec() == {
            "timestamp_column": None,
            "value_column": None,
            "series_id_column": None,
            "timezone_offset_min": 0,
            "duplicate_timestamp_max": 1,
            "non_monotonic_max": 0,
            "default_series_id": "series",
        }

    def test_the_profile_spec_widens_the_csv_spec_without_renaming_anything(self):
        shared = set(csvio.DEFAULT_SPEC)
        assert shared <= set(profile.DEFAULT_SPEC)
        assert set(profile.DEFAULT_SPEC) - shared == {"gap_factor", "zero_run_min", "missing_run_min"}


class TestFrozenFixtureCrossCheck:
    """Every interval the profile reports must be the interval the generator planted."""

    def test_dominant_cadence_is_the_declared_five_minutes(self, document, truth):
        for item in document["series"]:
            assert item["cadence"]["dominant_interval_ms"] == truth["cadence_ms"]
            assert item["cadence"]["median_interval_ms"] == truth["cadence_ms"]
            # 3 is the pinned gap_factor (see TestDefaultsArePinned), written as a literal
            # here on purpose: reading it back out of the document would make this
            # assertion compare the document with itself and survive a drifted default.
            assert item["cadence"]["gap_threshold_ms"] == 3 * truth["cadence_ms"]

    def test_gaps_match_the_planted_gaps(self, document, truth):
        reported = sorted(
            (item["series_id"], gap["prev_row"], gap["row_no"], gap["interval_ms"])
            for item in document["series"]
            for gap in item["gaps"]
        )
        planted = sorted(
            (gap["series_id"], gap["prev_row"], gap["row_no"], gap["interval_ms"])
            for gap in truth["planted"]["gaps"]
        )
        assert reported == planted
        assert len(reported) == 3

    def test_missing_runs_match_the_planted_runs(self, document, truth):
        reported = sorted(
            (item["series_id"], run["start_row"], run["end_row"], run["n_points"])
            for item in document["series"]
            for run in item["missing_runs"]
        )
        planted = sorted(
            (run["series_id"], run["start_row"], run["end_row"], run["n_points"])
            for run in truth["planted"]["missing_runs"]
        )
        assert reported == planted
        assert len(reported) == 3

    def test_zero_runs_match_the_planted_runs(self, document, truth):
        reported = sorted(
            (item["series_id"], run["start_row"], run["end_row"], run["n_points"])
            for item in document["series"]
            for run in item["zero_runs"]
        )
        planted = sorted(
            (run["series_id"], run["start_row"], run["end_row"], run["n_points"])
            for run in truth["planted"]["zero_runs"]
        )
        assert reported == planted
        assert len(reported) == 3

    def test_duplicate_timestamps_match_the_planted_duplicate(self, document, truth):
        reported = [
            (item["series_id"], duplicate["row_nos"], duplicate["extra_rows"])
            for item in document["series"]
            for duplicate in item["duplicate_timestamps"]
        ]
        planted = [
            (
                duplicate["series_id"],
                sorted(duplicate["row_nos"]),
                1,
            )
            for duplicate in truth["planted"]["duplicate_timestamps"]
        ]
        assert reported == planted

    def test_no_series_reports_a_non_monotonic_point(self, document):
        for item in document["series"]:
            assert item["non_monotonic_points"] == []
        assert document["quality"]["n_non_monotonic_points"] == 0

    def test_quality_counts_add_up_to_the_per_series_counts(self, document):
        quality = document["quality"]
        assert quality["n_series"] == len(document["series"])
        assert quality["n_rows"] == sum(item["n_rows"] for item in document["series"])
        assert quality["n_gap_intervals"] == sum(len(item["gaps"]) for item in document["series"])
        assert quality["n_zero_runs"] == sum(len(item["zero_runs"]) for item in document["series"])
        assert quality["n_missing_runs"] == sum(
            len(item["missing_runs"]) for item in document["series"]
        )
        assert quality["n_duplicate_timestamps"] == sum(
            len(item["duplicate_timestamps"]) for item in document["series"]
        )

    def test_offset_switches_are_recorded_because_the_fixture_mixes_forms(self, document):
        assert len(document["time"]["distinct_offsets"]) == 2
        assert document["quality"]["n_offset_switches"] >= 2
        assert document["time"]["n_explicit_offset_rows"] > 0
        assert document["time"]["n_implicit_offset_rows"] > 0

    def test_irregularity_is_ppm_of_the_exact_ratio(self, document):
        for item in document["series"]:
            cadence = item["cadence"]
            assert 0 < cadence["irregular_ratio_ppm"] < 1000000
            assert cadence["irregular_count"] == sum(
                bucket["count"]
                for bucket in cadence["distribution"]
                if bucket["interval_ms"] != cadence["dominant_interval_ms"]
            )


class TestPlantedAnomaliesArePresentInTheData:
    """Reading the CSV directly: each truth segment must really stand out where it says."""

    @staticmethod
    def _value(rows, row_no):
        cell = rows[row_no - 2]["value"]
        return None if cell == "" else float(cell)

    @staticmethod
    def _series(rows, row_no):
        return rows[row_no - 2]["series_id"]

    def _baseline(self, rows, series_id, row_no, span=12):
        """Median-ish baseline from the same series just before the segment."""
        values = []
        for offset in range(span, 0, -1):
            candidate = row_no - offset
            if candidate < 2:
                continue
            if self._series(rows, candidate) != series_id:
                continue
            value = self._value(rows, candidate)
            if value is not None:
                values.append(value)
        values.sort()
        assert values, "no baseline samples found before row %d" % row_no
        return values[len(values) // 2]

    def _series_slice(self, rows, series_id, start_row, end_row):
        """Rows of one series inside an inclusive source-row span (the file is interleaved)."""
        found = []
        for row_no in range(start_row, end_row + 1):
            if self._series(rows, row_no) != series_id:
                continue
            found.append((row_no, self._value(rows, row_no)))
        return found

    def test_segment_rows_belong_to_the_declared_series(self, rows, truth):
        for segment in truth["segments"]:
            assert self._series(rows, segment["start_row"]) == segment["series_id"]
            assert self._series(rows, segment["end_row"]) == segment["series_id"]

    def test_spikes_and_level_shifts_deviate_by_at_least_half_the_magnitude(self, rows, truth):
        checked = 0
        for segment in truth["segments"]:
            if segment["type"] not in ("spike", "level_shift"):
                continue
            value = self._value(rows, segment["start_row"])
            assert value is not None
            baseline = self._baseline(rows, segment["series_id"], segment["start_row"])
            magnitude = segment["magnitude_milli"] / 1000.0
            assert abs(value - baseline) >= 0.5 * magnitude, (segment["segment_id"], value, baseline)
            checked += 1
        assert checked >= 2

    def test_missing_runs_are_actually_empty_and_zero_runs_are_actually_zero(self, rows, truth):
        for run in truth["planted"]["missing_runs"]:
            inside = self._series_slice(rows, run["series_id"], run["start_row"], run["end_row"])
            assert len(inside) == run["n_points"], run
            for row_no, value in inside:
                assert value is None, (run, row_no)
        for run in truth["planted"]["zero_runs"]:
            inside = self._series_slice(rows, run["series_id"], run["start_row"], run["end_row"])
            assert len(inside) == run["n_points"], run
            for row_no, value in inside:
                assert value == 0.0, (run, row_no)

    def test_planed_segments_are_contiguous_inside_one_series(self, rows, truth):
        # A planted segment must not silently span a data gap or another series.
        for segment in truth["segments"]:
            inside = self._series_slice(
                rows, segment["series_id"], segment["start_row"], segment["end_row"]
            )
            assert len(inside) == segment["n_points"], segment["segment_id"]

    def test_variance_shifts_have_a_wider_spread_than_their_neighbourhood(self, rows, truth):
        checked = 0
        for segment in truth["segments"]:
            if segment["type"] != "variance_shift":
                continue
            inside = [
                self._value(rows, row_no)
                for row_no in range(segment["start_row"], segment["end_row"] + 1)
            ]
            inside = [value for value in inside if value is not None]
            assert len(inside) >= 30
            outside = []
            for row_no in range(max(2, segment["start_row"] - 40), segment["start_row"] - 1):
                if self._series(rows, row_no) != segment["series_id"]:
                    continue
                value = self._value(rows, row_no)
                if value is not None:
                    outside.append(value)
            assert len(outside) >= 10
            assert spread(inside) > 2.0 * spread(outside), segment["segment_id"]
            checked += 1
        assert checked >= 2


def spread(values):
    """Mean absolute deviation: a spread measure that needs no transcendental function."""
    total = 0.0
    for value in values:
        total += value
    mean = total / float(len(values))
    deviation = 0.0
    for value in values:
        deviation += abs(value - mean)
    return deviation / float(len(values))


class TestMinimalSampleProfile:
    def test_reports_one_series_with_one_gap_one_missing_run_and_one_zero_run(self):
        document = _build(MINIMAL_CSV)
        assert document["quality"]["n_series"] == 1
        assert document["quality"]["n_rows"] == 16
        assert document["quality"]["n_values_missing"] == 1
        assert document["quality"]["n_gap_intervals"] == 1
        assert document["quality"]["n_missing_runs"] == 1
        assert document["quality"]["n_zero_runs"] == 1
        series = document["series"][0]
        assert series["series_id"] == "series"
        assert series["gaps"][0]["prev_row"] == 8
        assert series["gaps"][0]["row_no"] == 9
        assert series["zero_runs"][0]["n_points"] == 2

    def test_declared_timezone_shifts_offset_less_rows(self, write_text_file):
        source = write_text_file("timestamp,value\n2024-03-01T00:00:00,1\n2024-03-01T00:05:00,2\n")
        default = _by_series(_build(source), "series")
        shifted_document = profile.build_profile(
            csvio.load_series(source, {"timezone_offset_min": 480})
        )
        shifted = _by_series(shifted_document, "series")
        assert default["first_ms"] - shifted["first_ms"] == 480 * 60000
        assert default["cadence"]["dominant_interval_ms"] == 300000
        assert shifted["cadence"]["dominant_interval_ms"] == 300000
        assert default["n_rows"] == shifted["n_rows"]
        assert shifted_document["time"]["n_implicit_offset_rows"] == 2
        assert shifted_document["params"]["timezone_offset_min"] == 480

    def test_explicit_offsets_ignore_the_declared_zone(self):
        # The minimal sample writes every timestamp with an explicit `Z`, so declaring a
        # zone must not move a single instant and must not create implicit rows.
        default_document = _build(MINIMAL_CSV)
        shifted_document = profile.build_profile(
            csvio.load_series(MINIMAL_CSV), {"timezone_offset_min": 480}
        )
        default = _by_series(default_document, "series")
        shifted = _by_series(shifted_document, "series")
        assert default["first_ms"] == shifted["first_ms"]
        assert default_document["time"]["n_implicit_offset_rows"] == 0
        assert shifted_document["time"]["n_implicit_offset_rows"] == 0
        assert [entry["offset_min"] for entry in shifted_document["time"]["distinct_offsets"]] == [0]


class TestCmdProfileFailureModes:
    def test_bad_input_exits_usage_and_writes_nothing(self, tmp_path, write_text_file, capsys):
        source = write_text_file("timestamp,value\nbroken,1\n")
        target = tmp_path / "out.json"
        assert cli.main(["profile", source, "-o", str(target)]) == cli.EXIT_USAGE
        captured = capsys.readouterr()
        assert "E_TS_UNPARSEABLE" in captured.err
        assert not target.exists(), "a failed profile must not leave a partial artifact"

    def test_missing_input_file_exits_usage(self, tmp_path, capsys):
        target = tmp_path / "out.json"
        missing = str(tmp_path / "absent.csv")
        assert cli.main(["profile", missing, "-o", str(target)]) == cli.EXIT_USAGE
        capsys.readouterr()
        assert not target.exists()

    def test_unwritable_output_exits_usage(self, tmp_path, capsys):
        target = tmp_path / "no_such_dir" / "out.json"
        assert cli.main(["profile", MINIMAL_CSV, "-o", str(target)]) == cli.EXIT_USAGE
        assert "cannot write" in capsys.readouterr().err
