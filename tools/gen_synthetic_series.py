"""Synthetic cold-chain warehouse series + planted truth + manifest (M1, K11).

Scenario (fictional): "冷链仓储温控与能耗监测（虚构）" -- three series on one 5-minute
grid (temperature / humidity / energy_kwh), a 24-hour daily profile, a slow drift and
bounded noise. Four anomaly families are planted on purpose (spike, level shift,
variance shift, missing/zero run) plus known data gaps; the planted intervals are
exported as truth, so no expected value is ever hand-written.

Generator discipline (K11):
  * RNG is a self-contained splitmix64 (stdlib `random` is never imported -- its
    cross-version sequence stability is not promised anyway);
  * the seed is an explicit argument and is written into the manifest;
  * `--check` verifies the manifest's own sha256 ledger first and then re-generates into
    a temporary directory for a byte-for-byte comparison, so a tampered or missing
    frozen artifact is exit 2;
  * truth holds inputs and expectations only -- never an `observed` field, and no
    always-dumb status key;
  * the generator asserts its own truth is non-trivial *and* detectable before writing
    anything (segment counts, window-boundary coverage, probe straddling, and -- added when
    M2 measured that humidity's planted spikes sat under its own noise floor -- a magnitude
    floor against each series' noise amplitude plus a daily-cycle floor).

Usage:
  python tools/gen_synthetic_series.py [--seed N] [--out-root DIR]
  python tools/gen_synthetic_series.py --check
"""

import argparse
import io
import json
import os
import shutil
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO_ROOT, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from anomaly_atlas import canon  # noqa: E402
from anomaly_atlas.cli import _ensure_utf8_stdio  # noqa: E402  (K10: single definition point)
from anomaly_atlas.timebase import epoch_ms_to_iso, parse_iso_to_epoch_ms  # noqa: E402

GENERATOR_VERSION = "1"
SCENARIO = "冷链仓储温控与能耗监测（虚构）"
DEFAULT_SEED = 20240229

N_GRID_POINTS = 1000
CADENCE_MS = 300000  # 5 minutes
PERIOD_MINUTES = 1440  # 24-hour daily profile
WINDOW_POINTS = 24  # rolling detector window (plan/06 P4)
MAX_GAP_MS = 1800000  # 30 minutes: the episode merge threshold (K7)
VALUE_DECIMALS = 2
MILLI = 1000
TZ_OFFSET_FOR_LOCAL_BLOCK = 480  # +08:00 rows exercise the explicit-offset path

START_MS = parse_iso_to_epoch_ms("2024-02-29T00:00:00Z")  # leap day + month boundary

# The same instants written four legal ways, in blocks, so the frozen CSV exercises
# every branch of the timestamp parser (Z / explicit offset / declared zone / space
# separator + fractional seconds) while staying perfectly regular in time.
_REPRESENTATION_BLOCKS = ((0, 400, "Z"), (400, 700, "offset"), (700, 900, "implicit"), (900, 1000, "Z"))

SERIES = (
    {
        "series_id": "temperature",
        "base_milli": -18000,
        "noise_amplitude_milli": 100,
        "drift_milli_total": -1800,
        "daily_profile_milli": [
            -350, -320, -280, -220, -120, 0, 140, 300, 440, 520, 560, 520,
            420, 280, 120, -40, -180, -300, -400, -460, -480, -460, -420, -380,
        ],
        "dropped_points": (240, 252),
    },
    {
        "series_id": "humidity",
        "base_milli": 85000,
        # 200 (not 600): a noise floor has to sit below both the daily cycle and the planted
        # anomalies or the benchmark claims truth the data cannot carry. At 600 the planted
        # humidity spikes (1800-2200 milli) were *under* the noise amplitude, so no detector at
        # the pinned k=3.5 could recover them (measured: max z = 2.77 at row 1694), and the
        # daily cycle (910 milli peak-to-peak) was only 1.5x the noise, which no period
        # estimator can find. assert_detectable() now enforces both floors.
        "noise_amplitude_milli": 200,
        "drift_milli_total": 2500,
        "daily_profile_milli": [
            420, 400, 360, 300, 200, 80, -60, -200, -320, -400, -440, -420,
            -340, -220, -80, 60, 200, 320, 400, 440, 460, 470, 460, 440,
        ],
        "dropped_points": (120, 132),
    },
    {
        "series_id": "energy_kwh",
        "base_milli": 4200,
        "noise_amplitude_milli": 120,
        "drift_milli_total": 800,
        "daily_profile_milli": [
            -900, -920, -940, -900, -800, -600, -300, 100, 500, 800, 950, 900,
            700, 400, 100, -100, -300, -500, -650, -750, -800, -850, -880, -900,
        ],
        "dropped_points": (330, 344),
    },
)

VARIANCE_MULT_MILLI = 4500  # noise x4.5 inside a variance-shift segment

# Planted anomalies: (type, (first_index, last_index), magnitude_milli). Layout
# guarantees: every family >= 2 segments in the dataset, segments on rolling-window
# boundaries at both edges, and merge probes on each side of max_gap_ms (25 and 35 min).
SEGMENTS = {
    "temperature": (
        ("spike", (6, 6), 5000),  # window boundary: left edge
        ("spike", (150, 152), 3500),
        ("level_shift", (300, 340), 900),
        ("spike", (400, 400), 3600),
        ("spike", (405, 405), 3600),  # merge probe A: 25 min apart (< max_gap_ms)
        ("variance_shift", (430, 470), VARIANCE_MULT_MILLI),
        ("spike", (505, 505), 3600),
        ("spike", (512, 512), 3600),  # merge probe B: 35 min apart (> max_gap_ms)
        ("missing_run", (560, 566), 0),
        ("zero_run", (620, 628), 0),
        ("level_shift", (700, 725), -1200),
        ("variance_shift", (800, 840), VARIANCE_MULT_MILLI),
        ("spike", (996, 996), 4500),  # window boundary: right edge
    ),
    "humidity": (
        ("spike", (12, 12), 1800),  # window boundary
        ("spike", (220, 220), 2200),
        ("level_shift", (350, 380), -2200),
        ("spike", (440, 440), 1900),
        ("spike", (445, 445), 1900),  # merge probe A: 25 min
        ("variance_shift", (500, 540), VARIANCE_MULT_MILLI),
        ("spike", (570, 570), 1900),
        ("spike", (577, 577), 1900),  # merge probe B: 35 min
        ("missing_run", (600, 606), 0),
        ("zero_run", (660, 668), 0),
        ("variance_shift", (740, 780), VARIANCE_MULT_MILLI),
        ("spike", (905, 906), 2100),
        ("spike", (998, 998), 2100),  # window boundary
    ),
    "energy_kwh": (
        ("spike", (21, 21), 2500),  # window boundary
        ("spike", (260, 261), 3000),
        ("level_shift", (420, 450), 1100),
        ("spike", (490, 490), 2600),
        ("spike", (495, 495), 2600),  # merge probe A: 25 min
        ("variance_shift", (580, 620), VARIANCE_MULT_MILLI),
        ("spike", (650, 650), 2600),
        ("spike", (657, 657), 2600),  # merge probe B: 35 min
        ("missing_run", (700, 706), 0),
        ("zero_run", (760, 768), 0),
        ("level_shift", (860, 890), -1300),
        ("variance_shift", (900, 940), VARIANCE_MULT_MILLI),
        ("spike", (995, 995), 2700),  # window boundary
    ),
}

# The one tolerated duplicate timestamp: a re-transmitted reading on the same instant.
# It doubles as the tie sample (two rows of one series share a timestamp, so ordering
# needs the row-number tie-break) and stays within `duplicate_timestamp_max`, so the
# frozen CSV remains profileable while the error code is exercised by negative fixtures.
DUPLICATE_AT = {"series_id": "temperature", "grid_index": 100, "value_delta_milli": 20}

MERGE_PROBES = (
    ("temperature", 400, 405),
    ("temperature", 505, 512),
    ("humidity", 440, 445),
    ("humidity", 570, 577),
    ("energy_kwh", 490, 495),
    ("energy_kwh", 650, 657),
)

SERIES_IDS = tuple(spec["series_id"] for spec in SERIES)

ARTIFACT_PATHS = (
    "data/synthetic/series.csv",
    "data/synthetic/manifest.json",
    "data/truth/truth.json",
    "data/truth/hash.txt",
)

_MAGNITUDE_KIND = {
    "variance_shift": "noise_scale_milli",
    "missing_run": "value_replacement",
    "zero_run": "value_replacement",
}
_DEFAULT_MAGNITUDE_KIND = "additive_milli"


class SplitMix64(object):
    """Self-contained splitmix64: 64-bit integer state, no stdlib `random` anywhere."""

    __slots__ = ("state",)

    _MASK = (1 << 64) - 1
    _GAMMA = 0x9E3779B97F4A7C15
    _MIX1 = 0xBF58476D1CE4E5B9
    _MIX2 = 0x94D049BB133111EB
    _TWO_POW_53 = 9007199254740992.0

    def __init__(self, seed):
        self.state = int(seed) & self._MASK

    def next_u64(self):
        self.state = (self.state + self._GAMMA) & self._MASK
        z = self.state
        z = ((z ^ (z >> 30)) * self._MIX1) & self._MASK
        z = ((z ^ (z >> 27)) * self._MIX2) & self._MASK
        return (z ^ (z >> 31)) & self._MASK

    def next_unit(self):
        """A uniform float in [0, 1): exact, because both steps are exact in binary64."""
        return (self.next_u64() >> 11) * (1.0 / self._TWO_POW_53)


def _series_seed(master_seed, series_position):
    return (int(master_seed) + (series_position + 1) * SplitMix64._GAMMA) & SplitMix64._MASK


def _daily_milli(profile_milli, phase_min):
    """Linear interpolation over the 24-hour profile table (pure arithmetic, no `sin`)."""
    hour = phase_min // 60
    frac = phase_min % 60
    low = profile_milli[hour]
    high = profile_milli[(hour + 1) % 24]
    return (low * (60 - frac) + high * frac) / 60.0


def _base_milli(series_spec, index, noise, spread_milli):
    """Value in 1/1000 units for one grid index, before the segment overlay."""
    phase_min = (index * (CADENCE_MS // 60000)) % PERIOD_MINUTES
    daily = _daily_milli(series_spec["daily_profile_milli"], phase_min)
    drift = series_spec["drift_milli_total"] * index / float(N_GRID_POINTS)
    noisy = noise * series_spec["noise_amplitude_milli"] * (spread_milli / float(MILLI))
    return series_spec["base_milli"] + daily + drift + noisy


def _segment_overlay(series_id):
    overlay = {}
    for kind, (first, last), magnitude in SEGMENTS[series_id]:
        for index in range(first, last + 1):
            if index in overlay:
                raise AssertionError("overlapping planted segments at index %d" % index)
            overlay[index] = (kind, magnitude)
    return overlay


def _collapse_segments(overlay):
    """Collapse the per-index overlay back into maximal same-kind runs (the truth rows)."""
    segments = []
    indices = sorted(overlay)
    position = 0
    while position < len(indices):
        first = indices[position]
        kind, magnitude = overlay[first]
        last = first
        position += 1
        while (
            position < len(indices)
            and indices[position] == last + 1
            and overlay[indices[position]][0] == kind
            and overlay[indices[position]][1] == magnitude
        ):
            last = indices[position]
            position += 1
        segments.append({"type": kind, "first": first, "last": last, "magnitude_milli": magnitude})
    return segments


def build_series_rows(seed):
    """Generate every series' grid rows, the dropped indices and the planted segments."""
    rows_by_series = {}
    dropped_by_series = {}
    segments_by_series = {}

    for position, series_spec in enumerate(SERIES):
        series_id = series_spec["series_id"]
        rng = SplitMix64(_series_seed(seed, position))
        overlay = _segment_overlay(series_id)
        first_drop, last_drop = series_spec["dropped_points"]
        dropped = set(range(first_drop, last_drop + 1))
        clash = sorted(set(overlay) & dropped)
        if clash:
            raise AssertionError("planted segment overlaps a dropped gap at %r" % (clash,))

        rows = []
        for index in range(N_GRID_POINTS):
            # Two draws per index, unconditionally: the stream position never depends on
            # whether this index sits inside a planted segment.
            noise = (rng.next_unit() - 0.5) * 2.0
            rng.next_unit()
            kind, magnitude = overlay.get(index, (None, 0))

            if kind == "missing_run":
                value = None
            elif kind == "zero_run":
                value = 0
            else:
                spread_milli = magnitude if kind == "variance_shift" else MILLI
                milli = _base_milli(series_spec, index, noise, spread_milli)
                if kind == "spike" or kind == "level_shift":
                    milli += magnitude
                value = canon.quantize(milli / float(MILLI), VALUE_DECIMALS)

            if index not in dropped:
                rows.append((index, START_MS + index * CADENCE_MS, value, 0))

        rows_by_series[series_id] = rows
        dropped_by_series[series_id] = sorted(dropped)
        segments_by_series[series_id] = _collapse_segments(overlay)

    _insert_duplicate_timestamp(rows_by_series)
    return rows_by_series, dropped_by_series, segments_by_series


def _insert_duplicate_timestamp(rows_by_series):
    rows = rows_by_series[DUPLICATE_AT["series_id"]]
    target = DUPLICATE_AT["grid_index"]
    for position, row in enumerate(rows):
        if row[0] == target:
            value = row[2]
            if value is not None:
                value += DUPLICATE_AT["value_delta_milli"]
            rows.insert(position + 1, (target, row[1], value, 1))
            return
    raise AssertionError("duplicate-timestamp anchor index %d was dropped" % target)


def format_timestamp(epoch_ms, grid_index):
    """One of the four legal representations for a UTC instant (_REPRESENTATION_BLOCKS)."""
    form = "Z"
    for first, last, block_form in _REPRESENTATION_BLOCKS:
        if first <= grid_index < last:
            form = block_form
            break
    if form == "offset":
        local_iso = epoch_ms_to_iso(epoch_ms + TZ_OFFSET_FOR_LOCAL_BLOCK * 60000)
        return local_iso[:-1] + "+08:00"
    if form == "implicit":
        return epoch_ms_to_iso(epoch_ms)[:-1].replace("T", " ")
    return epoch_ms_to_iso(epoch_ms)


def format_value(quantized):
    if quantized is None:
        return ""
    return canon.fixed_to_str(quantized, VALUE_DECIMALS)


def assemble(rows_by_series):
    """Interleave the series into one long table and number its physical lines."""
    rank = {series_id: position for position, series_id in enumerate(SERIES_IDS)}
    table = []
    for series_id in SERIES_IDS:
        for grid_index, epoch_ms, value, duplicate_flag in rows_by_series[series_id]:
            table.append((epoch_ms, rank[series_id], grid_index, duplicate_flag, series_id, value))
    table.sort(key=lambda item: (item[0], item[1], item[2], item[3]))

    lines = ["timestamp,series_id,value"]
    row_no_by_key = {}
    for position, (_ms, _rank, grid_index, duplicate_flag, series_id, value) in enumerate(table):
        row_no = position + 2  # header is line 1
        lines.append(
            "%s,%s,%s" % (format_timestamp(_ms, grid_index), series_id, format_value(value))
        )
        row_no_by_key[(series_id, grid_index, duplicate_flag)] = row_no
    return "\n".join(lines) + "\n", row_no_by_key


def build_truth(rows_by_series, dropped_by_series, segments_by_series, row_no_by_key, seed):
    truth_segments = []
    for series_id in SERIES_IDS:
        for number, segment in enumerate(segments_by_series[series_id], start=1):
            first, last = segment["first"], segment["last"]
            truth_segments.append(
                {
                    "segment_id": "%s-S%03d" % (series_id, number),
                    "series_id": series_id,
                    "type": segment["type"],
                    "start_row": row_no_by_key[(series_id, first, 0)],
                    "end_row": row_no_by_key[(series_id, last, 0)],
                    "start_ms": START_MS + first * CADENCE_MS,
                    "end_ms": START_MS + last * CADENCE_MS,
                    "n_points": last - first + 1,
                    "magnitude_milli": segment["magnitude_milli"],
                    "magnitude_kind": _MAGNITUDE_KIND.get(segment["type"], _DEFAULT_MAGNITUDE_KIND),
                    "at_window_boundary": first < WINDOW_POINTS
                    or last + WINDOW_POINTS > N_GRID_POINTS,
                }
            )
    truth_segments.sort(key=lambda item: (item["series_id"], item["start_row"]))

    merge_probes = []
    for number, (series_id, first_index, second_index) in enumerate(MERGE_PROBES, start=1):
        separation = (second_index - first_index) * CADENCE_MS
        within = separation <= MAX_GAP_MS
        merge_probes.append(
            {
                "probe_id": "P%02d" % number,
                "series_id": series_id,
                "first_row": row_no_by_key[(series_id, first_index, 0)],
                "second_row": row_no_by_key[(series_id, second_index, 0)],
                "separation_ms": separation,
                "max_gap_ms": MAX_GAP_MS,
                "expected_merged": within,
                "side": "at_or_below_max_gap" if within else "above_max_gap",
            }
        )

    planted = {
        "duplicate_timestamps": [
            {
                "series_id": DUPLICATE_AT["series_id"],
                "epoch_ms": START_MS + DUPLICATE_AT["grid_index"] * CADENCE_MS,
                "row_nos": [
                    row_no_by_key[(DUPLICATE_AT["series_id"], DUPLICATE_AT["grid_index"], 0)],
                    row_no_by_key[(DUPLICATE_AT["series_id"], DUPLICATE_AT["grid_index"], 1)],
                ],
                "value_delta_milli": DUPLICATE_AT["value_delta_milli"],
            }
        ],
        "gaps": [],
        "missing_runs": [],
        "zero_runs": [],
    }
    for series_id in SERIES_IDS:
        dropped = dropped_by_series[series_id]
        if dropped:
            previous = dropped[0] - 1
            planted["gaps"].append(
                {
                    "series_id": series_id,
                    "prev_row": row_no_by_key[(series_id, previous, 0)],
                    "row_no": row_no_by_key[(series_id, dropped[-1] + 1, 0)],
                    "interval_ms": (dropped[-1] + 1 - previous) * CADENCE_MS,
                    "n_dropped_points": len(dropped),
                }
            )
    for segment in truth_segments:
        bucket = {"missing_run": "missing_runs", "zero_run": "zero_runs"}.get(segment["type"])
        if bucket:
            planted[bucket].append(
                {
                    "series_id": segment["series_id"],
                    "start_row": segment["start_row"],
                    "end_row": segment["end_row"],
                    "n_points": segment["n_points"],
                }
            )
    planted["gaps"].sort(key=lambda item: (item["series_id"], item["prev_row"]))

    return {
        "scenario": SCENARIO,
        "seed": seed,
        "cadence_ms": CADENCE_MS,
        "max_gap_ms": MAX_GAP_MS,
        "window_points": WINDOW_POINTS,
        "n_grid_points": N_GRID_POINTS,
        "start_epoch_ms": START_MS,
        "series": [
            {
                "series_id": spec["series_id"],
                "n_rows": len(rows_by_series[spec["series_id"]]),
                "n_grid_points": N_GRID_POINTS,
                "n_dropped_points": len(dropped_by_series[spec["series_id"]]),
                "base_milli": spec["base_milli"],
                "noise_amplitude_milli": spec["noise_amplitude_milli"],
                "drift_milli_total": spec["drift_milli_total"],
                "daily_profile_milli": list(spec["daily_profile_milli"]),
            }
            for spec in SERIES
        ],
        "segments": truth_segments,
        "merge_probes": merge_probes,
        "planted": planted,
    }


def anomaly_set(truth):
    """The truth anomaly set whose canonical-JSON digest goes into data/truth/hash.txt."""
    return {
        "scenario": truth["scenario"],
        "seed": truth["seed"],
        "cadence_ms": truth["cadence_ms"],
        "max_gap_ms": truth["max_gap_ms"],
        "window_points": truth["window_points"],
        "segments": truth["segments"],
    }


def assert_non_trivial(truth):
    """The truth must have discriminating power, or the benchmark is a green no-op."""
    counts = _count_by_type(truth["segments"])
    for family in ("spike", "level_shift", "variance_shift", "missing_run", "zero_run"):
        if counts.get(family, 0) < 2:
            raise AssertionError(
                "planted family %r has %d segment(s), need >= 2" % (family, counts.get(family, 0))
            )
    if not any(segment["at_window_boundary"] for segment in truth["segments"]):
        raise AssertionError("no planted segment sits on a rolling window boundary")
    sides = set(probe["side"] for probe in truth["merge_probes"])
    if sides != {"at_or_below_max_gap", "above_max_gap"}:
        raise AssertionError("merge probes must straddle max_gap_ms, got %r" % (sorted(sides),))
    if not truth["planted"]["duplicate_timestamps"]:
        raise AssertionError("no duplicate timestamp planted (tie-break would be untested)")
    for bucket in ("gaps", "missing_runs", "zero_runs"):
        if not truth["planted"][bucket]:
            raise AssertionError("nothing planted in %r" % (bucket,))


def _count_by_type(segments):
    counts = {}
    for segment in segments:
        counts[segment["type"]] = counts.get(segment["type"], 0) + 1
    return counts


# Detectability floors. Planted truth is only meaningful if the data can carry it: an additive
# magnitude under the noise amplitude yields a robust z under any usable threshold, and a daily
# cycle comparable to the noise cannot be located by a period estimator. The M1 fixture violated
# both for humidity (noise 600 milli: spikes 1800-2200 milli under the noise amplitude, cycle 910
# milli only 1.5x it), which is why these floors exist -- a count-only non-triviality check
# happily describes a benchmark whose own anomalies are unrecoverable.
MIN_MAGNITUDE_OVER_NOISE = 8
MIN_DAILY_OVER_NOISE = 3


def assert_detectable(truth):
    """Every additive segment must stand out of its noise, and so must the planted daily cycle."""
    noise = {spec["series_id"]: spec["noise_amplitude_milli"] for spec in SERIES}
    for spec in SERIES:
        profile = spec["daily_profile_milli"]
        floor = MIN_DAILY_OVER_NOISE * spec["noise_amplitude_milli"]
        swing = max(profile) - min(profile)
        if swing < floor:
            raise AssertionError(
                "series %r: daily cycle swing %d milli is under %d x its noise amplitude (%d)"
                % (spec["series_id"], swing, MIN_DAILY_OVER_NOISE, spec["noise_amplitude_milli"])
            )
    for segment in truth["segments"]:
        if segment["type"] not in ("spike", "level_shift"):
            continue
        amplitude = abs(segment["magnitude_milli"])
        spec_noise = noise[segment["series_id"]]
        floor = MIN_MAGNITUDE_OVER_NOISE * spec_noise
        if amplitude < floor:
            raise AssertionError(
                "segment %s (%s): magnitude %d milli is under %d x the noise amplitude of %r (%d)"
                % (
                    segment["segment_id"],
                    segment["type"],
                    segment["magnitude_milli"],
                    MIN_MAGNITUDE_OVER_NOISE,
                    segment["series_id"],
                    spec_noise,
                )
            )


def build_artifacts(seed):
    """Return {relative path: bytes} for every frozen artifact."""
    rows_by_series, dropped_by_series, segments_by_series = build_series_rows(seed)
    csv_text, row_no_by_key = assemble(rows_by_series)
    truth = build_truth(rows_by_series, dropped_by_series, segments_by_series, row_no_by_key, seed)
    assert_non_trivial(truth)
    assert_detectable(truth)

    csv_bytes = csv_text.encode("utf-8")
    truth_bytes = canon.canonical_json_bytes(truth)
    digest = canon.sha256_hex(canon.canonical_json_bytes(anomaly_set(truth)))
    hash_bytes = (digest + "\n").encode("utf-8")

    manifest = {
        "generator": "tools/gen_synthetic_series.py",
        "generator_version": GENERATOR_VERSION,
        "scenario": SCENARIO,
        "seed": seed,
        "params": {
            "n_grid_points": N_GRID_POINTS,
            "cadence_ms": CADENCE_MS,
            "period_minutes": PERIOD_MINUTES,
            "window_points": WINDOW_POINTS,
            "max_gap_ms": MAX_GAP_MS,
            "value_decimals": VALUE_DECIMALS,
            "start_epoch_ms": START_MS,
            "start_iso": epoch_ms_to_iso(START_MS),
            "variance_mult_milli": VARIANCE_MULT_MILLI,
            "series": [
                {
                    "series_id": spec["series_id"],
                    "base_milli": spec["base_milli"],
                    "noise_amplitude_milli": spec["noise_amplitude_milli"],
                    "drift_milli_total": spec["drift_milli_total"],
                    "daily_profile_milli": list(spec["daily_profile_milli"]),
                    "dropped_points": list(spec["dropped_points"]),
                }
                for spec in SERIES
            ],
        },
        "planted": {
            "segment_counts": _count_by_type(truth["segments"]),
            "n_merge_probes": len(truth["merge_probes"]),
            "n_gaps": len(truth["planted"]["gaps"]),
            "n_missing_runs": len(truth["planted"]["missing_runs"]),
            "n_zero_runs": len(truth["planted"]["zero_runs"]),
            "n_duplicate_timestamps": len(truth["planted"]["duplicate_timestamps"]),
        },
        # Ledger of the other artifacts. manifest.json cannot appear in its own ledger
        # (its hash would depend on itself); `--check` covers it by regenerating.
        "artifacts": [
            {"path": "data/synthetic/series.csv", "sha256": canon.sha256_hex(csv_bytes), "size_bytes": len(csv_bytes)},
            {"path": "data/truth/truth.json", "sha256": canon.sha256_hex(truth_bytes), "size_bytes": len(truth_bytes)},
            {"path": "data/truth/hash.txt", "sha256": canon.sha256_hex(hash_bytes), "size_bytes": len(hash_bytes)},
        ],
        "truth_sha256": digest,
    }
    return {
        "data/synthetic/series.csv": csv_bytes,
        "data/synthetic/manifest.json": canon.canonical_json_bytes(manifest),
        "data/truth/truth.json": truth_bytes,
        "data/truth/hash.txt": hash_bytes,
    }


def write_artifacts(root, artifacts):
    for relative in sorted(artifacts):
        target = os.path.join(root, relative.replace("/", os.sep))
        directory = os.path.dirname(target)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(target, "wb") as handle:
            handle.write(artifacts[relative])


def read_bytes(path):
    with io.open(path, "rb") as handle:
        return handle.read()


def cmd_generate(root, seed):
    artifacts = build_artifacts(seed)
    write_artifacts(root, artifacts)
    print("wrote %d artifacts (seed=%d) under %s" % (len(artifacts), seed, root))
    for relative in ARTIFACT_PATHS:
        print("  %s  %s" % (canon.sha256_hex(artifacts[relative]), relative))
    return 0


def cmd_check(root, seed):
    """Verify the frozen artifacts: manifest ledger first, then a fresh regeneration."""
    manifest_path = os.path.join(root, "data", "synthetic", "manifest.json")
    if not os.path.isfile(manifest_path):
        print("error: frozen manifest is missing: %s" % manifest_path, file=sys.stderr)
        return 2

    problems = []
    try:
        manifest = json.loads(read_bytes(manifest_path).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        print("error: frozen manifest is not readable JSON: %s" % (exc,), file=sys.stderr)
        return 2

    for entry in manifest.get("artifacts", []):
        path = os.path.join(root, entry["path"].replace("/", os.sep))
        if not os.path.isfile(path):
            problems.append("missing frozen artifact: %s" % entry["path"])
            continue
        actual = canon.sha256_hex(read_bytes(path))
        if actual != entry["sha256"]:
            problems.append(
                "tampered frozen artifact: %s (ledger %s, actual %s)"
                % (entry["path"], entry["sha256"][:16], actual[:16])
            )

    hash_path = os.path.join(root, "data", "truth", "hash.txt")
    if os.path.isfile(hash_path):
        recorded = read_bytes(hash_path).decode("utf-8").strip()
        if recorded != manifest.get("truth_sha256"):
            problems.append(
                "hash.txt does not match the manifest truth_sha256 (%s vs %s)"
                % (recorded[:16], str(manifest.get("truth_sha256"))[:16])
            )
    else:
        problems.append("missing frozen artifact: data/truth/hash.txt")

    if problems:
        for problem in problems:
            print("check failed: %s" % problem, file=sys.stderr)
        return 2

    temporary = tempfile.mkdtemp(prefix="zaa-gen-check-")
    try:
        write_artifacts(temporary, build_artifacts(seed))
        for relative in ARTIFACT_PATHS:
            frozen = read_bytes(os.path.join(root, relative.replace("/", os.sep)))
            fresh = read_bytes(os.path.join(temporary, relative.replace("/", os.sep)))
            if frozen != fresh:
                problems.append("regeneration differs from the frozen artifact: %s" % relative)
        if problems:
            for problem in problems:
                print("check failed: %s" % problem, file=sys.stderr)
            return 2
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    print(
        "check ok: %d frozen artifacts match the manifest ledger and regenerate bit-for-bit"
        % len(ARTIFACT_PATHS)
    )
    print("  truth sha256: %s" % manifest.get("truth_sha256"))
    return 0


def main(argv=None):
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="gen_synthetic_series.py",
        description="Generate the frozen synthetic cold-chain series, its planted truth and the manifest.",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="Explicit RNG seed (written into the manifest)."
    )
    parser.add_argument("--out-root", default=_REPO_ROOT, help="Repository root to write data/ under.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the frozen artifacts (ledger + bit-for-bit regeneration) instead of writing.",
    )
    args = parser.parse_args(argv)
    root = os.path.abspath(args.out_root)
    if args.check:
        return cmd_check(root, args.seed)
    return cmd_generate(root, args.seed)


if __name__ == "__main__":
    sys.exit(main())
