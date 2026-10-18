"""Deterministic geometry and binning for the annotated view (M4).

API:
  DEFAULT_RENDER_SPEC / resolve_render_spec(spec=None) -> dict
  value_bounds(values_q) -> (lo_q, hi_q)
  row_to_pixel(index, n_rows, left, plot_width) -> int
  value_to_pixel(value_q, lo_q, hi_q, top, plot_height) -> int
  region_spans(rows, gap_threshold_ms) -> list[dict]
  threshold_values(values, detector, threshold_ref, decimals) -> list[(side, value_q)]
  main_series_layout(rows, episodes, width, height, gap_threshold_ms) -> dict
  episode_zoom_layout(rows, episode, pad_rows, width, height, gap_threshold_ms) -> dict
  density_bins(rows_by_series, episodes_by_series, heat_bin_ms) -> list[dict]
  small_multiples_layout(rows_by_series, episodes_by_series, width, height, gap_threshold_ms) -> list[dict]

Every coordinate this module returns is an **integer pixel** and every value-derived number is a
**fixed-point integer** (`canon.quantize`, 6 decimals), so the same input produces the same
geometry byte for byte: no float in the output, no random, no clock (D14/K2). Row index -> pixel is
one fixed linear map, applied with integer division only, and the same map is shared by the main
view and by the small multiples, so the two views line up column by column.

The three abnormal-region kinds are distinguished by *structure*, not by colour depth (plan/06 P5):
a gap carries explicit slanted stripe geometry, a zero run carries a ladder of vertical rungs, and a
missing run carries neither (it is drawn as a dashed outline). A black-and-white print therefore
still tells them apart -- which is the point of building the texture in the geometry layer rather
than in a colour choice.

`threshold_values` derives an episode's reference line from its own `threshold_ref` (the detector's
effective parameter block), never from a hard-coded constant: a z-like detector yields an upper and
a lower line, `rolling_iqr` yields the quartile-fence pair, `rules.static_threshold` yields the
configured level, and the rules that answer on missingness or on a difference domain return no line
at all -- the card says so instead of inventing one.
"""

from . import canon, detect

QUANT_DECIMALS = 6
_PPM = 1000000

# Value-axis padding, in parts per million of the series' own span: 4% below the minimum and above
# the maximum, so an anomalous excursion is never clipped by the frame edge. The bounds are taken
# over *all* present values, anomalies included -- the frame grows to hold the anomaly band rather
# than the band being cut off at the frame.
Y_PAD_PPM = 40000
MIN_SPAN_Q = 1

# Plot frames (integers; the geometry is integer-only by construction).
VIEW_LEFT = 62
VIEW_RIGHT = 12
VIEW_TOP = 12
VIEW_BOTTOM = 26
ZOOM_LEFT = 46
ZOOM_RIGHT = 10
ZOOM_TOP = 10
ZOOM_BOTTOM = 22

MIN_X_SPAN = 2          # a one-row region is widened so it stays visible
MIN_BAND_HEIGHT = 4     # a flat episode (a zero run) still gets a visible band
GAP_STRIPE_SPACING = 7  # slanted stripes, one every 7 px
ZERO_RUNG_SPACING = 6   # vertical rungs, one every 6 px
ZERO_RUNG_HALF = 4      # each rung is 2*4 px tall, centred on the zero line
ZERO_BAND_HALF = 5      # the zero run's outlined band is 2*5 px tall
N_X_TICKS = 5
N_Y_TICKS = 3

# Render-only parameters. They are presentation knobs -- they change what the page draws, never what
# the detectors decide -- so they are resolved and recorded on their own (`resolve_render_spec`,
# carried in the artifact) instead of being mixed into the hashed run document. See plan/06 D22.
DEFAULT_PAD_ROWS = 6
DEFAULT_HEAT_BIN_MS = 3600000  # 1 hour
RENDER_PARAMS = (("pad_rows", "int"), ("heat_bin_ms", "int"))
DEFAULT_RENDER_SPEC = {"pad_rows": DEFAULT_PAD_ROWS, "heat_bin_ms": DEFAULT_HEAT_BIN_MS}

KIND_GAP = "gap"
KIND_ZERO = "zero"
KIND_MISSING = "missing"

REGION_KINDS = (KIND_GAP, KIND_ZERO, KIND_MISSING)
ZERO_VALUE_Q = 0


def resolve_render_spec(spec=None):
    """Merge a render spec over the defaults; unknown keys and non-integers are rejected loudly.

    Same discipline as the run spec (K8): there is no hidden default, every value is coerced to its
    declared kind, and the resolved block is what the artifact displays and what the page's
    run-spec fragment is built from.
    """
    resolved = dict(DEFAULT_RENDER_SPEC)
    if spec:
        unknown = sorted(set(spec) - set(resolved))
        if unknown:
            raise KeyError("unknown render-spec key(s): %s" % ", ".join(unknown))
        resolved.update(spec)
    for param, kind in RENDER_PARAMS:
        value = resolved[param]
        if isinstance(value, bool) or not isinstance(value, int):
            if not (isinstance(value, float) and value == int(value)):
                raise ValueError("render-spec %s must be an integer, got %r" % (param, value))
            value = int(value)
        resolved[param] = int(value)
    if resolved["pad_rows"] < 0:
        raise ValueError("render-spec pad_rows must not be negative")
    if resolved["heat_bin_ms"] <= 0:
        raise ValueError("render-spec heat_bin_ms must be positive")
    return resolved


# ---------------------------------------------------------------------------
# The fixed maps (integers only)
# ---------------------------------------------------------------------------


def value_bounds(values_q):
    """The y-axis bounds for a series, padded so the anomaly band is never clipped.

    `lo` is below every present value and `hi` above it. A constant series still gets a
    non-degenerate axis (padding of at least one fixed-point unit), so the map below can never
    divide by zero.
    """
    present = [value for value in values_q if value is not None]
    if not present:
        return (0, MIN_SPAN_Q)
    low = min(present)
    high = max(present)
    span = high - low
    pad = span * Y_PAD_PPM // _PPM
    if pad < MIN_SPAN_Q:
        pad = MIN_SPAN_Q
    return (low - pad, high + pad)


def row_to_pixel(index, n_rows, left, plot_width):
    """Row index -> x pixel: one fixed linear map, integer division only.

    Shared by the main view and the small multiples so the two line up (M4). The operand of the
    integer division is non-negative by construction (`index >= 0`, `n_rows - 1 > 0`).
    """
    if n_rows <= 1:
        return left + plot_width // 2
    return left + index * plot_width // (n_rows - 1)


def value_to_pixel(value_q, lo_q, hi_q, top, plot_height):
    """Value (fixed point) -> y pixel, inverted (the maximum sits at the top).

    The numerator `value_q - lo_q` is non-negative because `lo_q` is the padded lower bound, so the
    integer division in K4's non-negative-operand rule is satisfied.
    """
    span = hi_q - lo_q
    if span < MIN_SPAN_Q:
        span = MIN_SPAN_Q
    offset = (value_q - lo_q) * plot_height // span
    if offset < 0:
        offset = 0
    elif offset > plot_height:
        offset = plot_height
    return top + plot_height - offset


def frame(width, height, left, right, top, bottom):
    """The integer plot frame for one chart: `{left, top, width, height, right, bottom}`."""
    plot_width = width - left - right
    plot_height = height - top - bottom
    if plot_width < 1:
        plot_width = 1
    if plot_height < 1:
        plot_height = 1
    return {
        "width": width,
        "height": height,
        "left": left,
        "top": top,
        "plot_width": plot_width,
        "plot_height": plot_height,
        "right": left + plot_width,
        "bottom": top + plot_height,
    }


# ---------------------------------------------------------------------------
# Region classification (gap / zero / missing)
# ---------------------------------------------------------------------------


def region_spans(rows, gap_threshold_ms):
    """Classify one series' abnormal regions, in row order (M4, plan/06 P5).

    `gap`     -- a hole in the *timeline*: the interval between two neighbouring rows exceeds the
                 profile's gap threshold, so the region between them holds no samples at all
                 (`missing_points` counts what a regular cadence would have put there);
    `zero`    -- maximal runs of rows whose value is exactly zero;
    `missing` -- maximal runs of rows whose value is missing (`None`), never replaced by 0 and never
                 interpolated (K9).

    The three kinds are pairwise disjoint by construction (a gap is a hole *between* rows, a zero or
    missing run is a property *of* rows), which is asserted here rather than assumed: overlapping
    regions would make "which texture is this?" unanswerable.
    """
    stamps = [row[1] for row in rows]
    cadence = detect.dominant_interval(stamps)
    if gap_threshold_ms is None:
        gap_threshold_ms = cadence * 3 if cadence is not None else None

    spans = []
    if gap_threshold_ms is not None:
        for index in range(1, len(rows)):
            interval = stamps[index] - stamps[index - 1]
            if interval > gap_threshold_ms:
                implied = interval // cadence - 1 if cadence else 0
                spans.append(
                    {
                        "kind": KIND_GAP,
                        "start_index": index - 1,
                        "end_index": index,
                        "start_row": rows[index - 1][0],
                        "end_row": rows[index][0],
                        "n_points": implied if implied > 0 else 0,
                    }
                )

    for kind, predicate in ((KIND_ZERO, _is_zero), (KIND_MISSING, _is_missing)):
        start = None
        for index in range(len(rows) + 1):
            inside = index < len(rows) and predicate(rows[index][2])
            if inside and start is None:
                start = index
            elif not inside and start is not None:
                spans.append(
                    {
                        "kind": kind,
                        "start_index": start,
                        "end_index": index - 1,
                        "start_row": rows[start][0],
                        "end_row": rows[index - 1][0],
                        "n_points": index - start,
                    }
                )
                start = None

    spans.sort(key=lambda span: (span["start_index"], REGION_KINDS.index(span["kind"])))
    # Only the row-property kinds can collide (a row's value cannot be both zero and missing). A gap
    # is a property of the *hole between* two rows, so its boundary rows are not claimed by it: a
    # missing run can perfectly well start right where the timeline resumes after a gap.
    covered = {}
    for span in spans:
        if span["kind"] == KIND_GAP:
            continue
        for index in range(span["start_index"], span["end_index"] + 1):
            covered[index] = covered.get(index, 0) + 1
    overlaps = sorted(index for index, count in covered.items() if count > 1)
    if overlaps:
        raise ValueError("abnormal regions overlap at row index(es): %s" % overlaps)
    return spans


def _is_zero(value):
    return value is not None and value == 0.0


def _is_missing(value):
    return value is None


def _gap_stripes(x0, x1, y_top, y_bottom):
    """Slanted stripe segments inside a gap rectangle, clipped to it (integers only).

    A stripe starts on the bottom edge and climbs at ~3:1; when it would leave the right edge it is
    shortened so it stays inside the rectangle. The clip is computed here rather than left to an SVG
    `clip-path`, because a clip path is a `url(...)` reference and the artifact allows `url()` only
    for an inlined `data:` payload (K12).
    """
    stripes = []
    height = y_bottom - y_top
    slant = height // 3
    if slant < 1:
        slant = 1
    x = x0
    while x <= x1:
        dx = x1 - x
        if dx > slant:
            dx = slant
        dy = dx * height // slant
        stripes.append([x, y_bottom, x + dx, y_bottom - dy])
        x += GAP_STRIPE_SPACING
    return stripes


def _zero_rungs(x0, x1, y):
    """Vertical rungs across a zero run, centred on the zero line (integers only)."""
    rungs = []
    x = x0
    while x <= x1:
        rungs.append([x, y - ZERO_RUNG_HALF, x, y + ZERO_RUNG_HALF])
        x += ZERO_RUNG_SPACING
    return rungs


# ---------------------------------------------------------------------------
# Threshold lines derived from an episode's `threshold_ref`
# ---------------------------------------------------------------------------


def threshold_values(rows, detector, threshold_ref, peak_row, decimals=QUANT_DECIMALS):
    """The value-space reference line(s) an episode's own `threshold_ref` implies.

    Returns `[(side, value_q)]` where `side` is `"upper"`, `"lower"` or `"level"`. The arithmetic
    mirrors the detector that fired, over the same trailing window it scored the peak row with, so
    the line is the detector's own fence rather than a plausible-looking number: the z detectors
    use `median ± k * robust_scale`, `rolling_iqr` uses the `[Q1 - m*IQR, Q3 + m*IQR]` box (with the
    same degenerate-box fallback), and `rules.static_threshold` uses the configured `±level`.

    An empty list means "this detector has no value-space threshold", and the card says that
    instead of drawing a line nobody can derive: `rules.pct_jump` answers on a ratio,
    `rules.cusum` on standardised differences, and `rules.missing_run` / `rules.zero_run` on the
    *presence* of samples.
    """
    ref = threshold_ref or {}
    index = None
    for position in range(len(rows)):
        if rows[position][0] == peak_row:
            index = position
            break
    if index is None:
        return []
    if detector in ("rolling_mad_z", "stl_resid_z", "rolling_iqr"):
        window = _window_size(ref.get("window"))
        present = _trailing(rows, index, window)
        if not present:
            return []
        if detector == "rolling_iqr":
            multiple = _decimal(ref.get("iqr_mult"))
            if multiple is None:
                return []
            low_quartile = detect._quantile(present, 0.25)
            high_quartile = detect._quantile(present, 0.75)
            spread = high_quartile - low_quartile
            if spread > 0:
                return [
                    ("upper", canon.quantize(high_quartile + multiple * spread, decimals)),
                    ("lower", canon.quantize(low_quartile - multiple * spread, decimals)),
                ]
            center = detect._median(present)
            scale, _median_value = detect.robust_scale(present)
        else:
            multiple = _decimal(ref.get("k"))
            if multiple is None:
                return []
            scale, center = detect.robust_scale(present)
        if scale == 0:
            return []
        return [
            ("upper", canon.quantize(center + multiple * scale, decimals)),
            ("lower", canon.quantize(center - multiple * scale, decimals)),
        ]
    if detector == "rules.static_threshold":
        level = _decimal(ref.get("static_threshold"))
        if level is None:
            return []
        return [
            ("upper", canon.quantize(level, decimals)),
            ("lower", canon.quantize(-level, decimals)),
        ]
    return []


def _window_size(value):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value == int(value):
            value = int(value)
        else:
            return 24
    return value if value > 0 else 24


def _trailing(rows, index, window):
    """The present values of the trailing window ending at `index` (inclusive), like `_window`."""
    low = index - window + 1
    if low < 0:
        low = 0
    found = []
    for position in range(low, index + 1):
        value = rows[position][2]
        if value is not None:
            found.append(value)
    return found


def _decimal(value):
    """A dumped decimal parameter (a 6-decimal fixed-point string) back as a float, or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-series geometry
# ---------------------------------------------------------------------------


def _quantised(values):
    return [None if value is None else canon.quantize(value, QUANT_DECIMALS) for value in values]


def _index_by_row(rows):
    return dict((row[0], index) for index, row in enumerate(rows))


def _visible_band(band_top, band_bottom, plot):
    """Grow a degenerate band to a visible height, centred, staying inside the frame.

    A flat episode (nine samples that are all exactly zero, say) has a value range of zero height and
    would otherwise be drawn as a one-pixel line that reads as an artefact rather than as a band.
    """
    if band_bottom - band_top >= MIN_BAND_HEIGHT:
        return band_top, band_bottom
    center = (band_top + band_bottom) // 2
    half = MIN_BAND_HEIGHT // 2
    top = center - half
    bottom = center + half
    if top < plot["top"]:
        top = plot["top"]
        bottom = top + MIN_BAND_HEIGHT
    if bottom > plot["bottom"]:
        bottom = plot["bottom"]
        top = bottom - MIN_BAND_HEIGHT
    return top, bottom


def main_series_layout(rows, episodes, width, height, gap_threshold_ms=None):
    """Full geometry of one series view: points, segments, bands, peaks, region textures, axes.

    `rows` is `[(row_no, epoch_ms, value)]`. Nothing here reads a clock or a random source, and no
    returned number is a float: two runs on the same input produce the same integers, which is what
    "the same input renders the same geometry" means concretely.
    """
    n_rows = len(rows)
    plot = frame(width, height, VIEW_LEFT, VIEW_RIGHT, VIEW_TOP, VIEW_BOTTOM)
    values_q = _quantised([row[2] for row in rows])
    lo_q, hi_q = value_bounds(values_q)
    xs = [row_to_pixel(index, n_rows, plot["left"], plot["plot_width"]) for index in range(n_rows)]

    points = []
    segments = []
    current = []
    for index in range(n_rows):
        value_q = values_q[index]
        if value_q is None:
            points.append(None)
            if current:
                segments.append(current)
                current = []
            continue
        coordinate = (xs[index], value_to_pixel(value_q, lo_q, hi_q, plot["top"], plot["plot_height"]))
        points.append(coordinate)
        current.append(coordinate)
    if current:
        segments.append(current)

    index_by_row = _index_by_row(rows)
    bands = []
    for episode in episodes:
        start = index_by_row.get(episode["start_row"])
        end = index_by_row.get(episode["end_row"])
        if start is None or end is None:
            continue
        peak_index = None
        peak_q = None
        low_q = None
        high_q = None
        for index in range(start, end + 1):
            value_q = values_q[index]
            if value_q is None:
                continue
            if peak_q is None or value_q > peak_q:
                peak_q = value_q
                peak_index = index
            if low_q is None or value_q < low_q:
                low_q = value_q
            if high_q is None or value_q > high_q:
                high_q = value_q
        x0 = xs[start]
        x1 = xs[end]
        if x1 - x0 < MIN_X_SPAN:
            x1 = x0 + MIN_X_SPAN
        if peak_index is None:
            # A detection that answers on missingness has no value to place; the band says so by
            # spanning the frame instead of pretending the missing run sits at some level.
            band_top = plot["top"]
            band_bottom = plot["bottom"]
            peak_x = None
            peak_y = None
        else:
            band_top = value_to_pixel(high_q, lo_q, hi_q, plot["top"], plot["plot_height"])
            band_bottom = value_to_pixel(low_q, lo_q, hi_q, plot["top"], plot["plot_height"])
            band_top, band_bottom = _visible_band(band_top, band_bottom, plot)
            peak_x = xs[peak_index]
            peak_y = value_to_pixel(peak_q, lo_q, hi_q, plot["top"], plot["plot_height"])
        bands.append(
            {
                "episode_id": episode["episode_id"],
                "detector": episode["detector"],
                "x0": x0,
                "x1": x1,
                "y_top": band_top,
                "y_bottom": band_bottom,
                "peak_x": peak_x,
                "peak_y": peak_y,
                "peak_value_q": peak_q,
                "has_values": peak_index is not None,
            }
        )
    bands.sort(key=lambda band: (band["x0"], band["x1"], band["episode_id"]))

    spans = []
    for region in region_spans(rows, gap_threshold_ms):
        x0 = xs[region["start_index"]]
        x1 = xs[region["end_index"]]
        if region["kind"] == KIND_GAP:
            # The x axis is *row index*, so a hole in the timeline would otherwise be one pixel
            # wide: the samples are absent, not misplaced. The band is widened by the row slots the
            # absent samples would have occupied at the local row density, so "15 samples missing"
            # reads as a 15-slot-wide hatched band instead of an invisible seam. The map itself is
            # untouched -- this widens the annotation, not the data.
            expected = region["n_points"]
            if expected > 0:
                x1 = x1 + expected * plot["plot_width"] // max(1, n_rows - 1)
        if x1 - x0 < MIN_X_SPAN:
            x1 = x0 + MIN_X_SPAN
        record = {
            "kind": region["kind"],
            "start_row": region["start_row"],
            "end_row": region["end_row"],
            "n_points": region["n_points"],
            "x0": x0,
            "x1": x1,
            "y_top": plot["top"],
            "y_bottom": plot["bottom"],
            "stripes": [],
            "rungs": [],
        }
        if region["kind"] == KIND_GAP:
            record["stripes"] = _gap_stripes(x0, x1, plot["top"], plot["bottom"])
        elif region["kind"] == KIND_ZERO:
            zero_y = value_to_pixel(ZERO_VALUE_Q, lo_q, hi_q, plot["top"], plot["plot_height"])
            record["y_top"] = zero_y - ZERO_BAND_HALF
            record["y_bottom"] = zero_y + ZERO_BAND_HALF
            record["rungs"] = _zero_rungs(x0, x1, zero_y)
        spans.append(record)
    spans.sort(key=lambda span: (span["x0"], REGION_KINDS.index(span["kind"])))

    x_ticks = []
    for slot in range(N_X_TICKS):
        index = 0 if n_rows <= 1 else slot * (n_rows - 1) // (N_X_TICKS - 1)
        x_ticks.append({"index": index, "x": xs[index], "row_no": rows[index][0]})
    y_ticks = []
    present_q = [value for value in values_q if value is not None]
    if present_q:
        for value_q in _y_tick_values(min(present_q), max(present_q)):
            y_ticks.append(
                {
                    "value_q": value_q,
                    "y": value_to_pixel(value_q, lo_q, hi_q, plot["top"], plot["plot_height"]),
                    "label": canon.fixed_to_str(value_q, QUANT_DECIMALS),
                }
            )
    zero_y = None
    if lo_q <= ZERO_VALUE_Q <= hi_q and present_q and min(present_q) < 0 < max(present_q):
        zero_y = value_to_pixel(ZERO_VALUE_Q, lo_q, hi_q, plot["top"], plot["plot_height"])

    return {
        "n_rows": n_rows,
        "frame": plot,
        "value_bounds": {"lo_q": lo_q, "hi_q": hi_q},
        "data_bounds": {
            "lo_q": min(present_q) if present_q else 0,
            "hi_q": max(present_q) if present_q else 0,
        },
        "points": points,
        "segments": segments,
        "bands": bands,
        "regions": spans,
        "x_ticks": x_ticks,
        "y_ticks": y_ticks,
        "zero_y": zero_y,
    }


def _y_tick_values(low_q, high_q):
    """Three label positions for the y axis: the data minimum, the midpoint, the data maximum."""
    if low_q == high_q:
        return [low_q]
    middle = low_q + (high_q - low_q) // 2
    values = [high_q, middle, low_q]
    if high_q - low_q < N_Y_TICKS:
        return [high_q, low_q]
    return values


def episode_zoom_layout(rows, episode, pad_rows, width, height, gap_threshold_ms=None):
    """Local zoom of one episode: `[start_row - pad, end_row + pad]`, clipped to the series.

    The window is expressed in *row index* space and the same fixed map is used inside it, so the
    card is a magnification of the main view rather than a differently-shaped picture. The
    threshold line(s) come from the episode's `threshold_ref` (never from a constant), and the peak
    marker is the highest in-episode value.
    """
    index_by_row = _index_by_row(rows)
    start = index_by_row.get(episode["start_row"])
    end = index_by_row.get(episode["end_row"])
    if start is None or end is None:
        raise KeyError("episode %s names rows outside the series" % episode["episode_id"])
    if start > end:
        start, end = end, start
    first = start - pad_rows
    if first < 0:
        first = 0
    last = end + pad_rows
    if last > len(rows) - 1:
        last = len(rows) - 1

    window = rows[first : last + 1]
    n_rows = len(window)
    plot = frame(width, height, ZOOM_LEFT, ZOOM_RIGHT, ZOOM_TOP, ZOOM_BOTTOM)
    values_q = _quantised([row[2] for row in window])
    lo_q, hi_q = value_bounds(values_q)
    xs = [row_to_pixel(index, n_rows, plot["left"], plot["plot_width"]) for index in range(n_rows)]

    points = []
    segments = []
    current = []
    for index in range(n_rows):
        value_q = values_q[index]
        if value_q is None:
            points.append(None)
            if current:
                segments.append(current)
                current = []
            continue
        coordinate = (xs[index], value_to_pixel(value_q, lo_q, hi_q, plot["top"], plot["plot_height"]))
        points.append(coordinate)
        current.append(coordinate)
    if current:
        segments.append(current)

    episode_values = [row[2] for row in rows[start : end + 1]]
    present_q = [value for value in _quantised(episode_values) if value is not None]
    band_start = start - first
    band_end = end - first
    x0 = xs[band_start]
    x1 = xs[band_end]
    if x1 - x0 < MIN_X_SPAN:
        x1 = x0 + MIN_X_SPAN
    if present_q:
        band_top = value_to_pixel(max(present_q), lo_q, hi_q, plot["top"], plot["plot_height"])
        band_bottom = value_to_pixel(min(present_q), lo_q, hi_q, plot["top"], plot["plot_height"])
        band_top, band_bottom = _visible_band(band_top, band_bottom, plot)
    else:
        band_top = plot["top"]
        band_bottom = plot["bottom"]

    peak_index = None
    peak_q = None
    for index in range(band_start, band_end + 1):
        value_q = values_q[index]
        if value_q is None:
            continue
        if peak_q is None or value_q > peak_q:
            peak_q = value_q
            peak_index = index

    thresholds = []
    peak_row = rows[first + peak_index][0] if peak_index is not None else episode["start_row"]
    for side, value_q in threshold_values(
        rows, episode["detector"], episode.get("threshold_ref"), peak_row, QUANT_DECIMALS
    ):
        if value_q is None:
            continue
        thresholds.append(
            {
                "side": side,
                "value_q": value_q,
                "y": value_to_pixel(value_q, lo_q, hi_q, plot["top"], plot["plot_height"]),
                "label": canon.fixed_to_str(value_q, QUANT_DECIMALS),
            }
        )

    regions = []
    for region in region_spans(window, gap_threshold_ms):
        region_x0 = xs[region["start_index"]]
        region_x1 = xs[region["end_index"]]
        if region["kind"] == KIND_GAP and region["n_points"] > 0:
            region_x1 = region_x1 + region["n_points"] * plot["plot_width"] // max(1, n_rows - 1)
        if region_x1 - region_x0 < MIN_X_SPAN:
            region_x1 = region_x0 + MIN_X_SPAN
        record = {
            "kind": region["kind"],
            "x0": region_x0,
            "x1": region_x1,
            "y_top": plot["top"],
            "y_bottom": plot["bottom"],
            "stripes": [],
            "rungs": [],
        }
        if region["kind"] == KIND_GAP:
            record["stripes"] = _gap_stripes(region_x0, region_x1, plot["top"], plot["bottom"])
        elif region["kind"] == KIND_ZERO:
            zero_y = value_to_pixel(ZERO_VALUE_Q, lo_q, hi_q, plot["top"], plot["plot_height"])
            record["y_top"] = zero_y - ZERO_BAND_HALF
            record["y_bottom"] = zero_y + ZERO_BAND_HALF
            record["rungs"] = _zero_rungs(region_x0, region_x1, zero_y)
        regions.append(record)
    regions.sort(key=lambda span: (span["x0"], REGION_KINDS.index(span["kind"])))

    return {
        "n_rows": n_rows,
        "frame": plot,
        "value_bounds": {"lo_q": lo_q, "hi_q": hi_q},
        "points": points,
        "segments": segments,
        "band": {"x0": x0, "x1": x1, "y_top": band_top, "y_bottom": band_bottom},
        "peak": {
            "x": None if peak_index is None else xs[peak_index],
            "y": None if peak_q is None else value_to_pixel(peak_q, lo_q, hi_q, plot["top"], plot["plot_height"]),
            "value_q": peak_q,
        },
        "thresholds": thresholds,
        "regions": regions,
        "window": {
            "start_row": rows[first][0],
            "end_row": rows[last][0],
            "n_points": n_rows,
            "pad_rows": pad_rows,
        },
    }


def small_multiples_layout(rows_by_series, episodes_by_series, width, height, gap_threshold_ms=None):
    """One compact chart per series, sharing the main view's row-index -> pixel map (M4)."""
    layouts = []
    for series_id in sorted(rows_by_series):
        layouts.append(
            {
                "series_id": series_id,
                "layout": main_series_layout(
                    rows_by_series[series_id],
                    episodes_by_series.get(series_id, ()),
                    width,
                    height,
                    gap_threshold_ms,
                ),
            }
        )
    return layouts


# ---------------------------------------------------------------------------
# Density strip
# ---------------------------------------------------------------------------


def density_bins(rows_by_series, episodes_by_series, heat_bin_ms):
    """Episode coverage per fixed time bin, as an integer ratio over valid points (M4).

    Bins are cut from the global timeline (`heat_bin_ms` wide, from the earliest sample). A valid
    (present) point is *covered* when some episode of its own series spans its timestamp; the
    denominator is the bin's valid-point count, so a bin whose samples are all missing reports
    "no data" rather than 0% or 100% by accident. The ratio is a fixed-point integer
    (`canon.quantize`): the strip is a product surface, and products carry no float (K3).
    """
    stamps = [row[1] for rows in rows_by_series.values() for row in rows]
    if not stamps:
        return []
    first = min(stamps)
    last = max(stamps)
    n_bins = (last - first) // heat_bin_ms + 1
    valid = [0] * n_bins
    covered = [0] * n_bins

    for series_id in sorted(rows_by_series):
        rows = rows_by_series[series_id]
        ranges = _episode_ms_ranges(rows, episodes_by_series.get(series_id, ()))
        for row in rows:
            if row[2] is None:
                continue
            index = (row[1] - first) // heat_bin_ms
            valid[index] += 1
            for start, end in ranges:
                if start <= row[1] <= end:
                    covered[index] += 1
                    break

    bins = []
    for index in range(n_bins):
        total = valid[index]
        ratio_q = canon.quantize(_ratio(covered[index], total), QUANT_DECIMALS) if total else 0
        bins.append(
            {
                "bin_index": index,
                "start_ms": first + index * heat_bin_ms,
                "end_ms": first + (index + 1) * heat_bin_ms - 1,
                "n_valid": total,
                "n_covered": covered[index],
                "coverage_q": ratio_q,
            }
        )
    return bins


def _ratio(part, total):
    if not total:
        return 0.0
    return part / total


def _episode_ms_ranges(rows, episodes):
    """`[(start_ms, end_ms)]` for episodes, resolved through the physical row numbers.

    Episode records carry ISO timestamps (K5) and physical `start_row`/`end_row`; the row numbers
    are the natural key back into the parsed series, so no ISO parsing (and no timezone database) is
    added to the render path.
    """
    ms_by_row = dict((row[0], row[1]) for row in rows)
    ranges = []
    for episode in episodes:
        start = ms_by_row.get(episode["start_row"])
        end = ms_by_row.get(episode["end_row"])
        if start is None or end is None:
            continue
        if end < start:
            start, end = end, start
        ranges.append((start, end))
    return ranges
