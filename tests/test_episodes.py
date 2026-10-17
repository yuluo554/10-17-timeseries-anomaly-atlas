"""M2 episode tests: the merge boundary, the severity key's four tie-breaks, and ids.

Every test here builds its own detections by hand, so the expected episode is computed by reading
the assertion rather than by re-running the code under test. The merge boundary is pinned at the
exact millisecond (`<= max_gap_ms` merges, `+1` splits) because that is the one place where K7's
"time domain, not point count" promise is decided.
"""

import pytest

from anomaly_atlas import episodes

MAX_GAP = 1800000  # 30 minutes, the pinned default (plan/06 P4)
CADENCE = 300000


def _points(*triples):
    """`(epoch_ms, row_no, score)` tuples in the order given."""
    return [(epoch_ms, row_no, score) for epoch_ms, row_no, score in triples]


def _merge(points, max_gap=MAX_GAP, decimals=6):
    return episodes.merge_episodes("series", "detector", {"k": "3.500000"}, points, max_gap, decimals)


class TestMergeBoundary:
    def test_a_gap_equal_to_max_gap_merges_into_one_episode(self):
        merged = _merge(_points((0, 2, 4.0), (MAX_GAP, 5, 5.0)))
        assert len(merged) == 1
        assert merged[0]["n_points"] == 2
        assert merged[0]["duration_ms"] == MAX_GAP
        assert merged[0]["start_row"] == 2
        assert merged[0]["end_row"] == 5

    def test_one_millisecond_more_splits_into_two(self):
        split = _merge(_points((0, 2, 4.0), (MAX_GAP + 1, 5, 5.0)))
        assert len(split) == 2
        assert [episode["n_points"] for episode in split] == [1, 1]
        assert [episode["duration_ms"] for episode in split] == [0, 0]

    def test_chained_points_split_at_the_first_wide_gap(self):
        merged = _merge(
            _points((0, 2, 4.0), (MAX_GAP, 5, 5.0), (2 * MAX_GAP + CADENCE, 8, 6.0))
        )
        assert [episode["start_row"] for episode in merged] == [2, 8]
        assert [episode["n_points"] for episode in merged] == [2, 1]

    def test_identical_timestamps_merge_and_keep_the_row_order(self):
        merged = _merge(_points((0, 7, 3.0), (0, 8, 9.0)))
        assert len(merged) == 1
        assert merged[0]["duration_ms"] == 0
        assert merged[0]["start_row"] == 7 and merged[0]["end_row"] == 8

    def test_the_peak_of_an_episode_is_the_largest_score(self):
        merged = _merge(_points((0, 2, 4.0), (CADENCE, 5, 9.25), (2 * CADENCE, 8, 5.0)))
        assert merged[0]["peak_score_q"] == 9250000

    def test_a_single_point_episode_is_legal(self):
        merged = _merge(_points((CADENCE, 5, 3.5)))
        assert len(merged) == 1
        assert merged[0]["n_points"] == 1
        assert merged[0]["duration_ms"] == 0

    def test_no_points_means_no_episodes(self):
        assert _merge([]) == []

    def test_peak_score_is_fixed_point_quantised(self):
        merged = _merge(_points((0, 2, 3.5000006)))
        assert merged[0]["peak_score_q"] == 3500001
        tie = _merge(_points((0, 2, 3.5000005)))
        assert tie[0]["peak_score_q"] == 3500000  # half to even

    def test_timestamps_are_written_as_fixed_form_iso_strings(self):
        merged = _merge(_points((1709164800000, 2, 4.0), (1709164800000 + CADENCE, 5, 4.0)))
        assert merged[0]["start"] == "2024-02-29T00:00:00.000Z"
        assert merged[0]["end"] == "2024-02-29T00:05:00.000Z"

    def test_threshold_ref_is_carried_onto_every_episode(self):
        merged = _merge(_points((0, 2, 4.0), (MAX_GAP + 1, 5, 4.0)))
        assert [episode["threshold_ref"] for episode in merged] == [{"k": "3.500000"}] * 2


def _episode(peak_q, duration_ms, start_row, detector="rolling_mad_z", series_id="series"):
    return {
        "episode_id": "",
        "series_id": series_id,
        "detector": detector,
        "start": "2024-02-29T00:00:00.000Z",
        "end": "2024-02-29T00:00:00.000Z",
        "duration_ms": duration_ms,
        "peak_score_q": peak_q,
        "n_points": 1,
        "start_row": start_row,
        "end_row": start_row,
        "threshold_ref": {},
    }


class TestSeverityOrdering:
    """K6: peak_score_q desc -> duration_ms desc -> start_row asc -> detector lexicographic."""

    def test_higher_peak_comes_first(self):
        ordered = episodes.order_episodes([_episode(100, 0, 2), _episode(200, 0, 5)])
        assert [episode["peak_score_q"] for episode in ordered] == [200, 100]

    def test_equal_peaks_prefer_the_longer_episode(self):
        ordered = episodes.order_episodes([_episode(200, 10, 2), _episode(200, 20, 5)])
        assert [episode["duration_ms"] for episode in ordered] == [20, 10]

    def test_equal_peak_and_duration_prefer_the_earlier_row(self):
        ordered = episodes.order_episodes([_episode(200, 20, 99), _episode(200, 20, 5)])
        assert [episode["start_row"] for episode in ordered] == [5, 99]

    def test_full_tie_is_broken_by_detector_name(self):
        ordered = episodes.order_episodes(
            [_episode(200, 20, 5, "rolling_mad_z"), _episode(200, 20, 5, "rules.cusum")]
        )
        assert [episode["detector"] for episode in ordered] == ["rolling_mad_z", "rules.cusum"]

    def test_the_key_is_integers_and_strings_only(self):
        for episode in (_episode(200, 20, 5), _episode(199999, 0, 5, "rules.zero_run")):
            for part in episodes.severity_key(episode):
                assert isinstance(part, (int, str))
                assert not isinstance(part, bool)

    def test_ordering_does_not_depend_on_input_order(self):
        pool = [
            _episode(100, 10, 3, "rolling_iqr"),
            _episode(200, 0, 9, "rules.cusum"),
            _episode(200, 10, 5, "rolling_mad_z"),
            _episode(200, 10, 5, "rules.missing_run"),
        ]
        forward = [(e["peak_score_q"], e["duration_ms"], e["start_row"], e["detector"]) for e in episodes.order_episodes(pool)]
        backward = [
            (e["peak_score_q"], e["duration_ms"], e["start_row"], e["detector"])
            for e in episodes.order_episodes(list(reversed(pool)))
        ]
        assert forward == backward
        assert forward == [
            (200, 10, 5, "rolling_mad_z"),
            (200, 10, 5, "rules.missing_run"),
            (200, 0, 9, "rules.cusum"),
            (100, 10, 3, "rolling_iqr"),
        ]


class TestEpisodeIds:
    def test_ids_number_each_series_separately_in_severity_order(self):
        assigned = episodes.assign_ids(
            episodes.order_episodes(
                [
                    _episode(100, 0, 40, series_id="a"),
                    _episode(300, 0, 10, series_id="a"),
                    _episode(200, 0, 70, series_id="b"),
                ]
            )
        )
        assert [(e["series_id"], e["episode_id"]) for e in assigned] == [
            ("a", "a-E001"),
            ("b", "b-E001"),
            ("a", "a-E002"),
        ]

    def test_numbering_starts_at_one_and_uses_three_digits(self):
        assigned = episodes.assign_ids(episodes.order_episodes([_episode(100, 0, 2, series_id="hm")]))
        assert assigned[0]["episode_id"] == "hm-E001"

    def test_ids_are_stable_for_a_repeated_run(self):
        pool = [_episode(2, 0, 4, "rolling_iqr"), _episode(2, 0, 4, "rolling_mad_z")]
        first = [e["episode_id"] for e in episodes.assign_ids(episodes.order_episodes(list(pool)))]
        second = [e["episode_id"] for e in episodes.assign_ids(episodes.order_episodes(list(pool)))]
        assert first == second


class TestBuildEpisodes:
    def _rows(self):
        return {"b": [(), (), ()], "a": [(), ()]}

    def test_it_sorts_detections_by_time_not_by_caller_order(self):
        detections = {
            ("a", "rolling_mad_z"): [(2 * CADENCE, 9, 4.0), (0, 3, 4.0), (CADENCE, 6, 4.0)],
        }
        built = episodes.build_episodes(self._rows(), detections, {"rolling_mad_z": {}}, MAX_GAP, 6)
        assert len(built) == 1
        assert built[0]["start_row"] == 3 and built[0]["end_row"] == 9

    def test_two_detectors_never_merge_into_one_episode(self):
        detections = {
            ("a", "rolling_mad_z"): [(0, 3, 4.0)],
            ("a", "rules.cusum"): [(0, 3, 4.0)],
        }
        built = episodes.build_episodes(self._rows(), detections, {}, MAX_GAP, 6)
        assert len(built) == 2
        assert sorted(episode["detector"] for episode in built) == ["rolling_mad_z", "rules.cusum"]

    def test_an_empty_detection_bucket_produces_nothing(self):
        built = episodes.build_episodes(self._rows(), {("a", "rolling_iqr"): []}, {}, MAX_GAP, 6)
        assert built == []

    def test_unknown_detector_falls_back_to_an_empty_threshold_ref(self):
        built = episodes.build_episodes(
            self._rows(), {("a", "rules.zero_run"): [(0, 3, 6.0)]}, {}, MAX_GAP, 6
        )
        assert built[0]["threshold_ref"] == {}
