"""Four deterministic detectors (M2) + `detect` orchestration.

API:
  estimate_period(grid_by_series, spec) -> (period_points, per-series estimates)
  rolling_mad_z(values, window, k, min_valid) -> [(index, score)]
  rolling_iqr(values, window, iqr_mult, min_valid) -> [(index, score)]
  stl_resid_z(values, positions, period_points, inner, outer, window, k, min_valid)
  rules(values, spec) -> [(index, score, rule_name)]
  detect_all(parsed, spec) -> (run_document, anomaly_set)
  detect_all_detailed(parsed, spec) -> (run_document, anomaly_set, detections)
  cmd_detect(csv_path, spec_path, out_dir) -> int

Mirrorable arithmetic only (plan/02 3.2): + - * / floor ceil abs min max and comparisons; powers
are expanded into multiplication and no transcendental function appears anywhere -- the browser
mirror (M3) has to reproduce these same operations bit for bit, which is the whole point of the
project. Every reducer below is a hand-written loop rather than `sum`/`statistics`, so the
summation order is part of the specification instead of an implementation detail of a library.

Degenerate-window rules are stated explicitly instead of being left to arithmetic accidents:
  * MAD == 0 (more than half the window sits exactly on the median) falls back to the mean
    absolute deviation; a scale of 0 (a constant window) means the point cannot be judged at all
    and is not flagged. Dividing by zero to get an infinity and then comparing against `k` is
    exactly what this avoids.
  * The same fallback applies to a degenerate IQR (a box collapsed on one value).
  * A missing value is never a candidate: it is data (it feeds the missing-run rule), not a point
    to be scored, so no detector ever invents a value for it.

What a detector returns is a raw score per anomalous point. Detectors do not merge, order, name
or filter anything -- that is `episodes.py`'s single job (K6/K7).
"""

import json
import os
import sys

from . import canon, csvio, episodes as episodes_module
from .timebase import epoch_ms_to_iso

# Version of the detector arithmetic and the period estimator. Distinct from
# `canon.CANON_VERSION` (the hash rules): a change here changes the detections, a change there
# changes the bytes even for identical detections.
DETECTOR_VERSION = "1"

MAD_TO_SIGMA = 1.4826
MIN_VALID = 6  # window // 4: the smallest sample a scale estimate may be built from
DEFAULT_PERIOD_REJECT_WINDOW = 121
DEFAULT_PERIOD_REJECT_SIGMA = 2.5
DEFAULT_MAX_GAP_MS = 1800000  # 30 minutes (plan/06 P4)

# Relative floor below which a difference scale counts as "no short-term noise": 10^-quant_decimals
# of the series' own robust scale. Deliberately conservative -- it only catches series whose
# differences are constant to within binary rounding (a straight line), where a standardised jump
# would otherwise be invented out of the last digit.
DECIMAL_RESOLUTION_FRACTION = 0.000001

# Detector parameters, spelled out as (name, int|decimal) so that the resolved values and their
# on-disk (fixed-point string) form are produced from one table. `plan/06` P4 pins the defaults;
# tests/test_detect.py::TestDefaultsArePinned repeats them as literals so drifting one is a
# deliberate two-file edit (a test that reads its expectation out of the document it checks would
# agree with whatever the default became).
DETECTOR_PARAMS = (
    ("rolling_mad_z", (("window", "int"), ("k", "decimal"), ("min_valid", "int"))),
    ("rolling_iqr", (("window", "int"), ("iqr_mult", "decimal"), ("min_valid", "int"))),
    (
        "stl_resid_z",
        (("inner", "int"), ("outer", "int"), ("window", "int"), ("k", "decimal"), ("min_valid", "int")),
    ),
    (
        "rules",
        (
            ("static_threshold", "nullable-decimal"),
            ("pct_jump", "decimal"),
            ("missing_run", "int"),
            ("cusum_k", "decimal"),
            ("cusum_h", "decimal"),
        ),
    ),
)

RUN_PARAMS = (
    ("max_gap_ms", "int"),
    ("period_points", "nullable-int"),
    ("period_reject_window", "int"),
    ("period_reject_sigma", "decimal"),
)

DEFAULT_SPEC = {
    "rolling_mad_z": {"window": 24, "k": 3.5, "min_valid": MIN_VALID},
    "rolling_iqr": {"window": 24, "iqr_mult": 3.0, "min_valid": MIN_VALID},
    "stl_resid_z": {"inner": 2, "outer": 1, "window": 24, "k": 3.5, "min_valid": MIN_VALID},
    "rules": {
        "static_threshold": None,
        "pct_jump": 0.35,
        "missing_run": 6,
        "cusum_k": 0.5,
        "cusum_h": 5.0,
    },
    "max_gap_ms": DEFAULT_MAX_GAP_MS,
    "period_points": None,
    "period_reject_window": DEFAULT_PERIOD_REJECT_WINDOW,
    "period_reject_sigma": DEFAULT_PERIOD_REJECT_SIGMA,
}

# Which rule each `rules` detection belongs to, so an episode can name what fired.
RULE_NAMES = ("static_threshold", "pct_jump", "missing_run", "zero_run", "cusum")


def _type_table():
    table = {}
    for name, params in DETECTOR_PARAMS:
        for param, kind in params:
            table[(name, param)] = kind
    for param, kind in RUN_PARAMS:
        table[(None, param)] = kind
    return table


PARAM_TYPES = _type_table()


def _coerce(value, kind, label):
    """Coerce one spec value to its declared kind; reject silent nonsense loudly."""
    if kind in ("decimal", "nullable-decimal"):
        if value is None:
            if kind == "nullable-decimal":
                return None
            raise ValueError("%s must be a number, not null" % label)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                raise ValueError("%s must be a number, got %r" % (label, value))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("%s must be a number, got %r" % (label, value))
        return float(value)
    if kind in ("int", "nullable-int"):
        if value is None:
            if kind == "nullable-int":
                return None
            raise ValueError("%s must be an integer, not null" % label)
        if isinstance(value, str):
            value = float(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("%s must be an integer, got %r" % (label, value))
        if float(value) != int(value):
            raise ValueError("%s must be a whole number, got %r" % (label, value))
        return int(value)
    raise KeyError("unknown parameter kind %r" % (kind,))


def resolve_spec(spec=None):
    """Merge a caller spec over the defaults and coerce every value to its declared kind.

    The CSV-contract parameters travel in the same object (they are part of the run-spec the
    archive is fingerprinted against) but are resolved by `csvio.resolve_spec`, so their
    defaults live in exactly one place.
    """
    resolved = {}
    for name, _params in DETECTOR_PARAMS:
        resolved[name] = dict(DEFAULT_SPEC[name])
    for param, _kind in RUN_PARAMS:
        resolved[param] = DEFAULT_SPEC[param]
    resolved.update(csvio.resolve_spec())

    if spec:
        unknown = sorted(set(spec) - set(resolved))
        if unknown:
            raise KeyError("unknown run-spec key(s): %s" % ", ".join(unknown))
        for key, value in spec.items():
            if isinstance(resolved[key], dict):
                if not isinstance(value, dict):
                    raise ValueError("run-spec %r must be an object" % (key,))
                extra = sorted(set(value) - set(resolved[key]))
                if extra:
                    raise KeyError("unknown %s parameter(s): %s" % (key, ", ".join(extra)))
                resolved[key].update(value)
            else:
                resolved[key] = value

    for name, params in DETECTOR_PARAMS:
        for param, kind in params:
            resolved[name][param] = _coerce(resolved[name][param], kind, "%s.%s" % (name, param))
    for param, kind in RUN_PARAMS:
        resolved[param] = _coerce(resolved[param], kind, param)
    return resolved


def dump_spec(resolved):
    """The on-disk (canonical) form of a resolved spec: integers, and decimals as fixed strings.

    Producing this from the resolved values -- rather than serialising the floats -- is what keeps
    run.json and the hashed anomaly set from being two representations of the same parameter that
    can drift (K2/K3/K8).
    """
    document = {}
    for name, params in DETECTOR_PARAMS:
        block = {}
        for param, kind in params:
            block[param] = _dump_value(resolved[name][param], kind)
        document[name] = block
    for param, kind in RUN_PARAMS:
        document[param] = _dump_value(resolved[param], kind)
    for param in csvio.DEFAULT_SPEC:
        document[param] = resolved[param]
    return document


def _dump_value(value, kind):
    if value is None:
        return None
    if kind in ("decimal", "nullable-decimal"):
        return canon.fixed_to_str(canon.quantize(value, _QUANT_DECIMALS), _QUANT_DECIMALS)
    return int(value)


_QUANT_DECIMALS = 6


def csv_spec(resolved):
    """The subset of a resolved spec that the CSV parser accepts."""
    return {key: resolved[key] for key in csvio.DEFAULT_SPEC if key in resolved}


# ---------------------------------------------------------------------------
# Numeric primitives (explicit loops: the operation sequence is the specification)
# ---------------------------------------------------------------------------


def _median(values):
    """Median with linear interpolation between the two middle values (no `statistics`)."""
    if not values:
        raise ValueError("median of an empty window")
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    position = 0.5 * (n - 1)
    low = int(position)
    high = low + 1
    if high >= n:
        return ordered[-1]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _quantile(values, fraction):
    """Linear-interpolation quantile over an unsorted list (single definition point)."""
    if not values:
        raise ValueError("quantile of an empty window")
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    position = fraction * (n - 1)
    low = int(position)
    high = low + 1
    if high >= n:
        return ordered[-1]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _mean(values):
    total = 0.0
    for value in values:
        total += value
    return total / float(len(values))


def _mad(values, median_value):
    """Median absolute deviation from a supplied median."""
    deviations = []
    for value in values:
        deviations.append(abs(value - median_value))
    return _median(deviations)


def _mean_abs_deviation(values, median_value):
    total = 0.0
    for value in values:
        total += abs(value - median_value)
    return total / float(len(values))


def robust_scale(values):
    """The window's scale in sigma units, with the degenerate-MAD fallback spelled out.

    `mad == 0` means more than half the window sits exactly on the median, so the MAD carries no
    scale information; the mean absolute deviation still does (a spike against a flat window
    remains a spike). A scale of 0 means every window value is identical and no point can be
    judged against it -- returned as 0 so callers skip the point instead of dividing by zero.
    """
    median_value = _median(values)
    mad = _mad(values, median_value)
    if mad > 0:
        return MAD_TO_SIGMA * mad, median_value
    return MAD_TO_SIGMA * _mean_abs_deviation(values, median_value), median_value


def _window(values, index, window):
    """The valid values of the trailing window `[index-window+1, index]` (inclusive)."""
    low = index - window + 1
    if low < 0:
        low = 0
    found = []
    for position in range(low, index + 1):
        value = values[position]
        if value is not None:
            found.append(value)
    return found


def _robust_z(window_values, target):
    """|x - median| / scale of one window, or 0 when the window cannot judge the point."""
    scale, median_value = robust_scale(window_values)
    if scale == 0:
        return 0.0
    return abs(target - median_value) / scale


# ---------------------------------------------------------------------------
# Detector 1: rolling median + MAD
# ---------------------------------------------------------------------------


def rolling_mad_z(values, window, k, min_valid):
    """Rolling median/MAD robust z; flags |z| > k. The window includes the scored point.

    Including the point keeps the window a plain trailing slice (one pass, trivially mirrored).
    A handful of extreme values cannot move a median or a median-of-deviations, so a spike does
    not mask its own detection, and a flagged point does not raise the scale for the next window.
    """
    hits = []
    for index in range(len(values)):
        target = values[index]
        if target is None:
            continue
        window_values = _window(values, index, window)
        if len(window_values) < min_valid:
            continue
        score = _robust_z(window_values, target)
        if score > k:
            hits.append((index, score))
    return hits


# ---------------------------------------------------------------------------
# Detector 2: rolling interquartile range
# ---------------------------------------------------------------------------


def rolling_iqr(values, window, iqr_mult, min_valid):
    """Rolling box bounds `[Q1 - m*IQR, Q3 + m*IQR]`; flags excursions, scores in IQR units."""
    hits = []
    for index in range(len(values)):
        target = values[index]
        if target is None:
            continue
        window_values = _window(values, index, window)
        if len(window_values) < min_valid:
            continue
        q1 = _quantile(window_values, 0.25)
        q3 = _quantile(window_values, 0.75)
        iqr = q3 - q1
        if iqr > 0:
            low = q1 - iqr_mult * iqr
            high = q3 + iqr_mult * iqr
            scale = iqr
        else:
            # Degenerate box: the same explicit fallback the MAD path uses, so a spike against a
            # flat window is still flagged and the score stays finite.
            median_value = _median(window_values)
            scale = _mean_abs_deviation(window_values, median_value)
            if scale == 0:
                continue
            low = median_value - iqr_mult * scale
            high = median_value + iqr_mult * scale
        if target > high:
            hits.append((index, (target - high) / scale))
        elif target < low:
            hits.append((index, (low - target) / scale))
    return hits


# ---------------------------------------------------------------------------
# Detector 3: STL residual z (self-implemented classic decomposition, no statsmodels)
# ---------------------------------------------------------------------------


def _next_odd(value):
    """Smallest odd integer >= value (LOESS windows are symmetric around their centre)."""
    value = int(value)
    if value < 1:
        return 1
    return value if value % 2 else value + 1


def _tricube_table(dmax):
    """Tricube weights `(1 - d^3)^3` for every integer distance up to `dmax`."""
    table = []
    for distance in range(dmax + 1):
        if dmax > 0:
            ratio = distance / float(dmax)
        else:
            ratio = 0.0
        tricube = 1.0 - ratio * ratio * ratio
        table.append(tricube * tricube * tricube)
    return table


def _loess(values, window, weights=None):
    """Locally-weighted linear fit (tricube weights), evaluated at every position.

    `window` counts positions, not present values: missing samples shrink the effective sample
    without moving the window centre. The fitted x is measured from the target position, so the
    local design matrix stays well conditioned for a series of any length and the value at the
    target is the intercept alone.

    Tricube weights depend only on |target - position|, and the window radius is the same for
    every target of a series at least `window` long, so one weight table per distinct radius
    serves the whole call -- the inner loop then does one list index per element instead of a
    division, a multiplication and two `abs` calls (this loop is the detector pipeline's hot
    spot: the trend window spans 1.5 periods).
    """
    n = len(values)
    half = window // 2
    tables = {}
    fitted = [None] * n
    for index in range(n):
        if values[index] is None:
            continue
        low = index - half
        if low < 0:
            low = 0
        high = index + half
        if high > n - 1:
            high = n - 1
        if high == low:
            fitted[index] = values[index]
            continue
        dmax = max(index - low, high - index)
        table = tables.get(dmax)
        if table is None:
            table = _tricube_table(dmax)
            tables[dmax] = table
        sw = 0.0
        swx = 0.0
        swy = 0.0
        swxx = 0.0
        swxy = 0.0
        for position in range(low, high + 1):
            value = values[position]
            if value is None:
                continue
            offset = position - index
            if offset < 0:
                weight = table[-offset]
            else:
                weight = table[offset]
            if weights is not None:
                weight = weight * weights[position]
            x = float(offset)
            sw += weight
            swx += weight * x
            swy += weight * value
            swxx += weight * x * x
            swxy += weight * x * value
        if sw == 0:
            continue
        determinant = sw * swxx - swx * swx
        if determinant == 0:
            fitted[index] = swy / sw
        else:
            slope = (sw * swxy - swx * swy) / determinant
            intercept = (swy - slope * swx) / sw
            fitted[index] = intercept
    return fitted


def _seasonal_curve(detrended, positions, period_points, weights, window):
    """Cyclic seasonal curve: weighted phase means, smoothed along the phase axis.

    Phases come from the *grid* index, not the list position: a dropped sample shifts every later
    position by one, so folding on positions would smear the cycle (the fixture drops 13-15
    consecutive samples per series). The phase axis is tripled before smoothing and the middle
    copy is kept, which makes the smoothing cyclic -- a one-sided window at the ends would leave a
    visible seam at the cycle wrap.
    """
    totals = [0.0] * period_points
    counts = [0.0] * period_points
    for index in range(len(detrended)):
        value = detrended[index]
        if value is None:
            continue
        phase = positions[index] % period_points
        weight = weights[index] if weights is not None else 1.0
        totals[phase] += weight * value
        counts[phase] += weight
    phase_means = []
    for phase in range(period_points):
        if counts[phase] > 0:
            phase_means.append(totals[phase] / counts[phase])
        else:
            phase_means.append(0.0)

    tripled = phase_means + phase_means + phase_means
    smoothed = _loess(tripled, window)
    middle = smoothed[period_points : 2 * period_points]
    return [
        (middle[phase] if middle[phase] is not None else phase_means[phase])
        for phase in range(period_points)
    ]


def _bisquare_weights(residual):
    """Bisquare robustness weights `(1 - u^2)^2` from the residual (pure multiplication)."""
    deviations = []
    for value in residual:
        if value is not None:
            deviations.append(abs(value))
    if not deviations:
        return [1.0] * len(residual)
    scale = 6.0 * _median(deviations)
    weights = []
    for value in residual:
        if value is None or scale == 0:
            weights.append(1.0)
            continue
        ratio = abs(value) / scale
        if ratio >= 1.0:
            weights.append(0.0)
        else:
            factor = 1.0 - ratio * ratio
            weights.append(factor * factor)
    return weights


def stl_residual(values, positions, period_points, inner, outer):
    """Trend + seasonal decomposition; returns the residual (None where a value is missing).

    Structurally the classic STL inner/outer loop: `inner` seasonal/trend refinements per pass,
    `outer` robustness passes on top of the initial fit. `period_points <= 1` means "no seasonal
    component" (the seasonal term is the series mean, i.e. only the trend is removed) -- the
    documented outcome when a series is too short to carry a cycle.
    """
    n = len(values)
    if period_points <= 1:
        present = [value for value in values if value is not None]
        seasonal_value = _mean(present) if present else 0.0
        detrended = [(value - seasonal_value) if value is not None else None for value in values]
        trend = _loess(detrended, _next_odd(max(3, min(n, 24))))
        return [
            (detrended[i] - trend[i]) if (detrended[i] is not None and trend[i] is not None) else None
            for i in range(n)
        ]

    trend_window = _next_odd(3 * period_points // 2)
    seasonal_window = _next_odd(period_points // 3)
    weights = [1.0] * n
    trend = _loess(values, trend_window)
    seasonal = [0.0] * n
    residual = list(values)
    for _pass in range(outer + 1):
        for _iteration in range(inner):
            detrended = [
                (values[i] - trend[i]) if (values[i] is not None and trend[i] is not None) else None
                for i in range(n)
            ]
            curve = _seasonal_curve(detrended, positions, period_points, weights, seasonal_window)
            seasonal = [curve[positions[i] % period_points] for i in range(n)]
            deseasonalized = [
                (values[i] - seasonal[i]) if values[i] is not None else None for i in range(n)
            ]
            trend = _loess(deseasonalized, trend_window, weights)
        residual = [
            (values[i] - trend[i] - seasonal[i])
            if (values[i] is not None and trend[i] is not None)
            else None
            for i in range(n)
        ]
        weights = _bisquare_weights(residual)
    return residual


def stl_resid_z(values, positions, period_points, inner, outer, window, k, min_valid):
    """STL residual scored by the same rolling median/MAD z (one implementation, not a copy)."""
    residual = stl_residual(values, positions, period_points, inner, outer)
    return rolling_mad_z(residual, window, k, min_valid)


# ---------------------------------------------------------------------------
# Detector 4: rules (threshold / percentage jump / missing+zero runs / CUSUM)
# ---------------------------------------------------------------------------


def rules(values, spec):
    """Rule detectors, each returning `(index, score, rule_name)`.

    Missing and zero runs are treated as findings, not as gaps to skip over: a run of absent
    samples is exactly the kind of event the archive exists to record, and its length is its
    score. The percentage-jump rule needs a non-zero predecessor: with a zero baseline the
    relative change is undefined, so the rule stays silent there and the zero-run rule owns that
    case (stated in data/README 4.1 instead of silently substituting a value).
    """
    hits = []
    static_threshold = spec["static_threshold"]
    if static_threshold is not None:
        for index, value in enumerate(values):
            if value is None:
                continue
            if abs(value) > static_threshold:
                hits.append((index, abs(value) - static_threshold, "static_threshold"))

    pct_jump = spec["pct_jump"]
    for index in range(1, len(values)):
        previous = values[index - 1]
        current = values[index]
        if previous is None or current is None or previous == 0:
            continue
        ratio = current / previous
        jump = ratio - 1.0
        if jump < 0:
            jump = -jump
        if jump > pct_jump:
            hits.append((index, jump, "pct_jump"))

    _run_hits(values, spec["missing_run"], True, hits)
    _run_hits(values, spec["missing_run"], False, hits)
    _cusum_hits(values, spec["cusum_k"], spec["cusum_h"], hits)
    return hits


def _run_hits(values, minimum, missing, hits):
    """Consecutive runs of missing (or zero) values at least `minimum` long."""
    start = None
    for index in range(len(values) + 1):
        inside = index < len(values) and (
            values[index] is None if missing else values[index] == 0.0
        )
        if inside and start is None:
            start = index
        elif not inside and start is not None:
            length = index - start
            if length >= minimum:
                name = "missing_run" if missing else "zero_run"
                for position in range(start, index):
                    hits.append((position, float(length), name))
            start = None


def _cusum_hits(values, cusum_k, cusum_h, hits):
    """Two-sided CUSUM over consecutive differences, scaled by the differences' robust scale.

    Working on differences is what makes the rule independent of the daily cycle and the drift: a
    level shift enters as one jump (and leaves as another), a spike is two jumps, while a slow cycle
    contributes almost nothing per step. Only valid neighbours contribute - a missing sample neither
    advances nor resets the accumulator. The scale is global rather than rolling because the
    accumulator is itself the smoothing; one series has one difference scale. Both accumulators
    restart on an alarm (the classic CUSUM restart policy): without it a single excursion keeps
    re-alarming for as long as it takes to decay, which reports one event as a long run.

    A difference scale at the input's decimal resolution means the series has no short-term noise at
    all (a straight line, a constant): standardising by it would turn the last binary digit into an
    "astronomically significant" jump, so a perfectly linear ramp would alarm. There is nothing to
    detect there, so the rule stands down.
    """
    differences = []
    for index in range(1, len(values)):
        previous = values[index - 1]
        current = values[index]
        if previous is None or current is None:
            continue
        differences.append((index, current - previous))
    if not differences:
        return
    scale_values = [difference for _index, difference in differences]
    scale, _median_value = robust_scale(scale_values)
    present = [value for value in values if value is not None]
    reference = robust_scale(present)[0] if present else 0.0
    if scale == 0 or scale < DECIMAL_RESOLUTION_FRACTION * reference:
        return
    positive = 0.0
    negative = 0.0
    for index, difference in differences:
        standardized = difference / scale
        positive += standardized - cusum_k
        if positive < 0.0:
            positive = 0.0
        negative += -standardized - cusum_k
        if negative < 0.0:
            negative = 0.0
        score = positive if positive > negative else negative
        if score > cusum_h:
            hits.append((index, score, "cusum"))
            positive = 0.0
            negative = 0.0


# ---------------------------------------------------------------------------
# Period estimation (ACF on a cleaned grid; the resolved value is what a recomputation consumes)
# ---------------------------------------------------------------------------


def dominant_interval(stamps):
    """The most frequent positive gap, shortest interval on a tie (the sampling grid)."""
    counts = {}
    for index in range(1, len(stamps)):
        delta = stamps[index] - stamps[index - 1]
        if delta > 0:
            counts[delta] = counts.get(delta, 0) + 1
    if not counts:
        return None
    return sorted(counts, key=lambda delta: (-counts[delta], delta))[0]


def to_grid(stamps, values, cadence):
    """Place samples on the sampling grid reconstructed from the timestamps.

    Rebuilding the grid from the time axis (rather than trusting list order) is what keeps the
    cycle's phase intact across dropped samples; a duplicate timestamp keeps one value per cell.
    """
    start = stamps[0]
    cells = (stamps[-1] - start) // cadence
    grid = [None] * (cells + 1)
    for stamp, value in zip(stamps, values):
        grid[(stamp - start) // cadence] = value
    return grid


def estimate_series_period(grid, reject_window, reject_sigma):
    """Robust period estimate for one grid, or None when the grid cannot carry one.

    The estimator has to survive the very anomalies the detectors look for. Measured on the frozen
    fixture, a plain ACF of the raw series peaks anywhere from lag 2 to lag 302 instead of 288: the
    planted zero run alone carries 78% of the variance at one point, and a 26-41 point level shift
    adds a broad ramp over the first 41 lags. So the ACF runs on a *cleaned* grid:

      1. residual against a centred running median (window > twice the longest run to reject, so
         such a run stays a minority inside every window);
      2. delete -- not replace -- the cells whose residual exceeds `reject_sigma` robust sigmas.
         Deletion is the honest move: a rejected cell says "no usable sample here", which is what
         the ACF's pairwise handling already understands, whereas a replacement would invent a
         value and still leave the run's structure in place;
      3. remove a least-squares line (a smooth trend is not periodic and would swamp the daily
         cycle, which carries far less variance than the drift), then winsorise at three robust
         sigmas so a surviving maverick cannot dominate;
      4. pairwise autocorrelation over the grid, searched for the strongest local maximum in
         `[max(8, n/16), n/3]` -- the lower bound keeps short-lag anomaly structure out of the
         answer, the upper bound demands at least three observable cycles -- then reduced to the
         fundamental when a divisor explains at least 80% as much (a clean cycle peaks at every
         multiple of its period).
    """
    present = [value for value in grid if value is not None]
    n = len(present)
    if n < 24:
        return None
    high = n // 3
    low = max(8, n // 16)
    if high <= low:
        return None

    trend = _median_trend(grid, reject_window)
    residual = [
        (grid[i] - trend[i]) if (grid[i] is not None and trend[i] is not None) else None
        for i in range(len(grid))
    ]
    residual_values = [value for value in residual if value is not None]
    if not residual_values:
        return None
    scale, _median_value = robust_scale(residual_values)
    if scale == 0:
        return None
    pruned = []
    for index, value in enumerate(residual):
        if value is not None and abs(value) > reject_sigma * scale:
            pruned.append(None)
        else:
            pruned.append(grid[index])
    z = _standardized_series(pruned)
    if not any(value is not None for value in z):
        return None
    # One extra lag so the local-maximum test at `high` has a right-hand neighbour to compare with.
    correlations = _autocorrelation(z, high + 1)
    best = None
    for lag in range(low, high + 1):
        if correlations[lag] >= correlations[lag - 1] and correlations[lag] >= correlations[lag + 1]:
            if best is None or correlations[lag] > correlations[best]:
                best = lag
    if best is None:
        return None
    if correlations[best] <= 0.15:
        return None
    # Prefer the fundamental. The autocorrelation of a clean cycle peaks at *every* multiple of the
    # true period, so the tallest peak is often a harmonic (measured: a period-40 grid peaks at 80
    # with r = 0.996, and 80's half explains 99% of that). Halve/third/quarter while a divisor still
    # explains most of the correlation and still sits in the search window.
    reduced = True
    while reduced:
        reduced = False
        for divisor in (2, 3, 4):
            if best % divisor:
                continue
            candidate = best // divisor
            if candidate < low:
                continue
            if correlations[candidate] >= 0.8 * correlations[best]:
                best = candidate
                reduced = True
                break
    return best


def _median_trend(grid, window):
    """Centred running median over the present values of the grid."""
    half = window // 2
    n = len(grid)
    trend = []
    for index in range(n):
        low = index - half
        high = index + half
        if low < 0:
            low = 0
        if high > n - 1:
            high = n - 1
        local = [grid[position] for position in range(low, high + 1) if grid[position] is not None]
        trend.append(_median(local) if local else None)
    return trend


def _standardized_series(grid):
    """Least-squares detrend, then centre and winsorise at three robust sigmas."""
    points = [(index, value) for index, value in enumerate(grid) if value is not None]
    if len(points) < 2:
        return [None] * len(grid)
    count = float(len(points))
    sum_x = 0.0
    sum_y = 0.0
    for index, value in points:
        sum_x += index
        sum_y += value
    mean_x = sum_x / count
    mean_y = sum_y / count
    sxx = 0.0
    sxy = 0.0
    for index, value in points:
        dx = index - mean_x
        sxx += dx * dx
        sxy += dx * (value - mean_y)
    slope = sxy / sxx if sxx > 0 else 0.0
    intercept = mean_y - slope * mean_x
    detrended = [
        (value - (intercept + slope * index)) if value is not None else None
        for index, value in enumerate(grid)
    ]
    present = [value for value in detrended if value is not None]
    scale, median_value = robust_scale(present)
    if scale == 0:
        return [None] * len(grid)
    out = []
    for value in detrended:
        if value is None:
            out.append(None)
            continue
        standardized = (value - median_value) / scale
        if standardized > 3.0:
            standardized = 3.0
        elif standardized < -3.0:
            standardized = -3.0
        out.append(standardized)
    return out


def _autocorrelation(z, max_lag):
    """Pairwise-complete autocorrelation over the grid: missing cells drop the pair, not the lag."""
    n = len(z)
    correlations = []
    for lag in range(0, max_lag + 1):
        numerator = 0.0
        left = 0.0
        right = 0.0
        for index in range(lag, n):
            a = z[index]
            b = z[index - lag]
            if a is None or b is None:
                continue
            numerator += a * b
            left += a * a
            right += b * b
        if left > 0 and right > 0:
            correlations.append(numerator / _sqrt(left * right))
        else:
            correlations.append(0.0)
    return correlations


def _sqrt(value):
    """Integer-free square root by Newton iteration: `**0.5` is banned (plan/02 3.2)."""
    if value <= 0:
        return 0.0
    guess = float(value)
    for _iteration in range(60):
        next_guess = 0.5 * (guess + value / guess)
        if next_guess == guess:
            break
        guess = next_guess
    return guess


def estimate_period(parsed, spec):
    """Per-series period estimates and the run-level period they resolve to.

    The run-level value is the median of the per-series estimates (lower middle on an even count),
    so one unrepresentative series cannot drag it, and it is recorded in run.json as the effective
    value a recomputation consumes -- the estimator itself is never re-run downstream (K8/D13).
    """
    estimates = []
    for series_id in parsed.series_order:
        rows = parsed.rows_by_series[series_id]
        stamps = [row[1] for row in rows]
        values = [row[2] for row in rows]
        cadence = dominant_interval(stamps)
        if cadence is None or len(rows) < 24:
            continue
        grid = to_grid(stamps, values, cadence)
        estimate = estimate_series_period(
            grid, spec["period_reject_window"], spec["period_reject_sigma"]
        )
        if estimate is not None:
            estimates.append((series_id, estimate))
    if not estimates:
        return 1, []
    ordered = sorted(estimate for _series_id, estimate in estimates)
    return ordered[(len(ordered) - 1) // 2], estimates


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def grid_positions(rows):
    """The grid index of every sample of one series, from the timestamps alone.

    The STL seasonal curve folds on this index rather than on the list position, so a dropped
    sample does not shift the phase of everything after it.
    """
    stamps = [row[1] for row in rows]
    cadence = dominant_interval(stamps)
    if cadence is None:
        return list(range(len(rows)))
    start = stamps[0]
    return [(stamp - start) // cadence for stamp in stamps]


def series_facts(parsed):
    """Per-series integers for the run document (counts, span, cadence, grid size)."""
    facts = []
    for series_id in parsed.series_order:
        rows = parsed.rows_by_series[series_id]
        stamps = [row[1] for row in rows]
        present = [row[2] for row in rows if row[2] is not None]
        cadence = dominant_interval(stamps)
        cells = None
        if cadence is not None and stamps:
            cells = (stamps[-1] - stamps[0]) // cadence + 1
        facts.append(
            {
                "series_id": series_id,
                "n_points": len(rows),
                "n_values_present": len(present),
                "n_values_missing": len(rows) - len(present),
                "cadence_ms": cadence,
                "n_grid_cells": cells,
                "first_ms": min(stamps) if stamps else None,
                "last_ms": max(stamps) if stamps else None,
            }
        )
    return facts


def threshold_refs(dumped_spec):
    """`detector -> effective parameter block` for the episode's `threshold_ref` field.

    The reference is the family's resolved parameter block in its on-disk form, so an episode
    carries the same representation of `k` that run.json does -- one form, no drift.
    """
    refs = {}
    for name, _params in DETECTOR_PARAMS:
        refs[name] = dumped_spec[name]
        if name == "rules":
            for rule in RULE_NAMES:
                refs["rules." + rule] = dumped_spec[name]
    return refs


def run_detectors(parsed, spec, period_points):
    """Run all four detectors over every series.

    Returns `{(series_id, detector): [(epoch_ms, row_no, score)]}`, one bucket per detector so a
    rule's episodes never merge with another rule's (the detector name is part of the episode and
    part of the severity key).
    """
    detections = {}
    for series_id in parsed.series_order:
        rows = parsed.rows_by_series[series_id]
        values = [row[2] for row in rows]
        positions = grid_positions(rows)

        def record(detector, hits):
            bucket = detections.setdefault((series_id, detector), [])
            for index, score in hits:
                bucket.append((rows[index][1], rows[index][0], score))

        mad = spec["rolling_mad_z"]
        record("rolling_mad_z", rolling_mad_z(values, mad["window"], mad["k"], mad["min_valid"]))
        iqr = spec["rolling_iqr"]
        record("rolling_iqr", rolling_iqr(values, iqr["window"], iqr["iqr_mult"], iqr["min_valid"]))
        stl = spec["stl_resid_z"]
        record(
            "stl_resid_z",
            stl_resid_z(
                values,
                positions,
                period_points,
                stl["inner"],
                stl["outer"],
                stl["window"],
                stl["k"],
                stl["min_valid"],
            ),
        )
        for index, score, rule in rules(values, spec["rules"]):
            record("rules." + rule, [(index, score)])
    return detections


def summarize(detections, episodes):
    """Integer counts for the archive summary (per detector and per series)."""
    episodes_by_detector = {}
    episodes_by_series = {}
    for episode in episodes:
        key = episode["detector"]
        episodes_by_detector[key] = episodes_by_detector.get(key, 0) + 1
        key = episode["series_id"]
        episodes_by_series[key] = episodes_by_series.get(key, 0) + 1
    detections_by_detector = {}
    n_detections = 0
    for detector in sorted(set(key[1] for key in detections)):
        count = 0
        for key, points in detections.items():
            if key[1] == detector:
                count += len(points)
        detections_by_detector[detector] = count
        n_detections += count
    return {
        "n_episodes": len(episodes),
        "n_detections": n_detections,
        "episodes_by_detector": episodes_by_detector,
        "episodes_by_series": episodes_by_series,
        "detections_by_detector": detections_by_detector,
    }


def detect_all(parsed, resolved):
    """Full pipeline over a parsed series and an already-resolved spec.

    Returns `(run_document, anomaly_set)`. The run document holds the *effective* values -- in
    particular the resolved `period_points` and, for every parameter, the value that was actually
    used -- so it is the only thing a recomputation needs (K8).
    """
    run_document, anomaly_set, _detections = detect_all_detailed(parsed, resolved)
    return run_document, anomaly_set


def detect_all_detailed(parsed, resolved):
    """`detect_all` plus the detector output the archive was built from (M3).

    The browser artifact carries the anomalous *points* as well as the episodes, so the carrier
    builder needs the detections. Handing them back from the same pass -- rather than re-running
    the detectors -- is not only cheaper: it makes the payload's point set the one the archive was
    actually assembled from, so the two cannot drift apart by construction.
    """
    period_points = resolved["period_points"]
    estimates = []
    if period_points is None:
        period_points, estimates = estimate_period(parsed, resolved)
        resolved = dict(resolved)
        resolved["period_points"] = period_points
        if estimates:
            period_source = "estimated"
        else:
            period_source = "no-cycle-default"
    else:
        period_source = "declared"

    detections = run_detectors(parsed, resolved, period_points)
    dumped = dump_spec(resolved)
    episodes = episodes_module.build_episodes(
        parsed.rows_by_series,
        detections,
        threshold_refs(dumped),
        resolved["max_gap_ms"],
        _QUANT_DECIMALS,
    )
    summary = summarize(detections, episodes)
    run_document = {
        "schema_version": canon.ANOMALY_SET_VERSION,
        "canon_version": canon.CANON_VERSION,
        "detector_version": DETECTOR_VERSION,
        "quant_decimals": _QUANT_DECIMALS,
        "period_source": period_source,
        "period_estimates": [
            {"series_id": series_id, "period_points": value}
            for series_id, value in sorted(estimates)
        ],
        "source": {
            "file": os.path.basename(parsed.path),
            "sha256": parsed.stats["sha256"],
            "size_bytes": parsed.stats["size_bytes"],
            "n_csv_records": parsed.stats["n_records"],
        },
        "params": dumped,
        "series": series_facts(parsed),
    }
    canon.assert_hashable(run_document)
    return run_document, canon.build_anomaly_set(run_document, episodes, summary), detections


def cmd_detect(csv_path, spec_path, out_dir):
    """CLI body for `detect`: 0 on success, 2 on any usage/input error, nothing written on 2."""
    from .cli import EXIT_OK, EXIT_USAGE

    spec = None
    if spec_path:
        if not os.path.isfile(spec_path):
            print("error: run-spec file not found: %s" % spec_path, file=sys.stderr)
            return EXIT_USAGE
        try:
            with open(spec_path, "rb") as handle:
                spec = json.loads(handle.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            print("error: run-spec is not readable JSON: %s" % (exc,), file=sys.stderr)
            return EXIT_USAGE
        except OSError as exc:
            print("error: cannot read %s: %s" % (spec_path, exc), file=sys.stderr)
            return EXIT_USAGE
        if not isinstance(spec, dict):
            print("error: run-spec must be a JSON object: %s" % (spec_path,), file=sys.stderr)
            return EXIT_USAGE

    try:
        resolved = resolve_spec(spec)
    except (KeyError, ValueError) as exc:
        print("error: run-spec: %s" % (exc,), file=sys.stderr)
        return EXIT_USAGE

    try:
        parsed = csvio.load_series(csv_path, csv_spec(resolved))
    except csvio.CsvContractError as exc:
        print("input error: %s" % (exc,), file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print("error: cannot read %s: %s" % (csv_path, exc), file=sys.stderr)
        return EXIT_USAGE

    run_document, anomaly_set = detect_all(parsed, resolved)
    digest = canon.canonical_digest(anomaly_set)
    try:
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        _write_bytes(os.path.join(out_dir, "run.json"), canon.canonical_json_bytes(run_document))
        _write_bytes(os.path.join(out_dir, "anomalies.json"), canon.canonical_json_bytes(anomaly_set))
        _write_bytes(os.path.join(out_dir, "anomaly_set.sha256"), (digest + "\n").encode("utf-8"))
    except OSError as exc:
        print("error: cannot write into %s: %s" % (out_dir, exc), file=sys.stderr)
        return EXIT_USAGE

    summary = anomaly_set["summary"]
    print(
        "detect: %d episode(s) from %d detection(s) over %d series; period_points=%d (%s)"
        % (
            summary["n_episodes"],
            summary["n_detections"],
            len(parsed.series_order),
            run_document["params"]["period_points"],
            run_document["period_source"],
        )
    )
    print("anomaly-set sha256 %s" % digest)
    return EXIT_OK


def _write_bytes(path, payload):
    with open(path, "wb") as handle:
        handle.write(payload)

