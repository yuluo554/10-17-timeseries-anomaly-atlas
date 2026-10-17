"""M2 selftest-suite tests: the checks are green, and every check can actually go red.

The important half is the second one. A check plus its falsification probe is the only thing that
distinguishes "the benchmark passes" from "the benchmark is a no-op": these tests assert both that
the probes go red on the real fixture and that a failing probe is counted as a failure by the CLI.
"""

import contextlib
import io
import json
import os

import pytest

from anomaly_atlas import canon, cli, csvio, detect, selftest

from conftest import REPO_ROOT, SERIES_CSV, read_text


@pytest.fixture(scope="module")
def results():
    return selftest.run_checks(selftest.find_fixture_root(REPO_ROOT))


class TestFixtureDiscovery:
    def test_it_finds_the_repository_root(self):
        assert selftest.find_fixture_root(REPO_ROOT) == REPO_ROOT

    def test_it_finds_the_root_from_a_subdirectory(self):
        assert selftest.find_fixture_root(os.path.join(REPO_ROOT, "tests")) == REPO_ROOT

    def test_it_falls_back_to_the_installation_root(self, tmp_path):
        assert selftest.find_fixture_root(str(tmp_path)) == REPO_ROOT

    def test_it_returns_none_when_there_are_no_fixtures(self, tmp_path, monkeypatch):
        monkeypatch.setattr(selftest, "_PACKAGE_ROOT", str(tmp_path))
        assert selftest.find_fixture_root(str(tmp_path)) is None


class TestChecksAreGreen:
    def test_every_check_is_registered_with_a_probe(self):
        assert len(selftest.CHECKS) == 5
        for name, check, probe in selftest.CHECKS:
            assert name and callable(check) and callable(probe)

    def test_all_checks_pass(self, results):
        failing = [result["name"] for result in results if not result["ok"]]
        assert failing == []
        assert len(results) == len(selftest.CHECKS)

    def test_all_probes_are_falsifiable(self, results):
        # A check whose probe cannot go red is reported as a failure by contract.
        failing = [result["name"] for result in results if not result["probe_ok"]]
        assert failing == []
        for result in results:
            assert result["probe_detail"]

    def test_the_reconciliation_check_reports_full_coverage(self, results):
        detail = dict((result["name"], result["detail"]) for result in results)["truth-reconciliation"]
        assert "39/39 planted segments covered" in detail
        assert "6/6 merge probes" in detail

    def test_the_golden_digest_check_names_the_frozen_digest(self, results):
        detail = dict((result["name"], result["detail"]) for result in results)["fixture-digest-frozen"]
        assert selftest.GOLDEN_ANOMALY_DIGEST[:16] in detail


class TestGoldenDigestIsTheRealOne:
    def test_the_pinned_literal_matches_a_fresh_default_run(self):
        # The tripwire: regenerating the fixture changes the digest and this line must be updated
        # deliberately, rather than the suite quietly comparing an artifact with itself.
        parsed = csvio.load_series(SERIES_CSV)
        _run, anomaly_set = detect.detect_all(parsed, detect.resolve_spec())
        assert canon.canonical_digest(anomaly_set) == selftest.GOLDEN_ANOMALY_DIGEST

    def test_the_truth_digest_recorded_in_the_repository_is_stable(self):
        manifest = json.loads(read_text(os.path.join(REPO_ROOT, "data", "synthetic", "manifest.json")))
        assert read_text(os.path.join(REPO_ROOT, "data", "truth", "hash.txt")).strip() == manifest[
            "truth_sha256"
        ]


class TestCmdSelftest:
    def test_it_returns_zero_when_everything_is_green(self, results, monkeypatch):
        # The checks themselves are covered once by the `results` fixture; this test is about the
        # CLI contract (exit code and one line per check), so it feeds the cached results in
        # rather than paying for a second full sweep of the fixture.
        monkeypatch.setattr(selftest, "run_checks", lambda root: results)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = cli.main(["selftest"])
        out = stream.getvalue()
        assert code == cli.EXIT_OK
        for name, _check, _probe in selftest.CHECKS:
            assert name in out
        assert "0 failing" in out

    def test_it_returns_not_ready_free_exit_code_three_is_retired(self):
        assert "selftest" not in cli.STAGE_NOT_READY

    def test_missing_fixtures_exit_four_rather_than_passing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(selftest, "_PACKAGE_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        assert selftest.cmd_selftest() == cli.EXIT_ENV
        assert "frozen fixtures not found" in capsys.readouterr().err

    def test_a_crashing_check_is_reported_as_a_failure(self, tmp_path, monkeypatch):
        def boom(_fixture):
            raise RuntimeError("injected defect")

        monkeypatch.setattr(selftest, "CHECKS", (("crashing", boom, lambda _fixture: (True, "ok")),))
        results = selftest.run_checks(REPO_ROOT)
        assert results[0]["ok"] is False
        assert "injected defect" in results[0]["detail"]

    def test_a_check_whose_probe_fails_counts_as_a_failure(self, monkeypatch, capsys):
        monkeypatch.setattr(
            selftest,
            "CHECKS",
            (("probe-less", lambda _fixture: (True, "fine"), lambda _fixture: (False, "never goes red")),),
        )
        assert selftest.cmd_selftest() == cli.EXIT_FAIL
        out = capsys.readouterr().out
        assert "probe FAIL" in out
        assert "1 failing" in out
