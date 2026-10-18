"""M3 mirror tests: the mirror's place in the static gate, the shared SHA-256 vectors, the
embedding contract, and the Node channel (parity, tamper localisation, missing Node).

The parity tests need Node. They are skipped only when it is absent, and the *absence* path has its
own deterministic test (a bogus `--node` name), so "no Node here" can never be confused with
"parity holds": the gate answers 4, it does not answer 0 (plan/06 D8).

The falsification probes are the reason this file is worth more than its green tick. Two are
arithmetic (a mutated `MAD_TO_SIGMA`, a mutated SHA-256 constant), and one displaces an inlined
sample: each must turn *its own* check red, and the tamper must localise to the series it broke.
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil

import pytest

from anomaly_atlas import canon, cli, csvio, detect, mirror, render

import test_no_transcendental as gate  # the M2 static gate owns the JavaScript scan scope

from conftest import REPO_ROOT, SERIES_CSV, TOOLS, read_text

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="Node is not installed on this machine")

SRC = os.path.join(REPO_ROOT, "src")
MIRROR_PATH = os.path.join(SRC, "anomaly_atlas", "mirror", "zaa_mirror.js")

_MIRROR_BLOCK_RE = re.compile(
    r"(<script\b[^>]*\bid=\"zaa-mirror\"[^>]*>)(.*?)(</script\s*>)", re.DOTALL | re.IGNORECASE
)


def _with_mirror_source(html, source):
    """Swap the inlined mirror source for another one, keeping the artifact otherwise intact."""
    replaced, count = _MIRROR_BLOCK_RE.subn(lambda match: match.group(1) + source + match.group(3), html, 1)
    assert count == 1
    return replaced

# The frozen anomaly-set digest, pinned as a literal (the same tripwire `selftest` uses): reading it
# back out of the artifact under test would make this file agree with whatever the artifact became.
FROZEN_DIGEST = "6020a3d34b0228c9b0735d7b2d10aad67d3181d0cb02eb2a02d7fd864ef1b422"
FROZEN_PERIOD_POINTS = 288

# Inline indices chosen one per series (the payload stores series sorted, rows in source order):
# energy_kwh / humidity / temperature.
TAMPER_INDICES = (3, 1500, 2900)


def _load_tool(name):
    path = os.path.join(TOOLS, name + ".py")
    spec = importlib.util.spec_from_file_location("zaa_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mirror_parity = _load_tool("mirror_parity")


@pytest.fixture(scope="module")
def frozen():
    parsed = csvio.load_series(SERIES_CSV)
    run_document, anomaly_set = detect.detect_all(parsed, detect.resolve_spec())
    return parsed, run_document, anomaly_set


@pytest.fixture(scope="module")
def artifact(tmp_path_factory, frozen):
    """A real artifact on disk -- `verify` and the parity tool both take a path."""
    path = os.path.join(str(tmp_path_factory.mktemp("artifact")), "atlas.html")
    render.write_view(SERIES_CSV, path)
    return path


@pytest.fixture(scope="module")
def payload(artifact):
    return mirror.extract_artifact(read_text(artifact))["payload"]


class TestMirrorIsInsideTheStaticGate:
    """The mirror is JavaScript under `src/`, so the M2 gate already scans it -- pinned here so a
    future move of the file cannot quietly walk it out of the scan scope."""

    def test_the_javascript_scan_scope_really_contains_the_mirror(self):
        assert MIRROR_PATH in gate._javascript_sources(gate.SRC)

    def test_the_shipped_mirror_passes_the_gate(self):
        assert gate.scan_javascript(MIRROR_PATH, gate.SRC) == []

    def test_a_transcendental_injected_into_the_mirror_goes_red(self, tmp_path):
        text = read_text(MIRROR_PATH)
        broken = tmp_path / "zaa_mirror.js"
        broken.write_text(text + "\nvar ZAA_PROBE = Math.exp(1.0);\n", encoding="utf-8")
        hits = gate.scan_javascript(str(broken), str(tmp_path))
        assert any(hit[2] == "Math.exp" for hit in hits), hits

    def test_the_mirror_names_its_counterparts(self):
        text = read_text(MIRROR_PATH)
        for family, members in (
            ("detect", ("rolling_mad_z", "rolling_iqr", "stl_resid_z", "rules", "grid_positions")),
            ("episodes", ("merge_episodes",)),
            ("canon", ("quantize", "fixed_to_str", "canonical_json_text", "sha256_hex")),
            ("timebase", ("epoch_ms_to_iso",)),
        ):
            assert "mirrors: anomaly_atlas." + family in text, family
            for member in members:
                assert member in text, member

    def test_the_mirror_is_algorithmic_only(self):
        # No DOM, no network, no module system, no Web Crypto: the same source has to run in a
        # browser and under Node, so anything that reaches outside plain arithmetic is a defect.
        text = read_text(MIRROR_PATH)
        for forbidden in ("crypto", "require(", "fetch(", "XMLHttpRequest", "document.", "window.",
                          "import(", "<script"):
            assert forbidden not in text, forbidden
        assert text.count("//") == 0  # block comments only, so masking script bodies stays trivial

    def test_the_mirror_does_not_re_estimate_the_period(self):
        # K8/D13: the mirror consumes the effective `period_points`. A second estimator would put
        # "estimator differences" into the fingerprint, which is exactly what the contract prevents.
        text = read_text(MIRROR_PATH)
        assert "estimate_period" not in text


class TestSharedSha256Vectors:
    """plan/02 3.4: one vector set, asserted on both sides -- here the Python half."""

    def test_the_vector_set_has_the_shapes_the_plan_names(self):
        lengths = sorted(len(text.encode("utf-8")) for text, _digest in mirror.SHA256_VECTORS)
        assert lengths[0] == 0  # the empty message
        assert any(text == "abc" for text, _digest in mirror.SHA256_VECTORS)
        assert any(length > 55 for length in lengths)  # past one padding block
        assert any(length > 64 for length in lengths)  # past a whole 64-byte block
        assert any(any(ord(ch) > 127 for ch in text) for text, _digest in mirror.SHA256_VECTORS)

    def test_every_vector_matches_hashlib_and_the_project_helper(self):
        for text, digest in mirror.SHA256_VECTORS:
            assert hashlib.sha256(text.encode("utf-8")).hexdigest() == digest, repr(text[:16])
            assert canon.sha256_hex(text) == digest, repr(text[:16])

    def test_the_comparison_can_go_both_ways(self):
        # A comparison that cannot fail proves nothing: pick a vector and disagree with it.
        text, digest = mirror.SHA256_VECTORS[1]
        assert canon.sha256_hex(text) == digest
        assert canon.sha256_hex(text) != "0" * 64


class TestSharedFixedPointVectors:
    """K13's other half: the mirror must reproduce the kernel's fixed-point rule for any input.

    This exists because the digest is a weak probe for it -- measured: mutating the mirror's
    half-to-even boundary left the frozen-fixture parity test green, since no score in the fixture
    lands in the affected window. Without these vectors the boundary would be untested.
    """

    def test_the_tie_vectors_have_unambiguous_literal_answers(self):
        for value, decimals, expected in mirror.FIXED_POINT_TIES:
            assert canon.quantize(value, decimals) == expected, (value, decimals)
            assert canon.fixed_to_str(canon.quantize(value, decimals), decimals) == str(expected)

    def test_the_python_side_agrees_with_the_named_ties(self):
        # The mirror-side vector set must contain the ties the literals above pin, or the two lists
        # could drift apart and the cross-language comparison would stop covering ties at all.
        for value, decimals, _expected in mirror.FIXED_POINT_TIES:
            assert (value, decimals) in mirror.FIXED_POINT_VECTORS

    @requires_node
    def test_the_mirror_agrees_with_the_kernel_on_the_fixed_point_rule(self, artifact):
        source = mirror.extract_artifact(read_text(artifact))["mirror_source"]
        outcome = mirror.run_node_fixed_point(source, NODE)
        expected_q = [canon.quantize(value, decimals) for value, decimals in mirror.FIXED_POINT_VECTORS]
        expected_s = [
            canon.fixed_to_str(canon.quantize(value, decimals), decimals)
            for value, decimals in mirror.FIXED_POINT_VECTORS
        ]
        assert outcome["quantized"] == expected_q, list(zip(mirror.FIXED_POINT_VECTORS, outcome["quantized"]))
        assert outcome["strings"] == expected_s

    @requires_node
    def test_a_mutated_half_to_even_boundary_is_caught_here(self, artifact):
        # The mutation that stayed green against the fixture digest must be red against these
        # vectors; otherwise the vectors are not doing the job they were added for.
        source = mirror.extract_artifact(read_text(artifact))["mirror_source"]
        broken = source.replace("    if (frac > 0.5) {", "    if (frac > 0.4999995) {", 1)
        assert broken != source
        outcome = mirror.run_node_fixed_point(broken, NODE)
        expected_q = [canon.quantize(value, decimals) for value, decimals in mirror.FIXED_POINT_VECTORS]
        assert outcome["quantized"] != expected_q


class TestArtifactContract:
    def test_extraction_round_trips_the_shipped_mirror(self, artifact):
        extracted = mirror.extract_artifact(read_text(artifact))
        assert extracted["mirror_source"] == mirror.load_mirror_js()

    def test_the_artifact_advertises_the_pinned_versions(self, payload):
        assert payload["contract_version"] == mirror.CONTRACT_VERSION == "1"
        assert payload["mirror_version"] == mirror.MIRROR_VERSION == "1"

    def test_the_embedded_fingerprint_is_the_frozen_digest(self, payload):
        assert payload["anomaly_set_sha256"] == FROZEN_DIGEST

    def test_the_embedded_canonical_json_is_the_archive_it_names(self, payload):
        archive = json.loads(payload["anomaly_set_canonical"])
        assert canon.canonical_digest(archive) == payload["anomaly_set_sha256"]
        assert payload["anomaly_set_canonical"] == canon.canonical_json_text(archive)

    def test_the_embedded_run_block_is_the_effective_spec(self, payload, frozen):
        _parsed, run_document, _anomaly_set = frozen
        assert payload["run"] == run_document
        assert payload["run"]["params"]["period_points"] == FROZEN_PERIOD_POINTS
        assert payload["run"]["period_source"] == "estimated"

    def test_the_payload_carries_no_float_literal(self, payload):
        # Samples travel as decimal text, so the same "integers, strings, null" guard the hashed
        # documents go through applies to the payload too -- one discipline, no exception.
        canon.assert_hashable(payload)
        for block in payload["series"]:
            for row in block["rows"]:
                assert isinstance(row[0], int) and isinstance(row[2], int)
                assert row[1] is None or isinstance(row[1], str)

    def test_the_inlined_samples_are_every_parsed_row(self, payload, frozen):
        parsed, _run_document, _anomaly_set = frozen
        inlined = sum(len(block["rows"]) for block in payload["series"])
        assert inlined == sum(len(rows) for rows in parsed.rows_by_series.values())
        by_series = {block["series_id"]: block["rows"] for block in payload["series"]}
        assert sorted(by_series) == parsed.series_order
        for series_id in parsed.series_order:
            rows = parsed.rows_by_series[series_id]
            for position, (row_no, epoch_ms, value) in enumerate(rows):
                cell = by_series[series_id][position]
                assert cell[0] == epoch_ms
                assert cell[2] == row_no
                assert cell[1] == (None if value is None else repr(value))

    def test_the_build_detection_points_are_the_kernel_output(self, payload, frozen):
        parsed, run_document, _anomaly_set = frozen
        decimals = run_document["quant_decimals"]
        resolved = detect.resolve_spec(run_document["params"])
        detections = detect.run_detectors(parsed, resolved, resolved["period_points"])
        expected = []
        for series_id in parsed.series_order:
            for detector in sorted(key[1] for key in detections if key[0] == series_id):
                bucket = sorted(detections[(series_id, detector)], key=lambda item: (item[0], item[1]))
                expected.append(
                    {
                        "series_id": series_id,
                        "detector": detector,
                        "points": [[p[0], p[1], canon.quantize(p[2], decimals)] for p in bucket],
                    }
                )
        assert payload["detections"] == expected


class TestArtifactErrors:
    def test_a_file_that_is_not_an_artifact_is_a_usage_error(self, tmp_path, capsys):
        other = tmp_path / "readme.md"
        other.write_text("# not an artifact\n", encoding="utf-8")
        assert mirror.cmd_verify(str(other), "node") == cli.EXIT_USAGE
        assert "zaa-payload" in capsys.readouterr().err

    def test_a_missing_artifact_is_a_usage_error(self, tmp_path, capsys):
        assert mirror.cmd_verify(str(tmp_path / "nope.html"), "node") == cli.EXIT_USAGE
        assert "not found" in capsys.readouterr().err

    def test_a_broken_payload_is_a_usage_error(self, tmp_path, artifact, capsys):
        html = read_text(artifact).replace(
            '<script id="zaa-payload" type="application/json">', 
            '<script id="zaa-payload" type="application/json">\n{bogus',
            1,
        )
        broken = tmp_path / "broken.html"
        broken.write_text(html, encoding="utf-8")
        assert mirror.cmd_verify(str(broken), "node") == cli.EXIT_USAGE
        assert "JSON" in capsys.readouterr().err


class TestNodeMissing:
    """`verify` must answer 4, with two ways forward -- never a silent pass (plan/06 D8)."""

    def test_verify_without_node_exits_four(self, artifact, capsys):
        assert mirror.cmd_verify(artifact, "definitely-not-a-node-executable") == cli.EXIT_ENV
        captured = capsys.readouterr()
        assert "not found" in captured.err
        assert len(mirror.NODE_REMEDIES) == 2
        for remedy in mirror.NODE_REMEDIES:
            assert remedy in captured.err

    def test_the_parity_tool_reports_the_same_status(self, artifact, capsys):
        status = mirror_parity.main(["--html", artifact, "--node", "definitely-not-a-node-executable"])
        assert status == cli.EXIT_ENV
        assert "hint:" in capsys.readouterr().err

    def test_the_tool_needs_something_to_do(self, capsys):
        assert mirror_parity.main([]) == cli.EXIT_USAGE
        assert "--html" in capsys.readouterr().err


@pytest.mark.usefixtures("artifact")
class TestNodeChannel:
    @requires_node
    def test_the_verdict_of_a_healthy_artifact_is_verified(self, artifact):
        outcome = mirror.verify_artifact(artifact, "node")
        assert outcome["status"] == "verified", outcome
        assert outcome["verdict"]["digest"] == FROZEN_DIGEST

    @requires_node
    def test_the_cli_verifies_and_exits_zero(self, artifact, capsys):
        assert cli.main(["verify", artifact]) == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "VERIFIED" in out and FROZEN_DIGEST in out

    @requires_node
    def test_the_shared_vectors_hold_in_the_shipped_mirror(self, artifact, payload):
        outcome = mirror.run_node_mirror(
            payload,
            mirror.expected_block(payload),
            mirror.extract_artifact(read_text(artifact))["mirror_source"],
            NODE,
        )
        assert outcome["vectors"] == []
        assert outcome["verdict"]["verified"] is True

    @requires_node
    @pytest.mark.parametrize("index", TAMPER_INDICES)
    def test_a_tampered_inline_point_goes_red_and_localises(self, artifact, index):
        outcome = mirror.verify_artifact(artifact, "node", index)
        assert outcome["status"] == "mismatch", outcome
        verdict = outcome["verdict"]
        assert verdict["verified"] is False
        tamper = outcome["tamper"]
        assert tamper["inline_index"] == index
        difference = verdict["first_point_diff"]
        assert difference is not None
        assert difference["series_id"] == tamper["series_id"], (difference, tamper)
        assert verdict["digest"] != FROZEN_DIGEST
        assert verdict["first_byte_diff"] >= 0

    @requires_node
    def test_the_tamper_probe_is_reported_and_exits_one(self, artifact, capsys):
        assert cli.main(["verify", artifact, "--tamper-index", "3"]) == cli.EXIT_FAIL
        captured = capsys.readouterr()
        assert "MISMATCH" in captured.err
        assert "energy_kwh" in captured.out  # the series the probe broke, named
        assert "tamper probe: inline index 3" in captured.out

    @requires_node
    def test_an_out_of_range_tamper_index_is_a_usage_error(self, artifact, capsys):
        assert cli.main(["verify", artifact, "--tamper-index", "99999"]) == cli.EXIT_USAGE
        assert "outside the" in capsys.readouterr().err

    @requires_node
    def test_a_detection_arithmetic_mutation_is_caught(self, artifact, payload):
        # Break the mirror's arithmetic (not its hash) and the parity gate must notice: this is the
        # mutation the whole Node channel exists for.
        source = mirror.extract_artifact(read_text(artifact))["mirror_source"]
        broken = source.replace("var MAD_TO_SIGMA = 1.4826;", "var MAD_TO_SIGMA = 1.5;", 1)
        assert broken != source
        outcome = mirror.run_node_mirror(payload, mirror.expected_block(payload), broken, NODE)
        assert outcome["vectors"] == []  # the hash is untouched, so the vector gate stays green
        assert outcome["verdict"]["verified"] is False
        assert outcome["verdict"]["first_point_diff"] is not None

    @requires_node
    def test_a_sha256_mutation_is_caught_as_a_vector_failure(self, artifact, payload):
        source = mirror.extract_artifact(read_text(artifact))["mirror_source"]
        broken = source.replace("var h0 = 0x6a09e667;", "var h0 = 0x6a09e668;", 1)
        assert broken != source
        outcome = mirror.run_node_mirror(payload, mirror.expected_block(payload), broken, NODE)
        assert len(outcome["vectors"]) == len(mirror.SHA256_VECTORS)
        assert outcome["verdict"]["verified"] is False

    @requires_node
    def test_a_mirror_that_cannot_run_is_a_defect_not_a_mismatch(self, artifact, tmp_path, capsys):
        broken = tmp_path / "broken-mirror.html"
        broken.write_text(_with_mirror_source(read_text(artifact), "var ZAA = {};\n"), encoding="utf-8")
        outcome = mirror.verify_artifact(str(broken), "node")
        assert outcome["status"] == "run-error"
        assert mirror.cmd_verify(str(broken), "node") == cli.EXIT_FAIL
        assert "could not be run" in capsys.readouterr().err


@pytest.mark.usefixtures("artifact")
class TestMirrorParityTool:
    @requires_node
    def test_the_tool_verifies_a_healthy_artifact(self, artifact, capsys):
        assert mirror_parity.main(["--html", artifact]) == cli.EXIT_OK
        assert "VERIFIED" in capsys.readouterr().out

    @requires_node
    def test_the_tool_tamper_probe_exits_one(self, artifact, capsys):
        assert mirror_parity.main(["--html", artifact, "--tamper-index", "1500"]) == cli.EXIT_FAIL
        assert "MISMATCH" in capsys.readouterr().err

    @requires_node
    def test_build_mode_writes_an_artifact_that_verifies(self, tmp_path, capsys):
        out = tmp_path / "built.html"
        assert mirror_parity.main(["--build", str(out), "--csv", SERIES_CSV]) == cli.EXIT_OK
        captured = capsys.readouterr()
        assert FROZEN_DIGEST in captured.out
        assert out.is_file()
        assert cli.main(["verify", str(out)]) == cli.EXIT_OK
        capsys.readouterr()

    def test_build_mode_reports_a_missing_csv(self, tmp_path, capsys):
        assert mirror_parity.main(["--build", str(tmp_path / "x.html"), "--csv", "no.csv"]) == cli.EXIT_USAGE
        assert "not found" in capsys.readouterr().err
