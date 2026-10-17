"""M2 detector tests: pinned defaults, per-detector semantics, the period estimator, the
frozen-fixture pipeline, and the `detect` CLI contract.

The per-detector tests build their inputs by hand and pin the expected score formula, so the
degenerate-window rules (MAD == 0, IQR == 0, a constant window) are checked against arithmetic
written out in the assertion rather than against whatever the implementation happens to do. The
STL tests use a C2-continuous cycle on purpose: against a cornered cycle the LOESS leaves slope
artefacts at the corners, and a test written on one of those would be measuring the wrong thing.
"""

import json
import os

import pytest

from anomaly_atlas import canon, cli, csvio, detect

from conftest import MINIMAL_CSV, SERIES_CSV, TRUTH_JSON, iter_floats, read_bytes, read_text

GOLDEN_ANOMALY_DIGEST = "6020a3d34b0228c9b0735d7b2d10aad67d3181d0cb02eb2a02d7fd864ef1b422"
FORBIDDEN_CLOCK_KEYS = {"generated", "generated_at", "created", "created_at", "built_at", "now"}


@pytest.fixture(scope="module")
def frozen():
    """The frozen fixture under the default spec: parsed, run document, anomaly set."""
    parsed = csvio.load_series(SERIES_CSV)
    run_document, anomaly_set = detect.detect_all(parsed, detect.resolve_spec())
    return parsed, run_document, anomaly_set


@pytest.fixture(scope="module")
def truth():
    return json.loads(read_text(TRUTH_JSON))


class TestDefaultsArePinned:
    """Every default is spelled out, so drifting one is a deliberate two-file edit."""

    def test_detector_defaults_are_exactly_these(self):
        assert detect.resolve_spec()["rolling_mad_z"] == {"window": 24, "k": 3.5, "min_valid": 6}
        assert detect.resolve_spec()["rolling_iqr"] == {"window": 24, "iqr_mult": 3.0, "min_valid": 6}
        assert detect.resolve_spec()["stl_resid_z"] == {
            "inner": 2,
            "outer": 1,
            "window": 24,
            "k": 3.5,
            "min_valid": 6,
        }
        assert detect.resolve_spec()["rules"] == {
            "static_threshold": None,
            "pct_jump": 0.35,
            "missing_run": 6,
            "cusum_k": 0.5,
            "cusum_h": 5.0,
        }

    def test_run_level_defaults_are_exactly_these(self):
        resolved = detect.resolve_spec()
        assert resolved["max_gap_ms"] == 1800000
        assert resolved["period_points"] is None
        assert resolved["period_reject_window"] == 121
        assert resolved["period_reject_sigma"] == 2.5

    def test_the_csv_contract_defaults_come_from_csvio(self):
        resolved = detect.resolve_spec()
        for key, value in csvio.DEFAULT_SPEC.items():
            assert resolved[key] == value

    def test_no_hidden_defaults_beyond_the_declared_tables(self):
        declared = set(csvio.DEFAULT_SPEC)
        for name, params in detect.DETECTOR_PARAMS:
            declared.add(name)
            assert set(detect.DEFAULT_SPEC[name]) == set(param for param, _kind in params)
        for param, _kind in detect.RUN_PARAMS:
            declared.add(param)
        assert set(detect.resolve_spec()) == declared

    def test_the_type_table_covers_every_declared_parameter(self):
        for (name, param), kind in detect.PARAM_TYPES.items():
            assert kind in ("int", "decimal", "nullable-int", "nullable-decimal"), (name, param)
        for name, params in detect.DETECTOR_PARAMS:
            for param, kind in params:
                assert detect.PARAM_TYPES[(name, param)] == kind


class TestSpecResolution:
    def test_nested_overrides_merge_without_dropping_siblings(self):
        resolved = detect.resolve_spec({"rolling_mad_z": {"k": 4.0}})
        assert resolved["rolling_mad_z"] == {"window": 24, "k": 4.0, "min_valid": 6}

    def test_unknown_top_level_key_is_rejected(self):
        with pytest.raises(KeyError):
            detect.resolve_spec({"nonsense": 1})

    def test_unknown_nested_key_is_rejected(self):
        with pytest.raises(KeyError):
            detect.resolve_spec({"rules": {"nonsense": 1}})

    def test_a_decimal_parameter_accepts_a_fixed_point_string(self):
        # run.json stores decimals as fixed strings, so the resolution path has to read its own
        # output back (a recomputation replays run.json verbatim).
        resolved = detect.resolve_spec({"rolling_mad_z": {"k": "3.500000"}})
        assert resolved["rolling_mad_z"]["k"] == 3.5

    def test_an_integer_parameter_rejects_a_fraction(self):
        with pytest.raises(ValueError):
            detect.resolve_spec({"rolling_mad_z": {"window": 24.5}})

    def test_an_integer_parameter_accepts_an_integral_float(self):
        assert detect.resolve_spec({"rolling_mad_z": {"window": 25.0}})["rolling_mad_z"]["window"] == 25

    def test_a_nullable_decimal_accepts_null(self):
        assert detect.resolve_spec({"rules": {"static_threshold": None}})["rules"]["static_threshold"] is None

    def test_a_non_nullable_decimal_rejects_null(self):
        with pytest.raises(ValueError):
            detect.resolve_spec({"rules": {"pct_jump": None}})

    def test_a_boolean_is_not_a_number(self):
        with pytest.raises(ValueError):
            detect.resolve_spec({"rolling_mad_z": {"window": True}})

    def test_a_detector_block_must_be_an_object(self):
        with pytest.raises(ValueError):
            detect.resolve_spec({"rolling_mad_z": 24})

    def test_resolution_is_idempotent(self):
        once = detect.resolve_spec({"rolling_mad_z": {"k": 4.0}, "max_gap_ms": 60})
        twice = detect.resolve_spec(once)
        assert twice == once


class TestDumpSpec:
    def test_decimals_become_fixed_point_strings_and_integers_stay_integers(self):
        dumped = detect.dump_spec(detect.resolve_spec())
        assert dumped["rolling_mad_z"] == {"window": 24, "k": "3.500000", "min_valid": 6}
        assert dumped["rules"]["pct_jump"] == "0.350000"
        assert dumped["rules"]["missing_run"] == 6
        assert dumped["rules"]["static_threshold"] is None
        assert dumped["max_gap_ms"] == 1800000
        assert dumped["period_reject_sigma"] == "2.500000"
        assert dumped["period_points"] is None

    def test_the_dumped_form_is_hashable_as_is(self):
        canon.assert_hashable(detect.dump_spec(detect.resolve_spec()))

    def test_every_caller_parameter_survives_the_round_trip(self):
        resolved = detect.resolve_spec()
        assert detect.resolve_spec(detect.dump_spec(resolved)) == resolved


class TestNumericPrimitives:
    def test_median_interpolates_between_the_middle_pair(self):
        assert detect._median([1, 2, 3, 4]) == 2.5
        assert detect._median([1, 2, 3]) == 2
        assert detect._median([5.0]) == 5.0
        assert detect._median([4, 1, 3, 2]) == 2.5

    def test_quantile_linear_interpolation(self):
        assert detect._quantile([1, 2, 3, 4], 0.25) == 1.75
        assert detect._quantile([1, 2, 3, 4], 0.75) == 3.25
        assert detect._quantile([1, 2, 3, 4], 0.5) == 2.5

    def test_median_and_quantile_refuse_an_empty_window(self):
        with pytest.raises(ValueError):
            detect._median([])
        with pytest.raises(ValueError):
            detect._quantile([], 0.5)

    def test_scale_is_mean_absolute_deviation_when_mad_is_zero(self):
        window = [0.0] * 11 + [4.0]
        scale, median_value = detect.robust_scale(window)
        assert median_value == 0.0
        assert scale == pytest.approx(detect.MAD_TO_SIGMA * 4.0 / 12.0)

    def test_a_constant_window_has_no_scale_at_all(self):
        assert detect.robust_scale([7.0] * 12) == (0.0, 7.0)

    def test_mad_scale_when_it_is_not_degenerate(self):
        scale, median_value = detect.robust_scale([1.0, 2.0, 3.0, 4.0, 5.0])
        assert median_value == 3.0
        assert scale == pytest.approx(detect.MAD_TO_SIGMA * 1.0)

    def test_sqrt_is_newton_iteration_not_the_power_operator(self):
        assert detect._sqrt(9.0) == pytest.approx(3.0)
        assert detect._sqrt(2.0) == pytest.approx(1.4142135623730951)
        assert detect._sqrt(0.0) == 0.0

    def test_next_odd(self):
        assert detect._next_odd(4) == 5
        assert detect._next_odd(5) == 5
        assert detect._next_odd(1) == 1
        assert detect._next_odd(0) == 1


class TestRollingMadZ:
    def test_a_spike_against_a_flat_window_is_flagged_by_the_mad_zero_fallback(self):
        values = [0.0] * 11 + [4.0]
        hits = detect.rolling_mad_z(values, 12, 3.5, 6)
        assert [index for index, _score in hits] == [11]
        # |x - median| / (1.4826 * mean absolute deviation) = 4 / (1.4826 * 4/12) = 12 / 1.4826
        assert hits[0][1] == pytest.approx(12.0 / detect.MAD_TO_SIGMA)

    def test_a_constant_window_cannot_judge_anything(self):
        assert detect.rolling_mad_z([7.0] * 30, 24, 3.5, 6) == []

    def test_a_linear_ramp_is_not_an_anomaly(self):
        # A ramp is locally linear, so no point is far from its window's median in scale units:
        # a robust detector that flagged ramps would flag every trend in real data.
        assert detect.rolling_mad_z([float(index) for index in range(40)], 24, 3.5, 6) == []

    def test_min_valid_gates_the_first_points(self):
        values = [0.0] * 7 + [9.0]
        assert len(detect.rolling_mad_z(values, 24, 3.5, 8)) == 1
        assert detect.rolling_mad_z(values, 24, 3.5, 9) == []

    def test_a_missing_value_is_never_a_candidate(self):
        assert detect.rolling_mad_z([None] * 8, 24, 3.5, 6) == []

    def test_missing_values_inside_the_window_do_not_break_the_scale(self):
        values = [0.0, None, 0.0, None, 0.0, None, 0.0, 0.0] + [4.0]
        hits = detect.rolling_mad_z(values, 12, 3.5, 4)
        assert [index for index, _score in hits] == [8]

    def test_a_larger_k_flags_no_more_points(self):
        values = [0.0] * 10 + [3.0] + [0.0] * 10
        loose = detect.rolling_mad_z(values, 12, 8.0, 6)
        tight = detect.rolling_mad_z(values, 12, 3.5, 6)
        assert set(index for index, _s in loose) <= set(index for index, _s in tight)

    def test_the_threshold_is_strictly_greater(self):
        # "|z| > k" is the documented rule, so a score exactly equal to k is *not* flagged. Taking
        # k from the implementation's own score keeps both sides on one expression: this measures
        # strictness instead of float equality of two separately computed values.
        values = [0.0] * 11 + [4.0]
        score = detect.rolling_mad_z(values, 12, 0.0, 6)[0][1]
        assert score > 0
        assert detect.rolling_mad_z(values, 12, score, 6) == []
        assert len(detect.rolling_mad_z(values, 12, score * 0.999999, 6)) == 1


class TestRollingIqr:
    def test_an_excursion_beyond_the_box_bound_is_flagged(self):
        values = [float(index) for index in range(1, 12)] + [100.0]
        hits = detect.rolling_iqr(values, 12, 3.0, 12)
        assert [index for index, _score in hits] == [11]
        # Q1 = 3.75, Q3 = 9.25 -> IQR 5.5, bound 25.75, score (100 - 25.75) / 5.5
        assert hits[0][1] == pytest.approx((100.0 - 25.75) / 5.5)

    def test_a_point_inside_the_box_is_not_flagged(self):
        assert detect.rolling_iqr([1.0, 2.0, 3.0, 4.0], 4, 3.0, 4) == []

    def test_a_degenerate_box_falls_back_to_the_mean_absolute_deviation(self):
        values = [0.0] * 11 + [4.0]
        hits = detect.rolling_iqr(values, 12, 3.0, 12)
        assert [index for index, _score in hits] == [11]
        assert hits[0][1] == pytest.approx(9.0, abs=1e-9)

    def test_an_all_zero_window_cannot_judge_anything(self):
        assert detect.rolling_iqr([0.0] * 20, 12, 3.0, 6) == []

    def test_min_valid_gates_the_first_points(self):
        values = [1.0, 1.0, 1.0, 1.0, 9.0]
        assert detect.rolling_iqr(values, 12, 1.0, 6) == []
        assert [index for index, _s in detect.rolling_iqr(values, 12, 1.0, 5)] == [4]

    def test_a_point_exactly_on_the_bound_is_not_flagged(self):
        # Q1 = 2.0, Q3 = 4.0, IQR = 2.0 (all exactly representable), so the upper bound is exactly
        # 6.25 at mult = 1.125: the deviation must exceed the bound, not just reach it.
        values = [1.0, 2.0, 3.0, 4.0, 6.25]
        assert detect.rolling_iqr(values, 5, 1.125, 5) == []
        assert [index for index, _s in detect.rolling_iqr(values, 5, 1.124, 5)] == [4]


class TestRules:
    def _spec(self, **overrides):
        spec = dict(detect.resolve_spec()["rules"])
        spec.update(overrides)
        return spec

    def test_static_threshold_is_off_when_null(self):
        hits = detect.rules([1.0, -40.0, 3.0], self._spec(static_threshold=None))
        assert [hit for hit in hits if hit[2] == "static_threshold"] == []

    def test_static_threshold_fires_on_the_absolute_magnitude(self):
        hits = [hit for hit in detect.rules([1.0, -4.0, 3.0], self._spec(static_threshold=2.5)) if hit[2] == "static_threshold"]
        assert [(index, score) for index, score, _rule in hits] == [(1, 1.5), (2, 0.5)]

    def test_pct_jump_fires_above_the_ratio_and_not_below(self):
        assert detect.rules([100.0, 150.0], self._spec()) == [(1, 0.5, "pct_jump")]
        assert detect.rules([150.0, 100.0], self._spec()) == []
        assert detect.rules([100.0, 60.0], self._spec()) == [(1, pytest.approx(0.4), "pct_jump")]

    def test_pct_jump_stays_silent_on_a_zero_baseline(self):
        # The relative change is undefined against zero; the zero-run rule owns that case instead
        # of the detector substituting a placeholder denominator.
        assert detect.rules([0.0, 5.0], self._spec()) == []
        assert detect.rules([None, 5.0], self._spec()) == []

    def test_missing_run_needs_the_configured_length(self):
        values = [1.0] + [None] * 6 + [2.0]
        hits = [hit for hit in detect.rules(values, self._spec(missing_run=6)) if hit[2] == "missing_run"]
        assert hits == [(index, 6.0, "missing_run") for index in range(1, 7)]
        assert [hit for hit in detect.rules(values, self._spec(missing_run=7)) if hit[2] == "missing_run"] == []

    def test_zero_run_needs_the_same_length(self):
        values = [1.0] + [0.0] * 6 + [2.0]
        hits = [hit for hit in detect.rules(values, self._spec(missing_run=6)) if hit[2] == "zero_run"]
        assert hits == [(index, 6.0, "zero_run") for index in range(1, 7)]
        short = [1.0] + [0.0] * 5 + [2.0]
        assert [hit for hit in detect.rules(short, self._spec(missing_run=6)) if hit[2] == "zero_run"] == []

    def test_a_missing_value_breaks_a_zero_run(self):
        values = [1.0, 0.0, 0.0, 0.0, None, 0.0, 0.0, 0.0, 2.0]
        assert [hit for hit in detect.rules(values, self._spec()) if hit[2] == "zero_run"] == []

    def test_cusum_fires_once_on_a_step_and_restarts(self):
        values = [0.0] * 20 + [10.0] * 20
        hits = [hit for hit in detect.rules(values, self._spec()) if hit[2] == "cusum"]
        assert [index for index, _score, _rule in hits] == [20]
        assert hits[0][1] > 10.0

    def test_cusum_ignores_a_slow_cycle(self):
        # One step of a slow ramp is far below the difference scale, so nothing accumulates.
        values = [float(index) * 0.01 for index in range(60)]
        assert [hit for hit in detect.rules(values, self._spec()) if hit[2] == "cusum"] == []

    def test_cusum_stands_down_when_the_differences_have_no_scale(self):
        assert [hit for hit in detect.rules([3.0] * 40, self._spec()) if hit[2] == "cusum"] == []

    def test_every_hit_names_one_of_the_documented_rules(self):
        values = [0.0] * 10 + [None] * 6 + [float(index) for index in range(10)]
        for _index, _score, rule in detect.rules(values, self._spec(static_threshold=1.0)):
            assert rule in detect.RULE_NAMES


def _bump(n, period, amplitude):
    """A C2-continuous periodic bump, built from multiplications only (no transcendentals)."""
    values = []
    for index in range(n):
        u = 2.0 * (index % period) / period
        if u > 1.0:
            u = 2.0 - u
        values.append(amplitude * u * u * u * (u * (6.0 * u - 15.0) + 10.0))
    return values


class TestStlResidual:
    """The STL path's job is to keep a cycle out of the hits while keeping the anomalies in."""

    def test_a_smooth_cycle_alone_produces_no_hits(self):
        values = _bump(1200, 96, 10.0)
        positions = list(range(1200))
        assert detect.stl_resid_z(values, positions, 96, 2, 1, 24, 3.5, 6) == []

    def test_without_the_seasonal_removal_the_same_cycle_is_flagged(self):
        # This is the contrast that justifies having an STL detector at all: the rolling median/MAD
        # sees the fast rise of the cycle as a deviation, the residual does not.
        values = _bump(1200, 96, 10.0)
        assert len(detect.rolling_mad_z(values, 24, 3.5, 6)) > 10

    def test_a_spike_on_a_cycle_is_found_and_the_cycle_is_not(self):
        values = _bump(1200, 96, 10.0)
        values[601] += 40.0
        hits = detect.stl_resid_z(values, list(range(1200)), 96, 2, 1, 24, 3.5, 6)
        assert [index for index, _score in hits] == [601]

    def test_halving_the_period_leaves_a_much_larger_residual(self):
        values = _bump(1200, 96, 10.0)
        positions = list(range(1200))
        right = [abs(value) for value in detect.stl_residual(values, positions, 96, 2, 1) if value is not None]
        wrong = [abs(value) for value in detect.stl_residual(values, positions, 48, 2, 1) if value is not None]
        assert max(wrong) > 3.0 * max(right)

    def test_period_at_most_one_means_no_seasonal_component(self):
        residual = detect.stl_residual([7.0] * 40, list(range(40)), 1, 2, 1)
        assert max(abs(value) for value in residual) < 1e-9
        assert detect.stl_resid_z([7.0] * 40, list(range(40)), 1, 2, 1, 24, 3.5, 6) == []

    def test_missing_values_stay_missing_in_the_residual(self):
        values = _bump(200, 96, 10.0)
        values[5] = None
        residual = detect.stl_residual(values, list(range(200)), 96, 2, 1)
        assert len(residual) == len(values)
        assert residual[5] is None
        assert all(value is not None for index, value in enumerate(residual) if index != 5)

    def test_the_seasonal_curve_is_folded_on_the_grid_not_the_list_position(self):
        # One dropped sample shifts every later list position by one. Folding on the grid keeps the
        # phase curve aligned; folding on positions smears it and leaves visible residual artefacts.
        values = _bump(200, 96, 10.0)
        positions = list(range(200))
        gapped_values = values[:100] + values[101:]
        gapped_positions = positions[:100] + positions[101:]
        clean = detect.stl_residual(values, positions, 96, 2, 1)
        folded = detect.stl_residual(gapped_values, gapped_positions, 96, 2, 1)
        # gapped index 149 holds the sample from grid position 150
        assert folded[149] == pytest.approx(clean[150], abs=0.01)
        folded_hits = detect.stl_resid_z(gapped_values, gapped_positions, 96, 2, 1, 24, 3.5, 6)
        position_hits = detect.stl_resid_z(
            gapped_values, list(range(len(gapped_values))), 96, 2, 1, 24, 3.5, 6
        )
        assert len(folded_hits) < len(position_hits)


class TestPeriodEstimator:
    def _grid(self, period, n, amplitude, noise_scale, shift_at=None):
        grid = _bump(n, period, amplitude)
        for index in range(n):
            grid[index] += (((index * 2654435761) % 1000) / 1000.0 - 0.5) * noise_scale
        if shift_at is not None:
            for index in range(shift_at, shift_at + 31):
                grid[index] += 8.0
        return grid

    def test_it_recovers_a_planted_period(self):
        assert detect.estimate_series_period(self._grid(40, 500, 10.0, 1.0), 121, 2.5) == 40
        assert detect.estimate_series_period(self._grid(64, 600, 10.0, 1.0), 121, 2.5) == 64

    def test_a_planted_level_shift_does_not_move_the_estimate(self):
        assert detect.estimate_series_period(self._grid(40, 500, 10.0, 1.0, shift_at=300), 121, 2.5) == 40

    def test_a_grid_too_short_for_three_cycles_yields_nothing(self):
        assert detect.estimate_series_period([1.0, 2.0, 1.0], 121, 2.5) is None
        assert detect.estimate_series_period([1.0] * 23, 121, 2.5) is None

    def test_a_constant_grid_yields_nothing(self):
        assert detect.estimate_series_period([3.0] * 500, 121, 2.5) is None

    def test_gaps_do_not_move_the_estimate(self):
        grid = self._grid(40, 500, 10.0, 1.0)
        for index in range(200, 220):
            grid[index] = None
        assert detect.estimate_series_period(grid, 121, 2.5) == 40

    def test_the_frozen_fixture_estimates_the_planted_daily_cycle(self, frozen):
        parsed, run_document, _anomaly_set = frozen
        estimates = dict(
            (item["series_id"], item["period_points"]) for item in run_document["period_estimates"]
        )
        assert estimates == {"temperature": 289, "humidity": 287, "energy_kwh": 288}
        assert run_document["params"]["period_points"] == 288
        assert run_document["period_source"] == "estimated"

    def test_a_short_series_resolves_to_no_cycle_instead_of_a_guess(self):
        parsed = csvio.load_series(MINIMAL_CSV)
        run_document, _anomaly_set = detect.detect_all(parsed, detect.resolve_spec())
        assert run_document["params"]["period_points"] == 1
        assert run_document["period_source"] == "no-cycle-default"
        assert run_document["period_estimates"] == []

    def test_a_declared_period_is_used_verbatim(self):
        parsed = csvio.load_series(SERIES_CSV)
        run_document, _anomaly_set = detect.detect_all(parsed, detect.resolve_spec({"period_points": 96}))
        assert run_document["params"]["period_points"] == 96
        assert run_document["period_source"] == "declared"
        assert run_document["period_estimates"] == []


class TestFrozenFixtureDocument:
    def test_the_run_document_holds_only_integers_strings_and_null(self, frozen):
        _parsed, run_document, _anomaly_set = frozen
        assert list(iter_floats(run_document)) == []
        canon.assert_hashable(run_document)

    def test_the_run_document_has_no_clock_field_and_no_iso_string(self, frozen):
        _parsed, run_document, _anomaly_set = frozen
        text = canon.canonical_json_text(run_document)
        for key in FORBIDDEN_CLOCK_KEYS:
            assert '"%s"' % key not in text
        assert "T00:00" not in text and "Z\"" not in text

    def test_the_run_document_params_are_the_resolved_effective_values(self, frozen):
        _parsed, run_document, _anomaly_set = frozen
        # The document carries the *effective* period (288, estimated), which is exactly what
        # declaring 288 by hand produces -- the estimate is recorded, never re-derived downstream.
        assert run_document["params"] == detect.dump_spec(detect.resolve_spec({"period_points": 288}))
        assert run_document["params"]["period_points"] == 288

    def test_version_fields_are_present_and_distinct(self, frozen):
        _parsed, run_document, _anomaly_set = frozen
        assert run_document["canon_version"] == canon.CANON_VERSION
        assert run_document["detector_version"] == detect.DETECTOR_VERSION
        assert run_document["schema_version"] == canon.ANOMALY_SET_VERSION
        assert isinstance(run_document["quant_decimals"], int)

    def test_the_source_is_identified_by_digest(self, frozen):
        _parsed, run_document, _anomaly_set = frozen
        assert run_document["source"]["file"] == "series.csv"
        assert run_document["source"]["sha256"] == csvio.load_series(SERIES_CSV).stats["sha256"]
        assert run_document["source"]["size_bytes"] == os.path.getsize(SERIES_CSV)

    def test_the_series_block_matches_the_parsed_counts(self, frozen):
        parsed, run_document, _anomaly_set = frozen
        by_id = dict((item["series_id"], item) for item in run_document["series"])
        assert sorted(by_id) == sorted(parsed.rows_by_series)
        for series_id, rows in parsed.rows_by_series.items():
            entry = by_id[series_id]
            assert entry["n_points"] == len(rows)
            assert entry["n_values_missing"] == sum(1 for row in rows if row[2] is None)
            assert entry["cadence_ms"] == 300000

    def test_the_digest_matches_the_frozen_golden(self, frozen):
        _parsed, _run_document, anomaly_set = frozen
        assert canon.canonical_digest(anomaly_set) == GOLDEN_ANOMALY_DIGEST

    def test_the_archive_is_byte_identical_across_runs(self):
        first = detect.detect_all(csvio.load_series(SERIES_CSV), detect.resolve_spec())
        second = detect.detect_all(csvio.load_series(SERIES_CSV), detect.resolve_spec())
        assert canon.canonical_json_bytes(first[1]) == canon.canonical_json_bytes(second[1])
        assert canon.canonical_json_bytes(first[0]) == canon.canonical_json_bytes(second[0])

    def test_the_run_block_inside_the_archive_equals_run_json(self, frozen, tmp_path, capsys):
        _parsed, run_document, anomaly_set = frozen
        out_dir = str(tmp_path / "out")
        assert cli.main(["detect", SERIES_CSV, "--out-dir", out_dir]) == cli.EXIT_OK
        capsys.readouterr()
        assert read_bytes(os.path.join(out_dir, "run.json")) == canon.canonical_json_bytes(run_document)
        assert anomaly_set["run"] == run_document


class TestFrozenFixtureEpisodes:
    def test_episodes_are_ordered_by_the_severity_key(self, frozen):
        _parsed, _run_document, anomaly_set = frozen
        keys = [detect_episode_key(episode) for episode in anomaly_set["episodes"]]
        assert keys == sorted(keys)

    def test_ids_are_sequential_per_series_in_that_order(self, frozen):
        _parsed, _run_document, anomaly_set = frozen
        counters = {}
        for episode in anomaly_set["episodes"]:
            series_id = episode["series_id"]
            counters[series_id] = counters.get(series_id, 0) + 1
            assert episode["episode_id"] == "%s-E%03d" % (series_id, counters[series_id])

    def test_every_episode_carries_the_documented_fields(self, frozen):
        _parsed, _run_document, anomaly_set = frozen
        expected = {
            "episode_id",
            "series_id",
            "detector",
            "start",
            "end",
            "duration_ms",
            "peak_score_q",
            "n_points",
            "start_row",
            "end_row",
            "threshold_ref",
        }
        assert anomaly_set["episodes"]
        for episode in anomaly_set["episodes"]:
            assert set(episode) == expected
            assert isinstance(episode["peak_score_q"], int)
            assert episode["duration_ms"] >= 0
            assert episode["n_points"] >= 1
            assert episode["start_row"] <= episode["end_row"]
            assert episode["start"].endswith("Z") and episode["end"].endswith("Z")

    def test_threshold_ref_is_the_effective_block_of_the_firing_detector(self, frozen):
        _parsed, run_document, anomaly_set = frozen
        for episode in anomaly_set["episodes"]:
            family = episode["detector"].split(".")[0]
            assert episode["threshold_ref"] == run_document["params"][family]

    def test_every_episode_row_span_is_inside_its_series_row_range(self, frozen):
        parsed, _run_document, anomaly_set = frozen
        for episode in anomaly_set["episodes"]:
            rows = parsed.rows_by_series[episode["series_id"]]
            assert rows[0][0] <= episode["start_row"] <= rows[-1][0]
            assert rows[0][0] <= episode["end_row"] <= rows[-1][0]

    def test_the_summary_counts_add_up(self, frozen):
        _parsed, _run_document, anomaly_set = frozen
        summary = anomaly_set["summary"]
        episodes = anomaly_set["episodes"]
        assert summary["n_episodes"] == len(episodes)
        assert sum(summary["episodes_by_detector"].values()) == len(episodes)
        assert sum(summary["episodes_by_series"].values()) == len(episodes)
        assert summary["n_detections"] == sum(summary["detections_by_detector"].values())
        for detector, count in summary["episodes_by_detector"].items():
            assert count == sum(1 for episode in episodes if episode["detector"] == detector)

    def test_missing_runs_are_found_by_the_run_rule_only(self, frozen, truth):
        # A gap in the data is not a value the rolling detectors can score, so the run rule owns it.
        _parsed, _run_document, anomaly_set = frozen
        detectors = set()
        for run in truth["planted"]["missing_runs"]:
            covering = [
                episode["detector"]
                for episode in anomaly_set["episodes"]
                if episode["series_id"] == run["series_id"]
                and episode["start_row"] <= run["end_row"]
                and run["start_row"] <= episode["end_row"]
            ]
            assert "rules.missing_run" in covering
            detectors.update(covering)
        assert detectors == {"rules.missing_run"}


def detect_episode_key(episode):
    return (
        -episode["peak_score_q"],
        -episode["duration_ms"],
        episode["start_row"],
        episode["detector"],
    )


class TestTruthReconciliation:
    def test_every_planted_segment_is_covered(self, frozen, truth):
        _parsed, _run_document, anomaly_set = frozen
        misses = []
        for segment in truth["segments"]:
            covering = [
                episode
                for episode in anomaly_set["episodes"]
                if episode["series_id"] == segment["series_id"]
                and episode["start_row"] <= segment["end_row"]
                and segment["start_row"] <= episode["end_row"]
            ]
            if not covering:
                misses.append(segment["segment_id"])
        assert misses == []
        assert len(truth["segments"]) == 39

    def test_every_merge_probe_is_decided_and_agrees(self, frozen, truth):
        parsed, _run_document, anomaly_set = frozen
        for probe in truth["merge_probes"]:
            stamps = dict((row[0], row[1]) for row in parsed.rows_by_series[probe["series_id"]])
            separation = stamps[probe["second_row"]] - stamps[probe["first_row"]]
            assert (separation <= probe["max_gap_ms"]) == probe["expected_merged"]
            matches = []
            for episode in anomaly_set["episodes"]:
                if episode["detector"] != "rolling_mad_z" or episode["series_id"] != probe["series_id"]:
                    continue
                if episode["start_row"] <= probe["first_row"] <= episode["end_row"]:
                    matches.append(episode["episode_id"])
                if episode["start_row"] <= probe["second_row"] <= episode["end_row"]:
                    matches.append(episode["episode_id"])
            assert len(matches) == 2, probe["probe_id"]
            assert (matches[0] == matches[1]) == probe["expected_merged"], probe["probe_id"]


class TestDigestSensitivity:
    def _digest(self, sample, override):
        parsed = csvio.load_series(sample)
        _run, anomaly_set = detect.detect_all(parsed, detect.resolve_spec(override))
        return canon.canonical_digest(anomaly_set)

    def test_every_parameter_matrix_is_covered(self):
        # Parametrising off the declaration tables means a newly added parameter is swept
        # automatically; the literal below keeps that from quietly shrinking.
        labels = set()
        for name, params in detect.DETECTOR_PARAMS:
            for param, _kind in params:
                labels.add("%s.%s" % (name, param))
        for param, _kind in detect.RUN_PARAMS:
            labels.add(param)
        assert labels == {
            "rolling_mad_z.window",
            "rolling_mad_z.k",
            "rolling_mad_z.min_valid",
            "rolling_iqr.window",
            "rolling_iqr.iqr_mult",
            "rolling_iqr.min_valid",
            "stl_resid_z.inner",
            "stl_resid_z.outer",
            "stl_resid_z.window",
            "stl_resid_z.k",
            "stl_resid_z.min_valid",
            "rules.static_threshold",
            "rules.pct_jump",
            "rules.missing_run",
            "rules.cusum_k",
            "rules.cusum_h",
            "max_gap_ms",
            "period_points",
            "period_reject_window",
            "period_reject_sigma",
        }

    @pytest.mark.parametrize(
        "override",
        [
            {"rolling_mad_z": {"window": 25}},
            {"rolling_mad_z": {"k": 3.6}},
            {"rolling_mad_z": {"min_valid": 7}},
            {"rolling_iqr": {"window": 25}},
            {"rolling_iqr": {"iqr_mult": 3.1}},
            {"rolling_iqr": {"min_valid": 7}},
            {"stl_resid_z": {"inner": 3}},
            {"stl_resid_z": {"outer": 0}},
            {"stl_resid_z": {"window": 25}},
            {"stl_resid_z": {"k": 3.6}},
            {"stl_resid_z": {"min_valid": 7}},
            {"rules": {"static_threshold": 1.0}},
            {"rules": {"pct_jump": 0.36}},
            {"rules": {"missing_run": 7}},
            {"rules": {"cusum_k": 0.6}},
            {"rules": {"cusum_h": 5.1}},
            {"max_gap_ms": 1800001},
            {"period_points": 96},
            {"period_reject_window": 122},
            {"period_reject_sigma": 2.6},
        ],
    )
    def test_changing_one_parameter_moves_the_digest(self, override):
        baseline = self._digest(MINIMAL_CSV, {})
        assert self._digest(MINIMAL_CSV, override) != baseline

    def test_an_identical_spec_keeps_the_digest(self):
        assert self._digest(MINIMAL_CSV, {}) == self._digest(MINIMAL_CSV, {})

    def test_a_tighter_merge_threshold_produces_more_episodes(self):
        # The digest assertion above is structural (the run-spec is inside the fingerprint); this
        # one checks that a parameter the contract cares about actually changes a verdict.
        parsed = csvio.load_series(SERIES_CSV)
        wide = detect.detect_all(parsed, detect.resolve_spec({"max_gap_ms": 1800000}))[1]
        narrow = detect.detect_all(parsed, detect.resolve_spec({"max_gap_ms": 600000}))[1]
        assert narrow["summary"]["n_episodes"] > wide["summary"]["n_episodes"]

    def test_a_higher_threshold_produces_fewer_episodes(self):
        parsed = csvio.load_series(SERIES_CSV)
        loose = detect.detect_all(parsed, detect.resolve_spec({"rolling_mad_z": {"k": 8.0}}))[1]
        tight = detect.detect_all(parsed, detect.resolve_spec())[1]
        assert loose["summary"]["episodes_by_detector"].get("rolling_mad_z", 0) < (
            tight["summary"]["episodes_by_detector"]["rolling_mad_z"]
        )


class TestCmdDetect:
    def test_a_successful_run_writes_three_files(self, tmp_path, capsys):
        out_dir = tmp_path / "out"
        assert cli.main(["detect", MINIMAL_CSV, "--out-dir", str(out_dir)]) == cli.EXIT_OK
        captured = capsys.readouterr()
        assert "anomaly-set sha256" in captured.out
        for name in ("run.json", "anomalies.json", "anomaly_set.sha256"):
            assert (out_dir / name).is_file()
        digest = read_text(str(out_dir / "anomaly_set.sha256")).strip()
        payload = read_bytes(str(out_dir / "anomalies.json"))
        assert digest == canon.sha256_hex(payload)
        assert payload == canon.canonical_json_bytes(json.loads(payload.decode("utf-8")))

    def test_the_output_directory_is_created_when_absent(self, tmp_path, capsys):
        out_dir = tmp_path / "deep" / "nested"
        assert cli.main(["detect", MINIMAL_CSV, "--out-dir", str(out_dir)]) == cli.EXIT_OK
        capsys.readouterr()
        assert (out_dir / "run.json").is_file()

    def test_double_run_writes_identical_bytes(self, tmp_path, capsys):
        first = tmp_path / "a"
        second = tmp_path / "b"
        assert cli.main(["detect", SERIES_CSV, "--out-dir", str(first)]) == cli.EXIT_OK
        assert cli.main(["detect", SERIES_CSV, "--out-dir", str(second)]) == cli.EXIT_OK
        capsys.readouterr()
        for name in ("run.json", "anomalies.json", "anomaly_set.sha256"):
            assert read_bytes(str(first / name)) == read_bytes(str(second / name))

    def test_a_spec_file_is_honoured(self, tmp_path, write_text_file, capsys):
        spec = write_text_file('{"rolling_mad_z": {"k": 4.0}}', name="spec.json")
        out_dir = tmp_path / "out"
        assert cli.main(["detect", MINIMAL_CSV, "--spec", spec, "--out-dir", str(out_dir)]) == cli.EXIT_OK
        capsys.readouterr()
        document = json.loads(read_text(str(out_dir / "run.json")))
        assert document["params"]["rolling_mad_z"]["k"] == "4.000000"

    def test_a_missing_spec_file_is_a_usage_error(self, tmp_path, capsys):
        out_dir = tmp_path / "out"
        missing = str(tmp_path / "absent.json")
        assert cli.main(["detect", MINIMAL_CSV, "--spec", missing, "--out-dir", str(out_dir)]) == cli.EXIT_USAGE
        assert not out_dir.exists()
        assert "run-spec file not found" in capsys.readouterr().err

    def test_an_unreadable_spec_file_is_a_usage_error(self, tmp_path, write_text_file, capsys):
        spec = write_text_file("{not json", name="spec.json")
        out_dir = tmp_path / "out"
        assert cli.main(["detect", MINIMAL_CSV, "--spec", spec, "--out-dir", str(out_dir)]) == cli.EXIT_USAGE
        assert not out_dir.exists()
        assert "not readable JSON" in capsys.readouterr().err

    def test_a_json_array_spec_is_a_usage_error(self, tmp_path, write_text_file, capsys):
        spec = write_text_file("[1, 2]", name="spec.json")
        out_dir = tmp_path / "out"
        assert cli.main(["detect", MINIMAL_CSV, "--spec", spec, "--out-dir", str(out_dir)]) == cli.EXIT_USAGE
        assert not out_dir.exists()
        assert "must be a JSON object" in capsys.readouterr().err

    def test_an_unknown_spec_key_is_a_usage_error_and_writes_nothing(self, tmp_path, write_text_file, capsys):
        spec = write_text_file('{"bogus": 1}', name="spec.json")
        out_dir = tmp_path / "out"
        assert cli.main(["detect", MINIMAL_CSV, "--spec", spec, "--out-dir", str(out_dir)]) == cli.EXIT_USAGE
        assert not out_dir.exists()
        assert "unknown run-spec key" in capsys.readouterr().err

    def test_a_wrongly_typed_parameter_is_a_usage_error(self, tmp_path, write_text_file, capsys):
        spec = write_text_file('{"rolling_mad_z": {"window": 24.5}}', name="spec.json")
        out_dir = tmp_path / "out"
        assert cli.main(["detect", MINIMAL_CSV, "--spec", spec, "--out-dir", str(out_dir)]) == cli.EXIT_USAGE
        assert not out_dir.exists()
        assert "whole number" in capsys.readouterr().err

    def test_a_broken_csv_is_a_usage_error_and_writes_nothing(self, tmp_path, write_text_file, capsys):
        broken = write_text_file("timestamp,value\nbroken,1\n")
        out_dir = tmp_path / "out"
        assert cli.main(["detect", broken, "--out-dir", str(out_dir)]) == cli.EXIT_USAGE
        assert not out_dir.exists()
        assert "E_TS_UNPARSEABLE" in capsys.readouterr().err

    def test_a_missing_csv_is_a_usage_error(self, tmp_path, capsys):
        out_dir = tmp_path / "out"
        missing = str(tmp_path / "absent.csv")
        assert cli.main(["detect", missing, "--out-dir", str(out_dir)]) == cli.EXIT_USAGE
        assert not out_dir.exists()
        capsys.readouterr()

    def test_detect_is_no_longer_a_not_ready_stage(self):
        assert "detect" not in cli.STAGE_NOT_READY
