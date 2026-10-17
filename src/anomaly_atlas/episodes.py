"""Episode merging, severity ordering and id assignment (M2, K6/K7).

API:
  merge_episodes(series_id, detector, threshold_ref, points, max_gap_ms, decimals) -> list[dict]
  order_episodes(episodes) -> list[dict]            # severity key, integers/strings only
  assign_ids(episodes) -> list[dict]                # '<series_id>-E<NNN>'
  build_episodes(rows_by_series, detections, threshold_refs, max_gap_ms, decimals) -> list[dict]

Merging is time-domain (`max_gap_ms`): two neighbouring anomalous points join one episode when
their timestamps are at most `max_gap_ms` apart. Point-count distance would fuse two unrelated
episodes across a data gap -- the semantics of the gap say "no samples here", not "nothing
happened here" (plan/06 D10), so the merge rule never looks at indices.

Severity ordering uses the fixed-point integer score, never the raw float: two scores that differ
in the 12th decimal can order differently in CPython and in V8, which would move episode ids and
change the archive fingerprint for a difference nobody can see (K6/D12).
"""

from .timebase import epoch_ms_to_iso

# The severity key, in the order the tie-breaks are applied (data/README 4.2). Every component is
# an integer or a string, and the tuple is a *total* order: within one series a detector can flag
# a given row once, so two episodes never share (peak_score_q, duration_ms, start_row, detector).
def severity_key(episode):
    return (
        -episode["peak_score_q"],
        -episode["duration_ms"],
        episode["start_row"],
        episode["detector"],
    )


def merge_episodes(series_id, detector, threshold_ref, points, max_gap_ms, decimals):
    """Group one detector's anomalous points of one series into episodes.

    `points` is `[(epoch_ms, row_no, score)]` in time order (row number breaks timestamp ties).
    The peak score is kept as a fixed-point integer (`canon.quantize`), so the severity key and
    the fingerprint never carry a raw float.
    """
    episodes = []
    current = []
    for point in points:
        if current and point[0] - current[-1][0] > max_gap_ms:
            episodes.append(_finish(series_id, detector, threshold_ref, current, decimals))
            current = []
        current.append(point)
    if current:
        episodes.append(_finish(series_id, detector, threshold_ref, current, decimals))
    return episodes


def _finish(series_id, detector, threshold_ref, points, decimals):
    """Turn one merged run of anomalous points into an episode record."""
    from . import canon

    peak = 0.0
    for point in points:
        if point[2] > peak:
            peak = point[2]
    start_ms = points[0][0]
    end_ms = points[-1][0]
    return {
        "episode_id": "",
        "series_id": series_id,
        "detector": detector,
        "start": epoch_ms_to_iso(start_ms),
        "end": epoch_ms_to_iso(end_ms),
        "duration_ms": end_ms - start_ms,
        "peak_score_q": canon.quantize(peak, decimals),
        "n_points": len(points),
        "start_row": points[0][1],
        "end_row": points[-1][1],
        "threshold_ref": threshold_ref,
    }


def order_episodes(episodes):
    """Sort by the severity key: most severe first (K6, integers and strings only)."""
    return sorted(episodes, key=severity_key)


def assign_ids(episodes):
    """Number the ordered episodes per series: '<series_id>-E<NNN>', 1-based.

    Numbering is per series so that adding a series does not renumber unrelated episodes -- a
    global counter would move every id when one series is added, and `episode_id` is what a
    report cites (D12).
    """
    seen = {}
    for episode in episodes:
        series_id = episode["series_id"]
        seen[series_id] = seen.get(series_id, 0) + 1
        episode["episode_id"] = "%s-E%03d" % (series_id, seen[series_id])
    return episodes


def build_episodes(rows_by_series, detections, threshold_refs, max_gap_ms, decimals):
    """Merge every detector's detections into the ordered, id-assigned episode list.

    `detections` maps `(series_id, detector)` to `[(epoch_ms, row_no, score)]`; the sequence is
    re-sorted here with the row number as the tie-break, so a caller cannot smuggle in an
    iteration-order dependency (plan/02 section 4.2).
    """
    episodes = []
    for series_id in sorted(rows_by_series):
        for detector in sorted(_detectors_for(detections, series_id)):
            points = sorted(detections[(series_id, detector)], key=lambda item: (item[0], item[1]))
            if not points:
                continue
            episodes.extend(
                merge_episodes(
                    series_id,
                    detector,
                    threshold_refs.get(detector, {}),
                    points,
                    max_gap_ms,
                    decimals,
                )
            )
    return assign_ids(order_episodes(episodes))


def _detectors_for(detections, series_id):
    return [key[1] for key in detections if key[0] == series_id]
