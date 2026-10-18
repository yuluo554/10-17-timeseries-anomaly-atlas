"""M4 render tests: the annotated view on top of the M3 embedding contract.

The artifact has two readers at once. The machine channel (`verify` / `tools/mirror_parity.py`) drives
the inlined mirror under Node; the human channel is the browser, where the badge, the sensitivity
sliders and the print stylesheet live. M3's lesson is pinned in that shape: zero external resources
is asserted on every build *and* falsified by injection, the artifact is byte-identical across runs,
and the page carries no `$` -- the one defect class the Node channel cannot see, because it never
runs the boot script.

The M4 additions are pinned against the archive rather than against the page: the report area's
numbers must be the summary the payload carries, the anomaly-set digest must still be the M2/M3
frozen one (proof that the render-only parameters never entered the fingerprint), and the three
region textures must be structurally distinct, because "distinguishable in black and white" is a
property of the markup, not of a stylesheet promise.
"""

import json
import os
import re

import pytest

from anomaly_atlas import canon, csvio, detect, layout, mirror, render

from conftest import MINIMAL_CSV, REPO_ROOT, SERIES_CSV, iter_floats, read_bytes, read_text

# The frozen anomaly-set digest, pinned as a literal. The M4 artifact must carry the *same* digest as
# the M3 carrier page: the annotated view is presentation over one archive, and a render-only knob
# that moved this number would mean presentation had leaked into the fingerprint (plan/06 D22).
FROZEN_DIGEST = "6020a3d34b0228c9b0735d7b2d10aad67d3181d0cb02eb2a02d7fd864ef1b422"
COMMITTED_ARTIFACT = os.path.join(REPO_ROOT, "examples", "atlas.html")

# The one call the boot script exists to make, pinned as text so a boot script that stops calling the
# mirror is a visible diff rather than a page that renders "复算中…" forever.
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
def artifact(frozen):
    parsed, run_document, anomaly_set, detections = frozen
    return render.build_view_html(parsed, run_document, anomaly_set, detections)


@pytest.fixture(scope="module")
def payload(artifact):
    return json.loads(_block(artifact, mirror.SCRIPT_ID_PAYLOAD))


class TestArtifactShape:
    def test_the_page_is_utf8_lf_without_bom(self, artifact):
        assert not artifact.startswith("\ufeff")
        assert "\r" not in artifact
        assert artifact.startswith("<!DOCTYPE html>")
        assert artifact.endswith("</html>\n")

    def test_the_contract_blocks_are_all_present(self, artifact):
        for script_id in (mirror.SCRIPT_ID_PAYLOAD, mirror.SCRIPT_ID_MIRROR, render.SCRIPT_ID_BOOT):
            assert 'id="%s"' % script_id in artifact

    def test_the_page_states_what_it_is(self, artifact):
        # The committed file is the annotated view, and it says so: a reader must not mistake it for
        # the M3 carrier page it replaced, nor for a plan of one.
        assert render.VIEW_TITLE in artifact
        assert "M4" in artifact

    def test_the_annotated_page_still_carries_the_recomputation(self, artifact, payload):
        assert payload["anomaly_set_sha256"] == FROZEN_DIGEST
        assert payload["run"]["params"]["period_points"] == 288
        assert ZAA_RECOMPUTE in artifact  # the boot script really drives the mirror

    def test_no_template_slot_survives_into_the_artifact(self, artifact):
        # `string.Template` leaves an unsubstituted slot verbatim, and a substituted value is not
        # re-scanned -- so a `$payload_id` written inside the boot script reaches the page as text
        # and the page looks up a null element. The Node channel cannot see that: it drives the
        # mirror directly and never runs the boot script (this is how the first version shipped, and
        # only the browser caught it). The absence of any `$` is therefore a gate, not cosmetics.
        assert "$" not in artifact
        render.assert_no_template_slots(artifact)  # the same claim, as the builder's own assertion

    def test_the_boot_block_looks_up_the_payload_block_by_its_contract_id(self, artifact):
        boot = _block(artifact, render.SCRIPT_ID_BOOT)
        assert 'getElementById("%s")' % mirror.SCRIPT_ID_PAYLOAD in boot
        assert 'getElementById("verdict-label")' in boot

    def test_the_boot_block_drives_the_sliders_through_the_mirror(self, artifact):
        # A slider that recomputed with its own arithmetic would be a second implementation of the
        # kernel in the page (the forbidden variant of the sensitivity channel, D17). Pinned as text:
        # the handler must call the mirror, and must not reach for any network API.
        boot = _block(artifact, render.SCRIPT_ID_BOOT)
        assert "ZAA.recompute(probePayload)" in boot
        assert 'getElementById("k-scale")' in boot
        assert 'getElementById("max-gap")' in boot
        assert 'getElementById("slider-spec")' in boot
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource"):
            assert forbidden not in boot


class TestZeroExternalResources:
    def test_the_shipped_page_is_self_contained(self, artifact):
        render.assert_no_external_resources(artifact)  # raises on any external reference

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
    def test_an_external_reference_is_rejected(self, artifact, injection):
        broken = artifact.replace("</body>", injection + "</body>", 1)
        assert broken != artifact
        with pytest.raises(ValueError):
            render.assert_no_external_resources(broken)

    def test_an_inlined_data_url_is_allowed(self, artifact):
        # Positive control for the exception: a data: payload never leaves the file, so banning it
        # would make an inline SVG texture (a `<pattern>` fill, say) impossible for no gain.
        allowed = artifact.replace(
            "</style>",
            ".gap { fill: url(data:image/svg+xml;base64,PHN2Zy8+); }\n</style>",
            1,
        )
        render.assert_no_external_resources(allowed)

    def test_the_javascript_bodies_are_masked_before_the_markup_scan(self, artifact):
        # The mirror is full of JavaScript operators and block comments; masking the script bodies
        # is what keeps the markup scan from reading them as external references.
        assert "/*" in artifact and "*/" in artifact
        render.assert_no_external_resources(artifact)

    def test_an_external_reference_introduced_by_the_builder_itself_goes_red(self, artifact):
        # The builder asserts at its own exit (not only in this file), and the assertion is the same
        # one: injecting into a copy proves the shipped page is not passing by accident.
        broken = artifact.replace('<svg class="chart"', '<svg src="x.png" class="chart"', 1)
        assert broken != artifact
        with pytest.raises(ValueError):
            render.assert_no_external_resources(broken)


class TestTheAnnotatedView:
    def test_every_component_of_the_plan_is_on_the_page(self, artifact):
        # The M4 component list, one assertion per item (plan/03 M4 / plan/05 M4).
        for marker in (
            'id="verdict"',                 # VERIFIED / MISMATCH badge
            'id="quality"',                 # data-quality card
            'id="main-series"',             # main series with bands, peaks and textures
            'id="small-multiples"',         # one chart per metric
            'id="density"',                 # anomaly density strip
            'id="sensitivity"',             # threshold-sensitivity sliders
            'id="episodes"',                # episode cards
            'id="report"',                  # report area
            'class="episode"',              # an episode card really exists
            '<input type="range" id="k-scale"',
            '<select id="max-gap"',
        ):
            assert marker in artifact, marker

    def test_the_main_view_draws_bands_peaks_and_all_three_textures(self, artifact):
        assert artifact.count('class="band ') > 0
        assert artifact.count('class="peak"') > 0
        assert 'class="region region-gap"' in artifact
        assert 'class="region region-zero"' in artifact
        assert 'class="region region-missing"' in artifact
        assert 'class="hatch"' in artifact  # the gap texture is explicit geometry
        assert 'class="rung"' in artifact   # so is the zero-run texture

    def test_one_episode_card_per_episode_with_its_id_and_source_rows(self, artifact, frozen):
        _parsed, _run_document, anomaly_set, _detections = frozen
        assert artifact.count('<article class="episode"') == len(anomaly_set["episodes"])
        for episode in anomaly_set["episodes"][:25] + anomaly_set["episodes"][-25:]:
            assert "<code>%s</code>" % episode["episode_id"] in artifact
            assert "<dd>%d → %d</dd>" % (episode["start_row"], episode["end_row"]) in artifact

    def test_a_threshold_line_is_derived_from_the_reference_or_the_card_says_why_not(self, artifact, frozen):
        # Every rolling-detector episode gets a numeric line; every rules episode either gets the
        # configured level (static_threshold) or the explicit "not a value-space threshold" note.
        _parsed, _run_document, anomaly_set, _detections = frozen
        rolling = [
            episode
            for episode in anomaly_set["episodes"]
            if episode["detector"] in ("rolling_mad_z", "rolling_iqr", "stl_resid_z")
        ]
        assert rolling
        assert artifact.count('class="threshold"') >= len(rolling)
        assert "该检测器的阈值不在数值域（规则型）" in artifact
        for episode in rolling[:10]:
            assert "Episode %s 的局部放大" % episode["episode_id"] in artifact

    def test_the_small_multiples_cover_every_series(self, artifact, frozen):
        parsed, _run_document, _anomaly_set, _detections = frozen
        for series_id in sorted(parsed.rows_by_series):
            assert "small multiple %s" % series_id in artifact

    def test_the_density_strip_has_one_cell_per_bin_and_a_legend(self, artifact, frozen):
        parsed, _run_document, anomaly_set, _detections = frozen
        episodes_by_series = {}
        for episode in anomaly_set["episodes"]:
            episodes_by_series.setdefault(episode["series_id"], []).append(episode)
        bins = layout.density_bins(parsed.rows_by_series, episodes_by_series, render.layout.DEFAULT_HEAT_BIN_MS)
        assert artifact.count('class="bin bin-') == len(bins) + 6  # + the legend swatches
        assert "无有效点" in artifact
        assert "覆盖 &gt; 75%" in artifact or "覆盖 > 75%" in artifact

    def test_the_report_area_repeats_the_archive_summary_verbatim(self, artifact, frozen):
        _parsed, _run_document, anomaly_set, _detections = frozen
        summary = anomaly_set["summary"]
        assert "%d 段 / %d 个（%d 条检测器流）" % (
            summary["n_episodes"],
            summary["n_detections"],
            len(summary["detections_by_detector"]),
        ) in artifact
        for detector in sorted(summary["episodes_by_detector"]):
            assert "%s: %d" % (detector, summary["episodes_by_detector"][detector]) in artifact

    def test_the_build_id_is_content_derived_never_a_clock(self, artifact, payload):
        assert "<dd>%s</dd>" % payload["anomaly_set_sha256"][: render.BUILD_ID_LENGTH] in artifact
        for key in ("generated", "generated_at", "created", "created_at", "built_at", "now"):
            assert key not in payload

    def test_the_render_spec_is_recorded_on_the_page(self, artifact):
        # The presentation knobs are declared and visible (no hidden default), and they are declared
        # as the render run-spec rather than inside the archive (plan/06 D22).
        assert "pad_rows = 6" in artifact
        assert "heat_bin_ms = 3600000" in artifact

    def test_a_non_default_render_spec_shows_up_verbatim(self, frozen):
        # The displayed run-spec fragment has to be the *resolved* one, otherwise "no hidden default"
        # is a claim about a string that is not the value in force. Non-default values are used here
        # on purpose: a page that printed the defaults no matter what would pass a default-only check.
        parsed, run_document, anomaly_set, detections = frozen
        html = render.build_view_html(
            parsed, run_document, anomaly_set, detections, {"pad_rows": 9, "heat_bin_ms": 7200000}
        )
        assert "pad_rows = 9" in html
        assert "heat_bin_ms = 7200000" in html
        assert "pad_rows = 6" not in html


class TestTheBuilderAssertsAtItsOwnExit:
    """The two invariants live in the builder, not once in this file. Each is driven through a value
    the builder cannot pre-screen for it -- the narrative -- so removing the assertion goes red."""

    def test_zero_external_resources_is_asserted_on_the_page_the_builder_produced(self, frozen):
        parsed, run_document, anomaly_set, detections = frozen
        with pytest.raises(ValueError):
            render.build_view_html(
                parsed, run_document, anomaly_set, detections, None, "see https://example.test/x"
            )

    def test_a_dollar_from_the_narrative_is_refused_by_the_builder(self, frozen):
        parsed, run_document, anomaly_set, detections = frozen
        with pytest.raises(ValueError):
            render.build_view_html(parsed, run_document, anomaly_set, detections, None, "价格 $5")

    def test_the_narrative_is_escaped_into_the_page(self, frozen):
        parsed, run_document, anomaly_set, detections = frozen
        html = render.build_view_html(parsed, run_document, anomaly_set, detections, None, "<b>粗体</b>")
        assert "&lt;b&gt;粗体&lt;/b&gt;" in html
        assert "<b>粗体</b>" not in html


class TestThePrimaryViewIsDeterministic:
    def test_the_primary_series_is_the_most_anomalous_with_a_tie_break(self):
        # One rule, pinned as a unit: most episodes wins; a tie goes to the lexicographically smaller
        # series id. Without the tie-break the main view could depend on dict iteration order.
        rows = {"b": [(1, 0, 1.0)], "a": [(2, 0, 1.0)]}
        one = [{"episode_id": "x-E001"}]
        assert render._primary_series(rows, {"a": one, "b": one}) == "a"
        assert render._primary_series(rows, {"a": [], "b": one}) == "b"
        assert render._primary_series(rows, {}) == "a"


class TestPrintLegibility:
    def test_the_stylesheet_has_a_print_block_that_keeps_cards_whole(self, artifact):
        assert "@media print" in artifact
        assert "break-inside: avoid" in artifact
        assert "page-break-inside: avoid" in artifact
        # The sliders are controls, not content: they are hidden in print, while every chart is kept.
        print_block = artifact[artifact.index("@media print") :]
        assert ".controls { display: none; }" in print_block

    def test_rendering_is_pinned_to_the_light_scheme(self, artifact):
        # Strokes, hatches and gray steps mean the same thing on paper only if the page does not flip
        # to a dark scheme (plan/06 P5).
        assert "color-scheme: light;" in artifact

    def test_the_three_region_styles_are_not_colour_only(self, artifact):
        # The three kinds differ by fill/stroke *structure*: a dashed outline, hatch lines, rungs.
        for selector in (".region-missing", ".region-gap", ".region-zero", ".hatch", ".rung"):
            assert selector in artifact, selector
        assert "stroke-dasharray: 5 3" in artifact  # the missing run's dashed outline
        assert "stroke-width: 1" in artifact

    def test_the_density_scale_is_discrete_gray_steps(self, artifact):
        # Five steps plus "no data", each with a legend entry: a continuous ramp would be unreadable
        # in black and white and unverifiable in a test.
        for step in range(5):
            assert ".bin-%d { fill: #" % step in artifact
        assert ".bin-nodata" in artifact


class TestViewIsDeterministic:
    def test_the_page_carries_no_clock_and_no_float_literal(self, payload):
        canon.assert_hashable(payload)
        assert list(iter_floats(payload)) == []

    def test_the_written_file_is_byte_identical_across_runs(self, tmp_path):
        first = tmp_path / "a.html"
        second = tmp_path / "b.html"
        render.write_view(SERIES_CSV, str(first))
        render.write_view(SERIES_CSV, str(second))
        assert read_bytes(str(first)) == read_bytes(str(second))

    def test_the_geometry_is_identical_across_two_renderings(self, frozen):
        # "The same input renders the same geometry" is asserted on the geometry itself, not only on
        # the bytes: integers are what make that true, so the check has to look at integers.
        parsed, _run_document, anomaly_set, _detections = frozen
        episodes_by_series = {}
        for episode in anomaly_set["episodes"]:
            episodes_by_series.setdefault(episode["series_id"], []).append(episode)
        first = layout.small_multiples_layout(
            parsed.rows_by_series, episodes_by_series, render.VIEW_WIDTH, render.MINI_HEIGHT, None
        )
        second = layout.small_multiples_layout(
            parsed.rows_by_series, episodes_by_series, render.VIEW_WIDTH, render.MINI_HEIGHT, None
        )
        assert first == second
        assert list(iter_floats(first)) == []

    def test_the_committed_artifact_is_the_builder_output(self, artifact):
        # The committed example must be regenerable, or "the artifact a reader downloads" and "the
        # artifact CI verifies" are two different files (the classic stale-fixture gap).
        assert os.path.isfile(COMMITTED_ARTIFACT), "examples/atlas.html is missing"
        assert read_text(COMMITTED_ARTIFACT) == artifact


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
        assert render.build_payload(parsed, run_document, anomaly_set) == payload  # no detections

    def test_the_render_spec_does_not_reach_the_fingerprint(self, artifact, frozen):
        # The whole point of keeping the presentation knobs apart (D22): changing them must not move
        # the archive's digest, and the digest really is the frozen one.
        parsed, run_document, anomaly_set, detections = frozen
        for render_spec in ({"pad_rows": 0, "heat_bin_ms": 60000}, {"pad_rows": 40, "heat_bin_ms": 10800000}):
            other = render.build_view_html(
                parsed, run_document, anomaly_set, detections, render_spec
            )
            other_payload = json.loads(_block(other, mirror.SCRIPT_ID_PAYLOAD))
            assert other_payload["anomaly_set_sha256"] == FROZEN_DIGEST
            assert other != artifact  # the view moved ...

    def test_the_same_archive_rebuilds_the_same_fingerprint(self, tmp_path, frozen):
        _parsed, _run_document, anomaly_set, _detections = frozen
        out = tmp_path / "minimal.html"
        _run, built = render.write_view(MINIMAL_CSV, str(out))
        html = read_text(str(out))
        render.assert_no_external_resources(html)
        payload = json.loads(_block(html, mirror.SCRIPT_ID_PAYLOAD))
        assert payload["anomaly_set_sha256"] == canon.canonical_digest(built)
        assert len(payload["series"]) == 1
        assert canon.canonical_digest(anomaly_set) == FROZEN_DIGEST
