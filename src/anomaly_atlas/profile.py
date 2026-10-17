"""Data profile + quality card (M1) -> profile.json.

API:
  build_profile(parsed, spec=None) -> dict            # keys sorted on dump (K2)
  resolve_spec(spec=None) -> dict                     # no hidden defaults (K8)
  write_profile(path, profile) -> None
  cmd_profile(csv_path, out_path) -> int

Contents: parse summary, timezone/offset record (including offset switches), cadence
(interval distribution + dominant interval + irregularity), duplicate timestamps, gap
intervals, zero-value runs, missing-value runs, non-monotonic points, and a structured
quality card. Pure rule computation -- no model call, no clock, no randomness, and the
whole document is written as canonical JSON (K2): only integers and strings, sorted
keys, LF, trailing newline, so two runs over the same CSV are byte-identical.
"""

import os
import sys

from . import canon, csvio

PROFILE_VERSION = "1"

# Profile-level parameters, on top of the CSV contract parameters. Same rule as csvio:
# nothing is implicit, every resolved value is copied into profile.json["params"].
DEFAULT_SPEC = dict(csvio.DEFAULT_SPEC)
DEFAULT_SPEC.update(
    {
        "gap_factor": 3,
        "zero_run_min": 2,
        "missing_run_min": 1,
    }
)

_INT_KEYS = (
    "timezone_offset_min",
    "duplicate_timestamp_max",
    "non_monotonic_max",
    "gap_factor",
    "zero_run_min",
    "missing_run_min",
)
_STR_KEYS = ("timestamp_column", "value_column", "series_id_column", "default_series_id")


def resolve_spec(spec=None):
    """Merge a caller spec over the defaults; unknown keys are rejected loudly."""
    if spec:
        unknown = sorted(set(spec) - set(DEFAULT_SPEC))
        if unknown:
            raise KeyError("unknown run-spec key(s): %s" % ", ".join(unknown))
    resolved = dict(DEFAULT_SPEC)
    if spec:
        resolved.update(spec)
    for key in _INT_KEYS:
        resolved[key] = int(resolved[key])
    for key in _STR_KEYS:
        if resolved[key] is not None:
            resolved[key] = str(resolved[key])
    return resolved


def _runs(rows, predicate, min_length):
    """Maximal consecutive runs of rows satisfying `predicate`, at least `min_length` long."""
    found = []
    start = None
    for index in range(len(rows) + 1):
        inside = index < len(rows) and predicate(rows[index][2])
        if inside and start is None:
            start = index
        elif not inside and start is not None:
            end = index - 1
            length = end - start + 1
            if length >= min_length:
                found.append(
                    {
                        "start_row": rows[start][0],
                        "end_row": rows[end][0],
                        "n_points": length,
                        "start_ms": rows[start][1],
                        "end_ms": rows[end][1],
                    }
                )
            start = None
    return found


def _profile_series(series_id, rows, spec):
    """Per-series cadence, timeline anomalies and value-shape counts."""
    n_rows = len(rows)
    values = [row[2] for row in rows]
    stamps = [row[1] for row in rows]

    n_missing = 0
    n_zero = 0
    n_negative = 0
    n_positive = 0
    for value in values:
        if value is None:
            n_missing += 1
        elif value == 0.0:
            # `-0.0 == 0.0` too: a signed zero is still a zero-valued sample.
            n_zero += 1
        elif value < 0:
            n_negative += 1
        else:
            n_positive += 1

    intervals = []
    non_monotonic = []
    for index in range(1, n_rows):
        delta = stamps[index] - stamps[index - 1]
        if delta < 0:
            non_monotonic.append(
                {
                    "row_no": rows[index][0],
                    "prev_row_no": rows[index - 1][0],
                    "epoch_ms": stamps[index],
                    "prev_epoch_ms": stamps[index - 1],
                    "delta_ms": delta,
                }
            )
        elif delta > 0:
            intervals.append((rows[index - 1][0], rows[index][0], delta))

    counts = {}
    for _prev_row, _row, delta in intervals:
        counts[delta] = counts.get(delta, 0) + 1
    distribution = [{"interval_ms": delta, "count": counts[delta]} for delta in sorted(counts)]
    dominant = None
    if counts:
        # Total order: most frequent first, then the shortest interval. Never rely on
        # dict iteration order reaching the output (plan/02 section 4.2).
        dominant = sorted(counts, key=lambda delta: (-counts[delta], delta))[0]
    ordered = sorted(delta for _p, _r, delta in intervals)
    median = ordered[(len(ordered) - 1) // 2] if ordered else None
    gap_threshold = dominant * spec["gap_factor"] if dominant is not None else None

    gaps = []
    if gap_threshold is not None:
        stamp_by_row = {row[0]: row[1] for row in rows}
        for prev_row, row, delta in intervals:
            if delta > gap_threshold:
                gaps.append(
                    {
                        "prev_row": prev_row,
                        "row_no": row,
                        "prev_ms": stamp_by_row[prev_row],
                        "ms": stamp_by_row[row],
                        "interval_ms": delta,
                        "missing_points": delta // dominant - 1,
                    }
                )

    seen_rows = {}
    for row_no, epoch_ms, _value in rows:
        seen_rows.setdefault(epoch_ms, []).append(row_no)
    duplicates = [
        {"epoch_ms": epoch_ms, "row_nos": sorted(row_nos), "extra_rows": len(row_nos) - 1}
        for epoch_ms, row_nos in sorted(seen_rows.items())
        if len(row_nos) > 1
    ]

    irregular_count = len(intervals) - counts.get(dominant, 0) if dominant is not None else 0
    irregular_ppm = 0
    if intervals:
        irregular_ppm = (irregular_count * 1000000 + len(intervals) // 2) // len(intervals)

    return {
        "series_id": series_id,
        "n_rows": n_rows,
        "n_values_present": n_rows - n_missing,
        "n_values_missing": n_missing,
        "n_values_zero": n_zero,
        "n_values_negative": n_negative,
        "n_values_positive": n_positive,
        "first_ms": min(stamps) if stamps else None,
        "last_ms": max(stamps) if stamps else None,
        "span_ms": (max(stamps) - min(stamps)) if stamps else None,
        "cadence": {
            "n_intervals": len(intervals),
            "dominant_interval_ms": dominant,
            "median_interval_ms": median,
            "min_interval_ms": ordered[0] if ordered else None,
            "max_interval_ms": ordered[-1] if ordered else None,
            "gap_threshold_ms": gap_threshold,
            "irregular_count": irregular_count,
            "irregular_ratio_ppm": irregular_ppm,
            "distribution": distribution,
        },
        "gaps": gaps,
        "zero_runs": _runs(rows, lambda value: value == 0.0, spec["zero_run_min"]),
        "missing_runs": _runs(rows, lambda value: value is None, spec["missing_run_min"]),
        "duplicate_timestamps": duplicates,
        "non_monotonic_points": non_monotonic,
    }


def _time_block(parsed, spec):
    """Declared vs explicit offsets, and where the offset changes from row to row."""
    records = parsed.offset_records
    counts = {}
    first_row = {}
    for row_no, offset_min, _explicit in records:
        counts[offset_min] = counts.get(offset_min, 0) + 1
        if offset_min not in first_row:
            first_row[offset_min] = row_no
    switches = []
    for index in range(1, len(records)):
        if records[index][1] != records[index - 1][1]:
            switches.append(
                {
                    "row_no": records[index][0],
                    "prev_row_no": records[index - 1][0],
                    "from_offset_min": records[index - 1][1],
                    "to_offset_min": records[index][1],
                }
            )
    return {
        "default_offset_min": spec["timezone_offset_min"],
        "distinct_offsets": [
            {"offset_min": offset_min, "count": counts[offset_min], "first_row": first_row[offset_min]}
            for offset_min in sorted(counts)
        ],
        "n_explicit_offset_rows": sum(1 for record in records if record[2]),
        "n_implicit_offset_rows": sum(1 for record in records if not record[2]),
        "offset_switches": switches,
    }


def _quality(parsed, series_profiles, time_block):
    """Counts only (intervals live per series); this is the structured quality card."""
    return {
        "n_rows": parsed.n_rows,
        "n_series": len(series_profiles),
        "n_values_present": sum(item["n_values_present"] for item in series_profiles),
        "n_values_missing": sum(item["n_values_missing"] for item in series_profiles),
        "n_values_zero": sum(item["n_values_zero"] for item in series_profiles),
        "n_duplicate_timestamps": sum(
            len(item["duplicate_timestamps"]) for item in series_profiles
        ),
        "n_duplicate_extra_rows": sum(
            duplicate["extra_rows"]
            for item in series_profiles
            for duplicate in item["duplicate_timestamps"]
        ),
        "n_non_monotonic_points": sum(
            len(item["non_monotonic_points"]) for item in series_profiles
        ),
        "n_gap_intervals": sum(len(item["gaps"]) for item in series_profiles),
        "n_zero_runs": sum(len(item["zero_runs"]) for item in series_profiles),
        "n_missing_runs": sum(len(item["missing_runs"]) for item in series_profiles),
        "n_offset_switches": len(time_block["offset_switches"]),
        "n_blank_rows": parsed.stats["n_blank_rows"],
        "n_ragged_rows": parsed.stats["n_ragged_rows"],
        "n_missing_series_cells": parsed.stats["n_missing_series_cells"],
    }


def build_profile(parsed, spec=None):
    """Build the profile document from a parsed series. Integers and strings only (K3).

    When `spec` is omitted, the spec recorded on `parsed` is used -- that is the spec
    which was actually applied during parsing, so the document can never claim a
    timezone or tolerance that was not in force (K8: no hidden defaults, no drift).
    """
    resolved = resolve_spec(spec if spec is not None else parsed.spec)
    series_profiles = [
        _profile_series(series_id, parsed.rows_by_series[series_id], resolved)
        for series_id in parsed.series_order
    ]
    time_block = _time_block(parsed, resolved)
    profile = {
        "schema_version": PROFILE_VERSION,
        "source": {
            "file": os.path.basename(parsed.path),
            "sha256": parsed.stats["sha256"],
            "size_bytes": parsed.stats["size_bytes"],
            "n_csv_records": parsed.stats["n_records"],
        },
        "params": resolved,
        "columns": parsed.columns,
        "series": series_profiles,
        "time": time_block,
        "quality": _quality(parsed, series_profiles, time_block),
    }
    return profile


def write_profile(path, profile):
    """Write canonical JSON bytes: UTF-8 without BOM, LF, trailing newline (K2)."""
    with open(path, "wb") as handle:
        handle.write(canon.canonical_json_bytes(profile))


def cmd_profile(csv_path, out_path):
    """CLI body for `profile`: 0 on success, 2 on any usage/input error."""
    from .cli import EXIT_OK, EXIT_USAGE

    try:
        parsed = csvio.load_series(csv_path)
    except csvio.CsvContractError as exc:
        print("input error: %s" % (exc,), file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print("error: cannot read %s: %s" % (csv_path, exc), file=sys.stderr)
        return EXIT_USAGE

    try:
        write_profile(out_path, build_profile(parsed))
    except OSError as exc:
        print("error: cannot write %s: %s" % (out_path, exc), file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK
