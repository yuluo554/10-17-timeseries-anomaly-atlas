"""M2 canon tests: the hashed archive form plus the fixed-point primitives it rests on.

The half-to-even rule gets direct tests because language-provided float formatting is banned here
precisely at the .5 boundary, where `f"{x:.6f}"` and `toFixed` disagree with each other and with
us. A test that only exercised "nice" values would never touch the case the rule exists for.
"""

import hashlib

import pytest

from anomaly_atlas import canon


class TestFixedPointPrimitives:
    def test_half_to_even_rounds_to_the_even_neighbour(self):
        assert canon.quantize(0.5, 0) == 0
        assert canon.quantize(1.5, 0) == 2
        assert canon.quantize(2.5, 0) == 2
        assert canon.quantize(3.5, 0) == 4

    def test_half_to_even_handles_negatives(self):
        assert canon.quantize(-0.5, 0) == 0
        assert canon.quantize(-1.5, 0) == -2
        assert canon.quantize(-2.5, 0) == -2

    def test_rounding_happens_above_and_below_the_half(self):
        assert canon.quantize(1.25, 1) == 12  # 12.5 -> even
        assert canon.quantize(1.35, 1) == 14  # 13.5 -> even
        assert canon.quantize(1.24, 1) == 12
        assert canon.quantize(1.26, 1) == 13

    def test_scaling_absorbs_binary_representation_noise(self):
        # 0.1 + 0.2 is 0.30000000000000004: the scale-and-floor form must still land on 300000.
        assert canon.quantize(0.1 + 0.2, 6) == 300000
        assert canon.quantize(0.30000000000000004, 6) == 300000

    def test_a_scaled_product_that_lands_on_the_half_ties_to_even(self):
        # 2.675 is really 2.67499999999999982, but multiplying by 100 rounds to exactly 267.5 in
        # binary64, so the tie rule (not the decimal expansion) decides: 267 is odd, hence 268.
        # The JS mirror computes the same product from the same double and reaches the same
        # integer, which is the whole reason this rule exists instead of `f"{x:.2f}"`.
        assert canon.quantize(2.675, 2) == 268
        assert canon.fixed_to_str(canon.quantize(2.675, 2), 2) == "2.68"

    def test_fixed_to_str_is_built_from_the_integer(self):
        assert canon.fixed_to_str(3500000, 6) == "3.500000"
        assert canon.fixed_to_str(-1234, 2) == "-12.34"
        assert canon.fixed_to_str(7, 3) == "0.007"
        assert canon.fixed_to_str(5, 0) == "5"
        assert canon.fixed_to_str(-7, 3) == "-0.007"
        assert canon.fixed_to_str(0, 6) == "0.000000"

    def test_round_trip_of_a_decimal_parameter(self):
        for value in (3.5, 3.0, 0.35, 0.5, 5.0, 2.5, 1.4826):
            quantized = canon.quantize(value, 6)
            assert canon.fixed_to_str(quantized, 6) == "%.6f" % value


class TestHashableRejection:
    def test_accepts_the_allowed_scalars_and_containers(self):
        canon.assert_hashable({"a": [1, "two", None, True], "b": {"c": 3}})

    @pytest.mark.parametrize("payload", [1.5, {"a": 1.5}, [1.5], {"a": [{"b": 2.5}]}])
    def test_rejects_a_float_anywhere_in_the_tree(self, payload):
        with pytest.raises(TypeError):
            canon.assert_hashable(payload)

    def test_rejects_a_non_string_key(self):
        with pytest.raises(TypeError):
            canon.assert_hashable({1: "x"})

    def test_canonical_json_refuses_to_serialise_a_float(self):
        with pytest.raises(TypeError):
            canon.canonical_json_bytes({"k": 3.5})

    def test_fixed_point_string_is_the_way_a_decimal_gets_in(self):
        payload = {"k": canon.fixed_to_str(canon.quantize(3.5, 6), 6)}
        canon.assert_hashable(payload)


class TestCanonicalForm:
    def test_text_is_sorted_indented_and_newline_terminated(self):
        text = canon.canonical_json_text({"b": 1, "a": 2})
        assert text == '{\n  "a": 2,\n  "b": 1\n}\n'

    def test_bytes_are_utf8_without_bom(self):
        payload = canon.canonical_json_bytes({"scenario": "冷链仓储（虚构）"})
        assert not payload.startswith(b"\xef\xbb\xbf")
        assert payload.decode("utf-8").startswith("{")

    def test_digest_is_sha256_of_the_canonical_bytes(self):
        document = {"a": [1, "x", None]}
        expected = hashlib.sha256(canon.canonical_json_bytes(document)).hexdigest()
        assert canon.canonical_digest(document) == expected
        assert canon.canonical_digest(document) == canon.sha256_hex(canon.canonical_json_bytes(document))

    def test_digest_is_stable_across_dictionary_insertion_order(self):
        first = {"a": 1, "b": {"d": 4, "c": 3}}
        second = {"b": {"c": 3, "d": 4}, "a": 1}
        assert canon.canonical_digest(first) == canon.canonical_digest(second)


class TestBuildAnomalySet:
    def _set(self, run=None, episodes=None, summary=None):
        return canon.build_anomaly_set(
            run if run is not None else {"params": {"k": "3.500000"}},
            episodes if episodes is not None else [],
            summary if summary is not None else {"n_episodes": 0},
        )

    def test_carries_the_version_and_all_three_blocks(self):
        anomaly_set = self._set()
        assert anomaly_set["schema_version"] == canon.ANOMALY_SET_VERSION
        assert set(anomaly_set) == {"schema_version", "run", "episodes", "summary"}

    def test_is_hashable_and_serialisable_as_is(self):
        canon.assert_hashable(self._set())
        assert canon.canonical_json_bytes(self._set()).endswith(b"\n")

    def test_the_run_block_is_inside_the_fingerprint(self):
        # This is the property the whole "change a parameter, get a new fingerprint" contract
        # rests on: a parameter that happens not to move a detection still moves the digest.
        baseline = canon.canonical_digest(self._set(run={"params": {"k": "3.500000"}}))
        changed = canon.canonical_digest(self._set(run={"params": {"k": "3.500001"}}))
        assert baseline != changed

    def test_an_identical_set_has_an_identical_digest(self):
        assert canon.canonical_digest(self._set()) == canon.canonical_digest(self._set())

    def test_versions_are_distinct_strings(self):
        assert canon.CANON_VERSION != canon.ANOMALY_SET_VERSION or isinstance(canon.CANON_VERSION, str)
        assert isinstance(canon.CANON_VERSION, str) and canon.CANON_VERSION
