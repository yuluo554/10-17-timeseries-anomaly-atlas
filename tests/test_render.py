"""M3 render tests: the embedding contract and the minimal carrier page.

The carrier page is the smallest artifact that can carry the M3 recomputation gate: the inlined
samples, the effective run-spec, the build-time canonical JSON plus digest, and the mirror source.
M4 reuses this same contract for the annotated view, so the properties pinned here -- zero external
resources, byte-identical double runs, a self-consistent embedded fingerprint -- are the ones M4
has to keep.

Zero external resources is asserted twice on purpose: once as a positive control (the shipped page
passes) and once as a mutation (a page that links a stylesheet, fetches a URL or inlines a request
is rejected). A check that cannot go red is decoration.
"""

import json
import os
import re

import pytest

from anomaly_atlas import canon, csvio, detect, mirror, render

from conftest import MINIMAL_CSV, REPO_ROOT, SERIES_CSV, read_bytes, read_text

FROZEN_DIGEST = "6020a3d34b0228c9b0735d7b2d10aad67d3181d0cb02eb2a02d7fd864ef1b422"
COMMITTED_ARTIFACT = os.path.join(REPO_ROOT, "examples", "atlas.html")

# The one call the carrier page exists to make, pinned as text so a boot script that stops calling
# the mirror is a visible diff rather than a page that renders "复算中…" forever.
ZAA_RECOMPUTE = "ZAA.verdict(ZAA.recompute(payload), expected, null)"


def _block(html, script_id):
    match = re.search(
        r'<script\b[^>]*\bid="%s"[^>]*>(.*?)</script\s*>' % script_id, html, re.DOTALL | re.IGNORECASE
    )
    assert match, script_id
    return match.group(1)


@pytest.fixture(scope="module")
def frozen():
    parsed = csvio.load_series(SERIES_CSV)
    run_document, anomaly_set, detections = detect.detect_all_detailed(parsed, detect.resolve_spec())
    return parsed, run_document, anomaly_set, detections


@pytest.fixture(scope="module")
def carrier(frozen):
    parsed, run_document, anomaly_set, detections = frozen
    return render.build_carrier_html(parsed, run_document, anomaly_set, detections)


@pytest.fixture(scope="module")
def payload(carrier):
    return json.loads(_block(carrier, mirror.SCRIPT_ID_PAYLOAD))


class TestCarrierShape:
    def test_the_page_is_utf8_lf_without_bom(self, carrier):
        assert not carrier.startswith("\ufeff")
        assert "\r" not in carrier
        assert carrier.startswith("<!DOCTYPE html>")
        assert carrier.endswith("</html>\n")

    def test_the_contract_blocks_are_all_present(self, carrier):
        for script_id in (mirror.SCRIPT_ID_PAYLOAD, mirror.SCRIPT_ID_MIRROR, "zaa-boot"):
            assert 'id="%s"' % script_id in carrier

    def test_the_page_states_what_it_is(self, carrier):
        # The M4 view replaces this artifact; a reader of the committed file must not mistake the
        # carrier for the finished view.
        assert render.CARRIER_TITLE in carrier
        assert "M4" in carrier

    def test_the_smallest_artifact_still_carries_the_recomputation(self, carrier, payload):
        assert payload["anomaly_set_sha256"] == FROZEN_DIGEST
        assert payload["run"]["params"]["period_points"] == 288
        assert ZAA_RECOMPUTE in carrier  # the boot script really drives the mirror


class TestZeroExternalResources:
    def test_the_shipped_page_is_self_contained(self, carrier):
        render.assert_no_external_resources(carrier)  # raises on any external reference

    @pytest.mark.parametrize(
        "injection",
        (
            '<script src="https://cdn.example/x.js"></script>',
            '<link rel="stylesheet" href="https://fonts.example/x.css">',
            '<img src="data-image.png">',
            '<iframe src="https://example.test/x"></iframe>',
            "<style>body { background: url(https://example.test/x.png); }</style>",
            "<style>@import url(https://example.test/x.css);</style>",
            "<!-- //example.test/x -->",
            "<script>fetch('https://example.test/x');</script>",
            "<script>var r = new XMLHttpRequest();</script>",
        ),
    )
    def test_an_external_reference_is_rejected(self, carrier, injection):
        broken = carrier.replace("</body>", injection + "</body>", 1)
        assert broken != carrier
        with pytest.raises(ValueError):
            render.assert_no_external_resources(broken)

    def test_an_inlined_data_url_is_allowed(self, carrier):
        # Positive control for the exception: a data: payload never leaves the file, so banning it
        # would make the M4 gap texture / print pattern work impossible for no gain.
        allowed = carrier.replace(
            "</style>",
            ".gap { fill: url(data:image/svg+xml;base64,PHN2Zy8+); }\n</style>",
            1,
        )
        render.assert_no_external_resources(allowed)

    def test_the_javascript_bodies_are_masked_before_the_markup_scan(self, carrier):
        # The mirror is full of JavaScript operators and block comments; masking the script bodies
        # is what keeps the markup scan from reading them as external references.
        assert "/*" in carrier and "*/" in carrier
        render.assert_no_external_resources(carrier)


class TestCarrierIsDeterministic:
    def test_the_page_carries_no_clock_and_no_float_literal(self, payload):
        canon.assert_hashable(payload)
        for key in ("generated", "generated_at", "created", "created_at", "built_at", "now"):
            assert key not in payload

    def test_the_written_file_is_byte_identical_across_runs(self, tmp_path):
        # The M3 artifact is a product, so the M1/M2 double-run guarantee has to hold for it too --
        # at the file layer, which also covers the LF/UTF-8/BOM discipline.
        first = tmp_path / "a.html"
        second = tmp_path / "b.html"
        render.write_carrier(SERIES_CSV, str(first))
        render.write_carrier(SERIES_CSV, str(second))
        assert read_bytes(str(first)) == read_bytes(str(second))

    def test_the_committed_artifact_is_the_builder_output(self, carrier):
        # The committed example must be regenerable, or "the artifact a reader downloads" and "the
        # artifact CI verifies" are two different files (the classic stale-fixture gap).
        assert os.path.isfile(COMMITTED_ARTIFACT), "examples/atlas.html is missing"
        assert read_text(COMMITTED_ARTIFACT) == carrier


class TestPayloadIsAPureFunctionOfTheRun:
    def test_the_payload_matches_the_archive_it_carries(self, payload, frozen):
        _parsed, run_document, anomaly_set, _detections = frozen
        assert payload["anomaly_set_canonical"] == canon.canonical_json_text(anomaly_set)
        assert payload["anomaly_set_sha256"] == canon.canonical_digest(anomaly_set)
        assert payload["run"] == run_document

    def test_re_deriving_the_points_from_run_json_gives_the_same_payload(self, payload, frozen):
        # The same-pass detections and the detections a recomputation would re-derive from run.json
        # must agree: otherwise the payload's point set is not a function of what the artifact
        # publishes, and the point comparison would be checking the wrong thing.
        parsed, run_document, anomaly_set, detections = frozen
        assert render.build_payload(parsed, run_document, anomaly_set) == payload  # no detections: re-derived

    def test_the_minimal_sample_also_builds(self, tmp_path):
        # The contract must not depend on the frozen fixture's shape (3 series, ~1000 points).
        out = tmp_path / "minimal.html"
        _run_document, anomaly_set = render.write_carrier(MINIMAL_CSV, str(out))
        html = read_text(str(out))
        render.assert_no_external_resources(html)
        payload = json.loads(_block(html, mirror.SCRIPT_ID_PAYLOAD))
        assert payload["anomaly_set_sha256"] == canon.canonical_digest(anomaly_set)
        assert len(payload["series"]) == 1
