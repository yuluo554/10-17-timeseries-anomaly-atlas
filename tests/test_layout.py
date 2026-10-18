"""M4 layout tests: deterministic integer geometry, the three region textures, and the bins.

`layout.py` is the module the artifact's *shape* comes from, so the properties pinned here are the
ones a reader of the picture depends on: every coordinate is an integer and the same input yields
the same integers (no float, no clock, no randomness), the main view and the small multiples share
one row-index -> pixel map, the y axis grows to hold the anomaly band rather than clipping it, and
the three abnormal-region kinds stay distinguishable *by structure* so a black-and-white print still
tells them apart (plan/06 P5).

The falsification side lives here too: a synthetic series is built where the expected bin coverage,
the expected threshold line and the expected region classification are known by construction, so the
checks are comparing against arithmetic that was done on paper, not against whatever the module
happened to return.
"""

import pytest

from anomaly_atlas import csvio, detect, layout, profile

from conftest import SERIES_CSV, iter_floats


@pytest.fixture(scope="module")
def frozen():
    parsed = csvio.load_series(SERIES_CSV)
    resolved = detect.resolve_spec()
    run_document, anomaly_set, _detections = detect.detect_all_detailed(parsed, resolved)
    profile_document = profile.build_profile(parsed)
    gap_thresholds = dict(
        (series["series_id"], series["cadence"]["gap_threshold_ms"])
        for series in profile_document["series"]
    )
    episodes_by_series = {}
    for episode in anomaly_set["episodes"]:
        episodes_by_series.setdefault(episode["series_id"], []).append(episode)
    return parsed, profile_document, gap_thresholds, episodes_by_series


def _rows(pairs, start_row=1, start_ms=1700000000000, step_ms=300000):
    """`[(value, ...)]` -> `[(row_no, epoch_ms, value)]`, one physical row apart per sample."""
    return [
        (start_row + index, start_ms + index * step_ms, value)
        for index, value in enumerate(pairs)
    ]


class TestRenderSpec:
    def test_defaults_are_pinned_as_literals(self):
        # Read as a literal on purpose: an assertion that reads its expectation out of the document
        # it checks agrees with whatever the default became.
        assert layout.DEFAULT_RENDER_SPEC == {"pad_rows": 6, "heat_bin_ms": 3600000}
        assert layout.resolve_render_spec() == layout.DEFAULT_RENDER_SPEC

    def test_an_unknown_key_is_rejected(self):
        with pytest.raises(KeyError):
            layout.resolve_render_spec({"pad_row": 6})

    @pytest.mark.parametrize("bad", ("6", 6.5, None, True))
    def test_a_non_integer_is_rejected(self, bad):
        with pytest.raises(ValueError):
            layout.resolve_render_spec({"pad_rows": bad})

    def test_an_integral_float_is_accepted(self):
        assert layout.resolve_render_spec({"pad_rows": 12.0})["pad_rows"] == 12

    def test_degenerate_windows_are_rejected(self):
        with pytest.raises(ValueError):
            layout.resolve_render_spec({"pad_rows": -1})
        with pytest.raises(ValueError):
            layout.resolve_render_spec({"heat_bin_ms": 0})


class TestTheFixedMaps:
    def test_row_to_pixel_is_the_same_map_in_both_views(self):
        # The one rule the main view and the small multiples must share, spelled out as arithmetic:
        # x = left + index * width // (n - 1), integer division only.
        assert layout.row_to_pixel(0, 11, 10, 500) == 10
        assert layout.row_to_pixel(10, 11, 10, 500) == 510
        assert layout.row_to_pixel(5, 11, 10, 500) == 10 + 5 * 500 // 10
        for index in range(11):
            assert isinstance(layout.row_to_pixel(index, 11, 10, 500), int)

    def test_a_single_row_lands_in_the_middle(self):
        assert layout.row_to_pixel(0, 1, 10, 500) == 10 + 250

    def test_the_map_is_non_decreasing(self):
        xs = [layout.row_to_pixel(index, 987, 62, 866) for index in range(987)]
        assert xs == sorted(xs)

    def test_value_bounds_grow_past_the_data_and_never_collapse(self):
        # Literal arithmetic: 4% of the span on both sides (Y_PAD_PPM = 40000), so the frame grows
        # with the data instead of clipping an excursion. Pinned as numbers, not as inequalities: a
        # pad of one unit would satisfy "the data is inside the frame" and still be a broken axis.
        assert layout.value_bounds([0, 1000000]) == (-40000, 1040000)
        assert layout.value_bounds([-2000000, 0]) == (-2080000, 80000)
        low, high = layout.value_bounds([5000, 5000])
        assert low < 5000 < high
        assert layout.value_bounds([None, None, None]) == (0, layout.MIN_SPAN_Q)

    def test_value_to_pixel_is_inverted_and_clamped(self):
        top, height = 10, 200
        high = layout.value_to_pixel(1000, 0, 1000, top, height)
        low = layout.value_to_pixel(0, 0, 1000, top, height)
        assert (high, low) == (top, top + height)
        assert layout.value_to_pixel(500, 0, 1000, top, height) == top + height // 2


class TestRegionClassification:
    def test_the_frozen_series_have_one_of_each_kind(self, frozen):
        parsed, profile_document, gap_thresholds, _episodes = frozen
        expected = dict(
            (series["series_id"], series) for series in profile_document["series"]
        )
        for series_id in sorted(parsed.rows_by_series):
            spans = layout.region_spans(
                parsed.rows_by_series[series_id], gap_thresholds[series_id]
            )
            kinds = [span["kind"] for span in spans]
            assert kinds.count(layout.KIND_GAP) == 1, kinds
            assert kinds.count(layout.KIND_ZERO) == 1, kinds
            assert kinds.count(layout.KIND_MISSING) == 1, kinds
            gap = [span for span in spans if span["kind"] == layout.KIND_GAP][0]
            assert gap["n_points"] == expected[series_id]["gaps"][0]["missing_points"]

    def test_a_gap_needs_no_impossible_comparison_with_the_gap_factor(self):
        # A gap is defined by the timeline alone: with a threshold of 3*step, the 4-step hole below
        # is a gap and the 3-step hole is not (the profile's `>` comparison, mirrored).
        rows = _rows([1.0, 2.0, 3.0, None, 5.0, 6.0, 7.0])
        rows[3] = (rows[3][0], rows[2][1] + 4 * 300000, None)
        rows[6] = (rows[6][0], rows[5][1] + 3 * 300000, 7.0)
        spans = layout.region_spans(rows, 3 * 300000)
        gaps = [span for span in spans if span["kind"] == layout.KIND_GAP]
        assert len(gaps) == 1
        assert gaps[0]["start_index"] == 2 and gaps[0]["end_index"] == 3

    def test_zero_and_missing_runs_are_maximal_and_disjoint(self):
        rows = _rows([1.0, 0.0, 0.0, None, None, 3.0, 0.0])
        spans = layout.region_spans(rows, 10 ** 9)
        assert [(span["kind"], span["start_index"], span["end_index"]) for span in spans] == [
            (layout.KIND_ZERO, 1, 2),
            (layout.KIND_MISSING, 3, 4),
            (layout.KIND_ZERO, 6, 6),
        ]

    def test_a_zero_and_a_missing_run_cannot_share_a_row(self):
        # The disjointness assertion is load-bearing, not decoration: an overlapping pair would make
        # "which texture is this?" unanswerable, so the module refuses to build rather than guess.
        rows = _rows([0.0, None])
        spans = layout.region_spans(rows, 10 ** 9)
        assert [span["kind"] for span in spans] == [layout.KIND_ZERO, layout.KIND_MISSING]


class TestMainSeriesLayout:
    def test_every_coordinate_is_an_integer(self, frozen):
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        for series_id in sorted(parsed.rows_by_series):
            document = layout.main_series_layout(
                parsed.rows_by_series[series_id],
                episodes_by_series[series_id],
                940,
                268,
                gap_thresholds[series_id],
            )
            assert list(iter_floats(document)) == []

    def test_the_same_input_gives_the_same_geometry(self, frozen):
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        series_id = "temperature"
        first = layout.main_series_layout(
            parsed.rows_by_series[series_id], episodes_by_series[series_id], 940, 268, gap_thresholds[series_id]
        )
        second = layout.main_series_layout(
            parsed.rows_by_series[series_id], episodes_by_series[series_id], 940, 268, gap_thresholds[series_id]
        )
        assert first == second

    def test_the_y_axis_contains_every_anomalous_value(self, frozen):
        # The frame grows to hold the anomaly band: the padding exists so the peak markers and the
        # band rectangles are inside the picture, not clipped by it.
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        series_id = "energy_kwh"
        rows = parsed.rows_by_series[series_id]
        document = layout.main_series_layout(
            rows, episodes_by_series[series_id], 940, 268, gap_thresholds[series_id]
        )
        values = [row[2] for row in rows if row[2] is not None]
        assert document["value_bounds"]["lo_q"] < min(values)
        assert document["value_bounds"]["hi_q"] > max(values)
        index_by_row = dict((row[0], index) for index, row in enumerate(rows))
        for band in document["bands"]:
            assert band["y_top"] >= document["frame"]["top"]
            assert band["y_bottom"] <= document["frame"]["bottom"]
            if band["has_values"]:
                assert band["peak_value_q"] is not None

    def test_a_gap_is_widened_to_its_absent_sample_count(self, frozen):
        # The x axis is row index, so a timeline hole is one pixel wide unless the band is widened
        # by the row slots the absent samples would have occupied. Both the gap and the missing run
        # therefore read as bands, and they read as *different* bands.
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        series_id = "humidity"
        gap_threshold = gap_thresholds[series_id]
        rows = parsed.rows_by_series[series_id]
        document = layout.main_series_layout(rows, episodes_by_series[series_id], 940, 268, gap_threshold)
        by_kind = dict((region["kind"], region) for region in document["regions"])
        assert set(by_kind) == {layout.KIND_GAP, layout.KIND_ZERO, layout.KIND_MISSING}
        assert by_kind[layout.KIND_GAP]["x1"] - by_kind[layout.KIND_GAP]["x0"] > layout.MIN_X_SPAN
        assert by_kind[layout.KIND_GAP]["stripes"], "a gap must carry explicit stripe geometry"
        assert by_kind[layout.KIND_ZERO]["rungs"], "a zero run must carry explicit rungs"
        assert not by_kind[layout.KIND_MISSING]["stripes"]
        assert not by_kind[layout.KIND_MISSING]["rungs"]

    def test_the_three_kinds_are_drawn_with_three_different_structures(self, frozen):
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        document = layout.main_series_layout(
            parsed.rows_by_series["temperature"],
            episodes_by_series["temperature"],
            940,
            268,
            gap_thresholds["temperature"],
        )
        shapes = {}
        for region in document["regions"]:
            shapes[region["kind"]] = (
                len(region["stripes"]) > 0,
                len(region["rungs"]) > 0,
                region["y_top"],
                region["y_bottom"],
            )
        # Slanted stripes / vertical rungs / neither: three distinct signatures, which is what keeps
        # them apart in colourless print.
        assert shapes[layout.KIND_GAP][:2] == (True, False)
        assert shapes[layout.KIND_ZERO][:2] == (False, True)
        assert shapes[layout.KIND_MISSING][:2] == (False, False)


class TestThresholdLinesComeFromTheReference:
    def test_a_z_detector_yields_the_median_plus_k_scale(self):
        # Hand arithmetic, pinned as literals: the window is the trailing 24 samples ending at the
        # peak row, i.e. all nine values here. Sorted, the median is 11 and the MAD is 1 (four
        # values sit 1 away from it, four sit on it, and the spike sits 29 away) -> scale = 1.4826.
        # upper = 11 + 3.5*1.4826 = 16.1891, lower = 11 - 5.1891 = 5.8109.
        rows = _rows([10.0, 11.0, 10.0, 11.0, 10.0, 11.0, 10.0, 11.0, 40.0])
        pairs = layout.threshold_values(
            rows, "rolling_mad_z", {"window": 24, "k": "3.500000", "min_valid": 6}, rows[8][0]
        )
        assert pairs == [("upper", 16189100), ("lower", 5810900)]
        # The line is derived, not hard-coded: with a different k it moves.
        assert layout.threshold_values(
            rows, "rolling_mad_z", {"window": 24, "k": "1.000000", "min_valid": 6}, rows[8][0]
        ) != pairs

    def test_the_window_lookback_comes_from_the_reference_block(self):
        # A shorter window sees only the flat tail, so the spike is not in it and the band narrows.
        rows = _rows([10.0, 11.0, 10.0, 11.0, 10.0, 11.0, 10.0, 11.0, 40.0])
        narrow = layout.threshold_values(
            rows, "rolling_mad_z", {"window": 4, "k": "3.500000", "min_valid": 6}, rows[8][0]
        )
        wide = layout.threshold_values(
            rows, "rolling_mad_z", {"window": 24, "k": "3.500000", "min_valid": 6}, rows[8][0]
        )
        assert narrow != wide

    def test_an_iqr_detector_yields_the_quartile_fences(self):
        rows = _rows([10.0, 12.0, 14.0, 16.0, 18.0, 20.0])
        pairs = dict(
            layout.threshold_values(
                rows, "rolling_iqr", {"window": 24, "iqr_mult": "3.000000", "min_valid": 6}, rows[5][0]
            )
        )
        values = [row[2] for row in rows]
        q1 = detect._quantile(values, 0.25)
        q3 = detect._quantile(values, 0.75)
        assert pairs["upper"] == layout.canon.quantize(q3 + 3.0 * (q3 - q1), layout.QUANT_DECIMALS)
        assert pairs["lower"] == layout.canon.quantize(q1 - 3.0 * (q3 - q1), layout.QUANT_DECIMALS)

    def test_a_static_threshold_yields_the_configured_levels(self):
        rows = _rows([1.0, 2.0, 3.0])
        assert layout.threshold_values(
            rows, "rules.static_threshold", {"static_threshold": "25.500000"}, rows[2][0]
        ) == [("upper", 25500000), ("lower", -25500000)]

    @pytest.mark.parametrize(
        "detector",
        ("rules.cusum", "rules.pct_jump", "rules.missing_run", "rules.zero_run"),
    )
    def test_a_rule_without_a_value_threshold_yields_no_line(self, detector):
        rows = _rows([1.0, 2.0, 3.0])
        assert layout.threshold_values(rows, detector, {"cusum_h": "5.000000"}, rows[1][0]) == []

    def test_a_missing_peak_row_yields_no_line(self):
        rows = _rows([1.0, 2.0])
        assert layout.threshold_values(rows, "rolling_mad_z", {"window": 24, "k": "3.500000"}, 999) == []


class TestEpisodeZoomLayout:
    def test_the_window_is_the_episode_plus_pad_clipped_to_the_series(self, frozen):
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        rows = parsed.rows_by_series["humidity"]
        episode = episodes_by_series["humidity"][0]
        document = layout.episode_zoom_layout(rows, episode, 6, 430, 132, gap_thresholds["humidity"])
        assert document["window"]["pad_rows"] == 6
        assert document["window"]["n_points"] == 21
        assert document["window"]["start_row"] >= rows[0][0]

    def test_a_pad_wider_than_the_series_is_clipped(self):
        rows = _rows([1.0, 5.0, 2.0])
        episode = {
            "episode_id": "s-E001",
            "start_row": rows[1][0],
            "end_row": rows[1][0],
            "detector": "rolling_mad_z",
            "threshold_ref": {"window": 24, "k": "3.500000"},
        }
        document = layout.episode_zoom_layout(rows, episode, 50, 430, 132, 10 ** 9)
        assert document["window"]["n_points"] == 3

    def test_the_peak_is_the_highest_value_inside_the_episode(self, frozen):
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        rows = parsed.rows_by_series["temperature"]
        for episode in episodes_by_series["temperature"][:12]:
            document = layout.episode_zoom_layout(rows, episode, 6, 430, 132, gap_thresholds["temperature"])
            index_by_row = dict((row[0], index) for index, row in enumerate(rows))
            values = [
                row[2]
                for row in rows[index_by_row[episode["start_row"]] : index_by_row[episode["end_row"]] + 1]
                if row[2] is not None
            ]
            if not values:
                assert document["peak"]["value_q"] is None
                continue
            assert document["peak"]["value_q"] == layout.canon.quantize(max(values), layout.QUANT_DECIMALS)

    def test_a_flat_episode_still_gets_a_visible_band(self, frozen):
        # The zero-run episode of humidity is nine samples that are all exactly 0.0: its value range
        # has zero height, so the band would read as a one-pixel artefact without the minimum height.
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        episodes = [
            episode
            for episode in episodes_by_series["humidity"]
            if episode["detector"] == "rolling_mad_z"
        ]
        flat = [episode for episode in episodes if episode["n_points"] > 4][0]
        document = layout.episode_zoom_layout(
            parsed.rows_by_series["humidity"], flat, 6, 430, 132, gap_thresholds["humidity"]
        )
        assert document["band"]["y_bottom"] - document["band"]["y_top"] >= layout.MIN_BAND_HEIGHT

    def test_a_missing_run_episode_has_no_peak_and_no_threshold_line(self, frozen):
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        episodes = [
            episode
            for episode in episodes_by_series["temperature"]
            if episode["detector"] == "rules.missing_run"
        ]
        assert episodes
        document = layout.episode_zoom_layout(
            parsed.rows_by_series["temperature"], episodes[0], 6, 430, 132, gap_thresholds["temperature"]
        )
        assert document["peak"]["value_q"] is None
        assert document["thresholds"] == []
        assert document["band"] == {
            "x0": document["band"]["x0"],
            "x1": document["band"]["x1"],
            "y_top": document["frame"]["top"],
            "y_bottom": document["frame"]["bottom"],
        }

    def test_an_episode_pointing_outside_the_series_is_an_error(self):
        rows = _rows([1.0, 2.0])
        with pytest.raises(KeyError):
            layout.episode_zoom_layout(
                rows,
                {"episode_id": "s-E001", "start_row": 42, "end_row": 42, "detector": "rules.cusum"},
                2,
                430,
                132,
                None,
            )


class TestDensityBins:
    def test_the_bins_tile_the_timeline(self, frozen):
        parsed, _profile, _gap_thresholds, episodes_by_series = frozen
        bins = layout.density_bins(parsed.rows_by_series, episodes_by_series, 3600000)
        stamps = [row[1] for rows in parsed.rows_by_series.values() for row in rows]
        assert len(bins) == (max(stamps) - min(stamps)) // 3600000 + 1
        assert bins[0]["start_ms"] == min(stamps)
        for index, item in enumerate(bins):
            assert item["bin_index"] == index
            assert item["start_ms"] == bins[0]["start_ms"] + index * 3600000

    def test_the_denominator_is_the_valid_point_count(self, frozen):
        parsed, _profile, _gap, episodes_by_series = frozen
        bins = layout.density_bins(parsed.rows_by_series, episodes_by_series, 3600000)
        present = sum(
            1 for rows in parsed.rows_by_series.values() for row in rows if row[2] is not None
        )
        assert sum(item["n_valid"] for item in bins) == present
        for item in bins:
            assert 0 <= item["n_covered"] <= item["n_valid"]
            if item["n_valid"] == 0:
                assert item["coverage_q"] == 0
            assert 0 <= item["coverage_q"] <= 1000000
            assert isinstance(item["coverage_q"], int)

    def test_an_empty_bin_is_reported_as_no_data_not_as_zero_coverage(self, frozen):
        parsed, _profile, _gap, episodes_by_series = frozen
        bins = layout.density_bins(parsed.rows_by_series, episodes_by_series, 60000)
        assert any(item["n_valid"] == 0 for item in bins)

    def test_coverage_is_arithmetic_not_a_guess(self):
        # One series, 4 samples 300 s apart, 600 s bins: two bins of two samples each, and an
        # episode covering the middle two samples covers exactly one sample per bin.
        rows = _rows([1.0, 2.0, 3.0, 4.0])
        episode = {"start_row": rows[1][0], "end_row": rows[2][0]}
        bins = layout.density_bins({"s": rows}, {"s": [episode]}, 600000)
        assert len(bins) == 2
        assert [(item["n_valid"], item["n_covered"]) for item in bins] == [(2, 1), (2, 1)]
        assert bins[0]["coverage_q"] == 500000

    def test_halving_the_bin_width_splits_every_bin(self, frozen):
        # The bin width is the only thing that moves the partition: at half the width every coarse
        # bin is two fine bins, and the valid-point counts add up. The fine grid can be one bin
        # shorter than twice the coarse grid, because the last bin is cut by the last sample rather
        # than by a whole width -- that is the fixed rule, spelled out instead of assumed.
        parsed, _profile, _gap, episodes_by_series = frozen
        coarse = layout.density_bins(parsed.rows_by_series, episodes_by_series, 3600000)
        fine = layout.density_bins(parsed.rows_by_series, episodes_by_series, 1800000)
        assert len(fine) in (2 * len(coarse), 2 * len(coarse) - 1)
        for index, item in enumerate(coarse):
            halves = [fine[2 * index]["n_valid"]]
            if 2 * index + 1 < len(fine):
                halves.append(fine[2 * index + 1]["n_valid"])
            assert item["n_valid"] == sum(halves)


class TestSmallMultiples:
    def test_one_chart_per_series_sharing_the_row_map(self, frozen):
        parsed, _profile, gap_thresholds, episodes_by_series = frozen
        layouts = layout.small_multiples_layout(
            parsed.rows_by_series, episodes_by_series, 940, 92, None
        )
        assert [entry["series_id"] for entry in layouts] == sorted(parsed.rows_by_series)
        for entry in layouts:
            main = layout.main_series_layout(
                parsed.rows_by_series[entry["series_id"]],
                episodes_by_series[entry["series_id"]],
                940,
                268,
                gap_thresholds[entry["series_id"]],
            )
            first = entry["layout"]["x_ticks"][0]["x"]
            last = entry["layout"]["x_ticks"][-1]["x"]
            assert (first, last) == (main["x_ticks"][0]["x"], main["x_ticks"][-1]["x"])
