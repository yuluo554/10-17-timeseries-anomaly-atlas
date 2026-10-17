"""M1 time-base tests (K5): the handwritten integer algorithm must be falsified by the
standard library before it is trusted.

Every cross-assertion below recomputes the value through a different route -- a
`timedelta` reassembled as integers, and `date.toordinal` -- instead of calling back into
the module under test. The falsifiability probe at the end proves the cross-check really
rejects a wrong algorithm rather than rubber-stamping one.
"""

import ast
import calendar
import csv
import datetime
import io
import os
import re

import pytest

from anomaly_atlas import timebase

from conftest import SERIES_CSV

_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

# strptime is used instead of fromisoformat because the latter only gained general
# fraction/offset support after 3.8; the suite must behave the same on both interpreters.
_STDLIB_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z")

_IMPLICIT_FORM_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$")


def _normalise_for_stdlib(text):
    """Rewrite a fixture timestamp into `<date>T<time>+HHMM` with a 3-digit fraction."""
    stamped = text.strip().replace(" ", "T")
    date_part, separator, time_part = stamped.partition("T")
    assert separator == "T", text

    match = re.search(r"\.(\d+)", time_part)
    if match:
        digits = (match.group(1) + "000")[:3]
        time_part = time_part[: match.start()] + "." + digits + time_part[match.end() :]

    if time_part.endswith(("Z", "z")):
        time_part = time_part[:-1] + "+0000"
    else:
        match = re.search(r"([+-])(\d{2}):?(\d{2})$", time_part)
        if match:
            time_part = time_part[: match.start()] + match.group(1) + match.group(2) + match.group(3)
        elif re.search(r"[+-]\d{2}$", time_part):
            time_part = time_part + "00"
        else:
            time_part = time_part + "+0000"
    return date_part + "T" + time_part


def _epoch_ms_via_stdlib(text):
    """Independent route: parse with the stdlib, then reassemble the timedelta in integers."""
    normalised = _normalise_for_stdlib(text)
    for fmt in _STDLIB_FORMATS:
        try:
            parsed = datetime.datetime.strptime(normalised, fmt)
            break
        except ValueError:
            continue
    else:
        raise AssertionError("the test helper cannot parse %r (normalised %r)" % (text, normalised))
    delta = parsed - _EPOCH
    return delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000


def _det_lcg(state):
    """A tiny deterministic integer generator: the sweep is reproducible, never random."""
    return (state * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)


class TestCivilAlgorithms:
    def test_matches_datetime_toordinal_across_four_centuries(self):
        anchor = datetime.date(1970, 1, 1).toordinal()
        for year in range(1800, 2201):
            for month in range(1, 13):
                for day in (1, 15, calendar.monthrange(year, month)[1]):
                    expected = datetime.date(year, month, day).toordinal() - anchor
                    assert timebase.days_from_civil(year, month, day) == expected, (year, month, day)

    def test_round_trips_every_sampled_day(self):
        for days in range(-800000, 800001, 997):
            year, month, day = timebase.civil_from_days(days)
            assert timebase.days_from_civil(year, month, day) == days

    def test_century_leap_rules(self):
        assert timebase.is_valid_civil_date(2000, 2, 29) is True
        assert timebase.is_valid_civil_date(1900, 2, 29) is False
        assert timebase.is_valid_civil_date(2024, 2, 29) is True
        assert timebase.is_valid_civil_date(2023, 2, 29) is False
        assert timebase.is_valid_civil_date(2023, 4, 31) is False
        assert timebase.is_valid_civil_date(2023, 12, 32) is False
        assert timebase.is_valid_civil_date(2023, 0, 1) is False


class TestEpochMsToCivil:
    def test_cross_checked_against_timedelta(self):
        state = 12345
        for _ in range(4000):
            state = _det_lcg(state)
            milliseconds = (state >> 20) % 8000000000000 - 2000000000000
            expected = _EPOCH + datetime.timedelta(milliseconds=milliseconds)
            assert timebase.epoch_ms_to_civil(milliseconds) == (
                expected.year,
                expected.month,
                expected.day,
                expected.hour,
                expected.minute,
                expected.second,
                expected.microsecond // 1000,
            ), milliseconds

    def test_negative_epoch_decomposes_by_floor_not_truncation(self):
        assert timebase.epoch_ms_to_civil(-1) == (1969, 12, 31, 23, 59, 59, 999)
        assert timebase.epoch_ms_to_civil(0) == (1970, 1, 1, 0, 0, 0, 0)

    def test_iso_is_fixed_width(self):
        assert timebase.epoch_ms_to_iso(0) == "1970-01-01T00:00:00.000Z"
        assert timebase.epoch_ms_to_iso(1709164800123) == "2024-02-29T00:00:00.123Z"
        assert timebase.epoch_ms_to_iso(-1) == "1969-12-31T23:59:59.999Z"
        for milliseconds in (0, -1, 1, 1709164800000, -62135596800000, 253402300799999):
            assert len(timebase.epoch_ms_to_iso(milliseconds)) == 24

    def test_iso_round_trips_through_the_parser(self):
        for milliseconds in (0, -1, 1, 1709164800000, 1735689599999, 946684800000):
            assert timebase.parse_iso_to_epoch_ms(timebase.epoch_ms_to_iso(milliseconds)) == milliseconds


class TestParseOffsetSemantics:
    def test_explicit_offset_is_subtracted(self):
        utc = timebase.parse_iso_to_epoch_ms("2024-02-29T00:00:00Z")
        assert timebase.parse_iso_to_epoch_ms("2024-02-29T08:00:00+08:00") == utc
        assert timebase.parse_iso_to_epoch_ms("2024-02-29T08:00:00+0800") == utc
        assert timebase.parse_iso_to_epoch_ms("2024-02-28T16:00:00-08:00") == utc
        assert timebase.parse_iso_to_epoch_ms("2024-02-29T08:00:00+08") == utc

    def test_absent_offset_uses_the_declared_zone_and_is_reported(self):
        stamp = timebase.parse_timestamp("2024-02-29T08:00:00", default_tz_offset_min=480)
        assert stamp == timebase.ParsedTimestamp(
            epoch_ms=timebase.parse_iso_to_epoch_ms("2024-02-29T00:00:00Z"),
            offset_min=480,
            offset_explicit=False,
        )

    def test_explicit_offset_is_flagged_even_when_it_means_utc(self):
        stamp = timebase.parse_timestamp("2024-02-29T08:00:00Z", default_tz_offset_min=480)
        assert stamp.offset_min == 0
        assert stamp.offset_explicit is True

    def test_declared_zone_is_ignored_when_the_text_carries_one(self):
        declared = timebase.parse_iso_to_epoch_ms(
            "2024-02-29T08:00:00+08:00", default_tz_offset_min=60
        )
        assert declared == timebase.parse_iso_to_epoch_ms("2024-02-29T00:00:00Z")


class TestBoundaries:
    @pytest.mark.parametrize(
        "text,expected_iso",
        [
            ("2024-02-29T00:00:00Z", "2024-02-29T00:00:00.000Z"),  # leap day
            ("2023-03-01T00:00:00Z", "2023-03-01T00:00:00.000Z"),
            ("2024-01-31T23:59:59.999Z", "2024-01-31T23:59:59.999Z"),  # month end
            ("2024-12-31T23:59:59.999Z", "2024-12-31T23:59:59.999Z"),  # year end
            ("2024-02-29 12:34:56", "2024-02-29T12:34:56.000Z"),  # space separator
            ("2024-02-29T12:34:56.5Z", "2024-02-29T12:34:56.500Z"),  # one fractional digit
            ("2024-02-29T12:34:56.123456789Z", "2024-02-29T12:34:56.123Z"),  # truncated
            ("2024-02-29T12:34Z", "2024-02-29T12:34:00.000Z"),  # seconds omitted
            ("2024-02-29T12:34+08:00", "2024-02-29T04:34:00.000Z"),
            ("2000-02-29T00:00:00Z", "2000-02-29T00:00:00.000Z"),  # century leap day
        ],
    )
    def test_accepted_forms_and_the_instant_they_mean(self, text, expected_iso):
        epoch_ms = timebase.parse_iso_to_epoch_ms(text)
        assert timebase.epoch_ms_to_iso(epoch_ms) == expected_iso
        assert epoch_ms == _epoch_ms_via_stdlib(text)

    def test_month_and_year_rollover_are_exactly_one_millisecond_apart(self):
        year_end = timebase.parse_iso_to_epoch_ms("2024-12-31T23:59:59.999Z")
        assert timebase.epoch_ms_to_iso(year_end + 1) == "2025-01-01T00:00:00.000Z"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "notatime",
            "2023-02-29T00:00:00Z",  # 2023 is not a leap year
            "1900-02-29T00:00:00Z",  # 1900 is not a leap year (century rule)
            "2024-13-01T00:00:00Z",
            "2024-00-10T00:00:00Z",
            "2024-04-31T00:00:00Z",
            "2024-02-29T24:00:00Z",
            "2024-02-29T00:60:00Z",
            "2024-02-29T00:00:60Z",  # leap seconds are not representable on this grid
            "2024-02-29T00:00:00+99:00",
            "2024-02-29T00:00:00.Z",
            "2024-02-29T00:00:00.1234567890Z",  # more than 9 fraction digits
            "20240229T000000Z",
            "2024-02-29",
        ],
    )
    def test_rejected_forms(self, text):
        with pytest.raises(timebase.TimeParseError):
            timebase.parse_iso_to_epoch_ms(text)

    def test_surrounding_whitespace_is_tolerated(self):
        assert timebase.parse_iso_to_epoch_ms(" 2024-02-29T00:00:00Z ") == timebase.parse_iso_to_epoch_ms(
            "2024-02-29T00:00:00Z"
        )

    def test_non_string_input_is_rejected(self):
        with pytest.raises(timebase.TimeParseError):
            timebase.parse_iso_to_epoch_ms(1709164800000)


class TestFixtureRowsAreCrossChecked:
    """Every row of the frozen CSV, parsed by hand and by the stdlib, must agree."""

    @staticmethod
    def _fixture_rows():
        with io.open(SERIES_CSV, encoding="utf-8", newline="") as handle:
            return [(row["timestamp"], row["series_id"]) for row in csv.DictReader(handle)]

    def test_fixture_is_large_enough_to_be_evidence(self):
        assert len(self._fixture_rows()) > 2000, "the fixture shrank; the cross-check is vacuous"

    def test_every_fixture_row_agrees_with_the_stdlib(self):
        rows = self._fixture_rows()
        for text, _series_id in rows:
            assert timebase.parse_iso_to_epoch_ms(text) == _epoch_ms_via_stdlib(text), text
        assert len(rows) > 2000

    def test_fixture_covers_every_representation_form(self):
        # Positive control: if the fixture held only `...Z` rows, the claim that offsets,
        # declared zones and fractional seconds are exercised would rest on nothing.
        texts = [text for text, _series in self._fixture_rows()]
        assert any(text.endswith("Z") for text in texts)
        assert any(text.endswith("+08:00") for text in texts)
        assert any(_IMPLICIT_FORM_RE.match(text) for text in texts)
        assert all("." in text for text in texts)

    def test_parsed_fixture_instants_sit_on_a_clean_grid(self):
        # A mis-parsed row would show up as a stray interval, not as a silent wrong value.
        deltas = set()
        grouped = {}
        for text, series_id in self._fixture_rows():
            grouped.setdefault(series_id, []).append(timebase.parse_iso_to_epoch_ms(text))
        for stamps in grouped.values():
            for index in range(1, len(stamps)):
                deltas.add(stamps[index] - stamps[index - 1])
        assert deltas, "no intervals at all"
        assert all(delta >= 0 for delta in deltas), sorted(deltas)
        assert all(delta % 300000 == 0 for delta in deltas), sorted(deltas)
        assert 0 in deltas, "the planted duplicate timestamp did not survive parsing"
        assert 300000 in deltas
        assert len(deltas) <= 4, sorted(deltas)

    def test_fixture_offsets_are_recorded_and_switch(self):
        explicit = 0
        implicit = 0
        offsets = set()
        switches = 0
        previous = None
        for text, _series_id in self._fixture_rows():
            stamp = timebase.parse_timestamp(text)
            offsets.add(stamp.offset_min)
            explicit += 1 if stamp.offset_explicit else 0
            implicit += 0 if stamp.offset_explicit else 1
            if previous is not None and stamp.offset_min != previous:
                switches += 1
            previous = stamp.offset_min
        assert explicit > 0 and implicit > 0
        assert offsets == {0, 480}
        assert switches >= 2


class TestFalsifiability:
    """The cross-check must reject a wrong algorithm, or it is decoration."""

    @staticmethod
    def _off_by_one_days_from_civil(year, month, day):
        """A plausible bug: the day-of-year term forgets its `- 1`."""
        shifted = year - (1 if month <= 2 else 0)
        era = (shifted if shifted >= 0 else shifted - 399) // 400
        year_of_era = shifted - era * 400
        day_of_year = (153 * (month - 3 if month > 2 else month + 9) + 2) // 5 + day
        day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
        return era * 146097 + day_of_era - 719468

    def test_the_buggy_algorithm_really_is_wrong(self):
        anchor = datetime.date(1970, 1, 1).toordinal()
        mismatches = sum(
            1
            for year in (1800, 1900, 1969, 1970, 2000, 2024, 2100)
            if self._off_by_one_days_from_civil(year, 3, 1)
            != datetime.date(year, 3, 1).toordinal() - anchor
        )
        assert mismatches > 0, "the probe is not actually wrong; the cross-check proves nothing"

    def test_the_cross_check_catches_that_bug_but_the_module_does_not_have_it(self):
        anchor = datetime.date(1970, 1, 1).toordinal()
        for year in (1800, 1900, 1969, 2000, 2100):
            expected = datetime.date(year, 3, 1).toordinal() - anchor
            assert self._off_by_one_days_from_civil(year, 3, 1) != expected, year
            assert timebase.days_from_civil(year, 3, 1) == expected, year

    def test_fraction_digits_are_truncated_not_rounded(self):
        base = timebase.parse_iso_to_epoch_ms("2024-02-29T00:00:00Z")
        assert timebase.parse_iso_to_epoch_ms("2024-02-29T00:00:00.0005Z") == base
        assert timebase.parse_iso_to_epoch_ms("2024-02-29T00:00:00.9999Z") == base + 999

    def test_module_never_delegates_to_a_timezone_aware_stdlib(self):
        # `datetime`/`time` cannot be mirrored in JavaScript, so the module must not lean
        # on them (plan/06 D11). Checked on the parsed module, not on the prose.
        with io.open(os.path.join(os.path.dirname(timebase.__file__), "timebase.py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        forbidden_calls = {
            "fromisoformat",
            "strptime",
            "fromtimestamp",
            "utcnow",
            "now",
            "time",
            "localtime",
            "mktime",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in ("datetime", "time", "zoneinfo", "pytz")
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in ("datetime", "time", "zoneinfo", "pytz")
            if isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_calls, node.attr
