"""CSV contract parsing + per-row validation (M1, K9).

API:
  ERROR_CODES: dict[str, str]                        # single definition point (data/README 4.4)
  load_series(path, spec=None) -> ParsedSeries
  resolve_spec(spec) -> dict                         # no hidden defaults (K8)
  format_errors(errors) -> str

Column contract: a timestamp column plus a value column, plus an optional series_id
column. Roles are resolved either from run-spec or from a synonym whitelist; an
ambiguous match is an error, never a guess.

Error discipline (K9):
  * every error carries a source line number or a column name;
  * all errors are collected and reported at once -- never first-error-and-stop;
  * exit code 2 (usage/input) is the caller's business; this module only reports.

Missingness is data, not damage: an empty cell (or NA/NaN/null/none/-) becomes `None`.
No zero-fill, no interpolation -- missingness is an input to profiling and to the rule
detector. Non-finite numbers are rejected rather than propagated, because a NaN would
silently poison every downstream interval and score.
"""

import csv
import hashlib
import io
import re

from .timebase import TimeParseError, parse_timestamp

# The seven codes of data/README.md 4.4. Single definition point: nothing else in the
# repository may hard-code one of these strings.
ERROR_CODES = {
    "E_EMPTY_FILE": "file is empty or carries a header but no data rows",
    "E_MISSING_COLUMN": "timestamp or value column not found (and not named explicitly)",
    "E_DUPLICATE_COLUMN": "duplicate column name, or a column name that cannot be resolved uniquely",
    "E_TS_UNPARSEABLE": "timestamp cell is not a legal ISO-8601 timestamp",
    "E_VALUE_UNPARSEABLE": "value cell is not a finite decimal number (empty cells are missing, not errors)",
    "E_DUPLICATE_TIMESTAMP": "more repeated timestamps inside one series than the run-spec allows",
    "E_NON_MONOTONIC": "more out-of-order timestamps inside one series than the run-spec allows",
}

# Synonym whitelists (plan/03: `timestamp|time|ts`, `value|val|y`). Matching is
# case-insensitive on the stripped header cell.
TIMESTAMP_SYNONYMS = ("timestamp", "time", "ts")
VALUE_SYNONYMS = ("value", "val", "y")
SERIES_SYNONYMS = ("series_id", "series", "metric_id", "metric")

MISSING_TOKENS = frozenset(("", "na", "n/a", "nan", "null", "none", "-", "--"))

# A finite decimal number, spelled the same way in every language we mirror to:
# no underscores, no hex, no `inf`/`nan`, no thousands separators.
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")

# No hidden engine defaults (K8): every value below is copied into the resolved spec and
# therefore into profile.json, so a reader can see exactly what was applied.
DEFAULT_SPEC = {
    "timestamp_column": None,
    "value_column": None,
    "series_id_column": None,
    "timezone_offset_min": 0,
    "duplicate_timestamp_max": 1,
    "non_monotonic_max": 0,
    "default_series_id": "series",
}


class InputError(object):
    """One contract violation: a stable code plus where it happened."""

    __slots__ = ("code", "row_no", "column", "detail")

    def __init__(self, code, row_no=None, column=None, detail=""):
        if code not in ERROR_CODES:
            raise KeyError("unknown error code: %r" % (code,))
        self.code = code
        self.row_no = row_no
        self.column = column
        self.detail = detail

    def sort_key(self):
        return (self.row_no if self.row_no is not None else 0, self.code, self.column or "", self.detail)

    def describe(self):
        where = ""
        if self.row_no is not None:
            where = "row %d: " % self.row_no
        elif self.column is not None:
            where = "column %r: " % (self.column,)
        return "%s%s: %s" % (where, self.code, self.detail)

    def __repr__(self):
        return "InputError(%r, row_no=%r, column=%r, detail=%r)" % (
            self.code,
            self.row_no,
            self.column,
            self.detail,
        )


class CsvContractError(Exception):
    """Carries *every* error found in one pass; the caller decides the exit code."""

    def __init__(self, errors, path=None):
        self.errors = sorted(errors, key=InputError.sort_key)
        self.path = path
        head = "%s: %d input error(s)" % (path or "<input>", len(self.errors))
        Exception.__init__(self, head + "\n" + format_errors(self.errors))


def format_errors(errors):
    return "\n".join(error.describe() for error in errors)


class ParsedSeries(object):
    """The parsed series plus the metadata the profile needs.

    `rows_by_series[series_id]` is a list of `(row_no, epoch_ms, value_or_none)` in
    source order; `row_no` is the physical 1-based line number in the CSV (header = 1),
    which is what `start_row`/`end_row` and every error message mean.
    `offset_records` is `(row_no, offset_min, offset_explicit)` in source order and is
    what lets the profile record declared-vs-explicit offsets and their switches.
    `spec` is the *resolved* spec that was actually applied while parsing, so downstream
    documents can report the applied value instead of a re-guessed one (K8).
    """

    def __init__(self, path, header, columns, rows_by_series, offset_records, stats, spec=None):
        self.path = path
        self.header = header
        self.columns = columns
        self.rows_by_series = rows_by_series
        self.offset_records = offset_records
        self.stats = stats
        self.spec = dict(spec) if spec else {}

    @property
    def series_order(self):
        return sorted(self.rows_by_series)

    @property
    def n_rows(self):
        return sum(len(rows) for rows in self.rows_by_series.values())

    def rows(self, series_id):
        return self.rows_by_series[series_id]

    def __repr__(self):
        return "ParsedSeries(path=%r, series=%d, rows=%d)" % (
            self.path,
            len(self.rows_by_series),
            self.n_rows,
        )


def resolve_spec(spec=None):
    """Merge a caller spec over DEFAULT_SPEC; unknown keys are rejected loudly."""
    resolved = dict(DEFAULT_SPEC)
    if spec:
        unknown = sorted(set(spec) - set(DEFAULT_SPEC))
        if unknown:
            raise KeyError("unknown run-spec key(s): %s" % ", ".join(unknown))
        resolved.update(spec)
    resolved["timezone_offset_min"] = int(resolved["timezone_offset_min"])
    resolved["duplicate_timestamp_max"] = int(resolved["duplicate_timestamp_max"])
    resolved["non_monotonic_max"] = int(resolved["non_monotonic_max"])
    return resolved


def parse_value(text):
    """Return the float value of a cell, or `None` when the cell is a missing marker.

    Raises ValueError for anything that is not a finite decimal -- including `inf`/`nan`
    spellings that `float()` would otherwise accept.
    """
    stripped = text.strip()
    if stripped.lower() in MISSING_TOKENS:
        return None
    if not _NUMBER_RE.match(stripped):
        raise ValueError("not a finite decimal number: %r" % (text,))
    value = float(stripped)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("not a finite decimal number: %r" % (text,))
    return value


def _normalise_header(cell):
    return cell.replace("\ufeff", "").strip()


def _resolve_role(role, header, explicit, synonyms, required, errors):
    """Resolve one role to a header index, appending errors instead of guessing."""
    if explicit is not None:
        if explicit not in header:
            errors.append(
                InputError(
                    "E_MISSING_COLUMN",
                    column=explicit,
                    detail="%s column %r is not a column of this file (header: %s)"
                    % (role, explicit, header),
                )
            )
            return None
        return header.index(explicit)

    matches = [i for i, name in enumerate(header) if name.lower() in synonyms]
    if not matches:
        if required:
            errors.append(
                InputError(
                    "E_MISSING_COLUMN",
                    column=role,
                    detail="no %s column found; expected one of %s (header: %s)"
                    % (role, list(synonyms), header),
                )
            )
        return None
    if len(matches) > 1:
        errors.append(
            InputError(
                "E_DUPLICATE_COLUMN",
                column=role,
                detail="%d columns match the %s role (%s); refusing to guess"
                % (len(matches), role, [header[i] for i in matches]),
            )
        )
        return None
    return matches[0]


def _read_rows(path):
    """Read the file into `[(end_line_no, record)]`.

    The line numbers come from `csv.reader.line_num`, so a record spanning quoted
    embedded newlines still reports the physical line it ends on -- which is the line
    number every error message and every `start_row`/`end_row` must refer to.
    """
    with io.open(path, "rb") as handle:
        raw = handle.read()
    # Decode with `replace` rather than `strict`: undecodable bytes then surface as a
    # real E_TS/E_VALUE_UNPARSEABLE with a row number, instead of an uncoded traceback.
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text, newline=""))
    return raw, [(reader.line_num, record) for record in reader]


def load_series(path, spec=None):
    """Parse a long-format CSV into a `ParsedSeries`, or raise `CsvContractError`.

    One pass: column resolution, then every data row, then per-series timeline checks.
    All violations found on the way are raised together (K9).
    """
    resolved = resolve_spec(spec)
    errors = []
    raw, records = _read_rows(path)

    if not records:
        raise CsvContractError([InputError("E_EMPTY_FILE", detail="no rows at all")], path=path)

    header_line_no, header_record = records[0]
    header = [_normalise_header(cell) for cell in header_record]
    header_row_no = header_line_no
    if not any(header):
        raise CsvContractError(
            [InputError("E_EMPTY_FILE", row_no=header_row_no, detail="header row is empty")],
            path=path,
        )

    duplicates = sorted({name for name in header if header.count(name) > 1 and name})
    for name in duplicates:
        errors.append(
            InputError(
                "E_DUPLICATE_COLUMN",
                row_no=header_row_no,
                column=name,
                detail="column %r appears %d times in the header" % (name, header.count(name)),
            )
        )
    if duplicates:
        raise CsvContractError(errors, path=path)

    indices = {}
    for role, synonyms, required in (
        ("timestamp", TIMESTAMP_SYNONYMS, True),
        ("value", VALUE_SYNONYMS, True),
        ("series_id", SERIES_SYNONYMS, False),
    ):
        indices[role] = _resolve_role(
            role, header, resolved[role + "_column"], synonyms, required, errors
        )
    if errors:
        raise CsvContractError(errors, path=path)

    columns = {}
    for role in ("timestamp", "value", "series_id"):
        columns[role] = header[indices[role]] if indices[role] is not None else None

    data_records = records[1:]
    blank_rows = 0
    ragged_rows = 0
    missing_series_cells = 0
    rows_by_series = {}
    offset_records = []
    parsed_ok = 0
    n_values_present = 0

    for row_no, record in data_records:
        if not any(cell.strip() for cell in record):
            blank_rows += 1
            continue
        if len(record) != len(header):
            ragged_rows += 1
        cells = list(record[: len(header)]) + [""] * max(0, len(header) - len(record))

        try:
            stamp = parse_timestamp(cells[indices["timestamp"]], resolved["timezone_offset_min"])
        except TimeParseError as exc:
            errors.append(
                InputError(
                    "E_TS_UNPARSEABLE",
                    row_no=row_no,
                    column=columns["timestamp"],
                    detail="%s" % (exc,),
                )
            )
            continue

        try:
            value = parse_value(cells[indices["value"]])
        except ValueError as exc:
            errors.append(
                InputError(
                    "E_VALUE_UNPARSEABLE",
                    row_no=row_no,
                    column=columns["value"],
                    detail="%s" % (exc,),
                )
            )
            continue

        if indices["series_id"] is None:
            series_id = resolved["default_series_id"]
        else:
            series_id = cells[indices["series_id"]].strip()
            if not series_id:
                series_id = resolved["default_series_id"]
                missing_series_cells += 1

        rows_by_series.setdefault(series_id, []).append((row_no, stamp.epoch_ms, value))
        offset_records.append((row_no, stamp.offset_min, stamp.offset_explicit))
        parsed_ok += 1
        if value is not None:
            n_values_present += 1

    errors.extend(
        _timeline_errors(
            rows_by_series, resolved["duplicate_timestamp_max"], resolved["non_monotonic_max"]
        )
    )

    if not rows_by_series and not errors:
        errors.append(
            InputError("E_EMPTY_FILE", row_no=header_row_no, detail="header only, no data rows")
        )
    if errors:
        raise CsvContractError(errors, path=path)

    stats = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "n_records": len(records),
        "n_data_rows": parsed_ok,
        "n_blank_rows": blank_rows,
        "n_ragged_rows": ragged_rows,
        "n_missing_series_cells": missing_series_cells,
        "n_values_present": n_values_present,
        "n_values_missing": parsed_ok - n_values_present,
        "n_series": len(rows_by_series),
    }
    return ParsedSeries(path, header, columns, rows_by_series, offset_records, stats, resolved)


def _timeline_errors(rows_by_series, duplicate_max, non_monotonic_max):
    """Per-series duplicate-timestamp and ordering checks (thresholds from run-spec)."""
    errors = []
    for series_id in sorted(rows_by_series):
        rows = rows_by_series[series_id]
        seen = {}
        duplicate_rows = []
        for row_no, epoch_ms, _value in rows:
            if epoch_ms in seen:
                duplicate_rows.append((row_no, seen[epoch_ms]))
            else:
                seen[epoch_ms] = row_no
        if len(duplicate_rows) > duplicate_max:
            for row_no, first_row in duplicate_rows[duplicate_max:]:
                errors.append(
                    InputError(
                        "E_DUPLICATE_TIMESTAMP",
                        row_no=row_no,
                        column=series_id,
                        detail="timestamp already used by row %d (series %r allows %d repetition(s))"
                        % (first_row, series_id, duplicate_max),
                    )
                )
        backwards = []
        for index in range(1, len(rows)):
            if rows[index][1] < rows[index - 1][1]:
                backwards.append((rows[index][0], rows[index - 1][0]))
        if len(backwards) > non_monotonic_max:
            for row_no, previous_row in backwards[non_monotonic_max:]:
                errors.append(
                    InputError(
                        "E_NON_MONOTONIC",
                        row_no=row_no,
                        column=series_id,
                        detail="timestamp is earlier than row %d (series %r allows %d out-of-order step(s))"
                        % (previous_row, series_id, non_monotonic_max),
                    )
                )
    return errors
