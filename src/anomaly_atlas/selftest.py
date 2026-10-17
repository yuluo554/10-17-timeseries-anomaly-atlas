"""Built-in falsifiable benchmark suite (M2).

API:
  find_fixture_root(start=None) -> str | None
  CHECKS: tuple of (name, check, probe)
  run_checks(root=None) -> list[dict]
  cmd_selftest() -> int                # 0 all green, 1 any defect, 4 fixtures unavailable

Checks (each one is a claim the archive makes about itself):
  1. frozen-artifacts-ledgered        -- the manifest's own sha256 ledger covers all four frozen
     artifacts and every digest matches, and hash.txt equals the manifest's truth digest.
  2. truth-reconciliation             -- every planted segment of truth.json is overlapped by at
     least one episode of a default-spec run (all 39, not a sample), and every merge probe
     behaves as `expected_merged` says it must.
  3. fixture-digest-frozen            -- the default-spec anomaly-set digest equals the frozen
     golden digest, so behaviour drift shows up as a red check instead of as a quietly different
     archive.
  4. parameter-change-moves-digest    -- changing a parameter moves the digest (K8: the effective
     run-spec is inside the fingerprint, so this holds even for a parameter that happens not to
     move a detection).
  5. profile-double-run-byte-identical -- the M1 guarantee still holds after M2 landed.

Every check carries a *falsification probe*: a deliberate defect that must turn that check red. A
check whose probe does not go red is reported as a failure, not as a pass -- otherwise the whole
suite could be green because it is a no-op (a test that reads its expectation out of the artifact
it is checking, for instance). The probes are the reason this suite is worth more than its green
tick.

A crashing check is reported as a failed check, never swallowed.
"""

import json
import os
import shutil
import sys
import tempfile

from . import canon, csvio, detect, profile

# The anomaly-set digest of the frozen fixture under the default spec. Pinned as a literal on
# purpose: reading it back out of the artifact would make the check compare the artifact with
# itself. Regenerating the fixture changes this line -- that is a tripwire, not an annoyance.
GOLDEN_ANOMALY_DIGEST = "6020a3d34b0228c9b0735d7b2d10aad67d3181d0cb02eb2a02d7fd864ef1b422"

# The detector whose flagged set at a merge-probe pair is exactly the two planted points; the
# end-to-end probe verdict is taken from it (see _reconcile for why this is stated explicitly).
PRIMARY_DETECTOR = "rolling_mad_z"

FROZEN_ARTIFACTS = (
    "data/synthetic/series.csv",
    "data/synthetic/manifest.json",
    "data/truth/truth.json",
    "data/truth/hash.txt",
)

_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Parameter overrides for check 4: one per detector family plus the merge threshold and the period
# declaration -- the three things plan/05's M2 DoD names explicitly. The exhaustive sweep over
# every parameter lives in tests/test_detect.py, where it belongs.
SENSITIVITY_OVERRIDES = (
    ("rolling_mad_z.k", {"rolling_mad_z": {"k": 3.6}}),
    ("rolling_iqr.iqr_mult", {"rolling_iqr": {"iqr_mult": 3.1}}),
    ("stl_resid_z.inner", {"stl_resid_z": {"inner": 3}}),
    ("rules.missing_run", {"rules": {"missing_run": 7}}),
    ("max_gap_ms", {"max_gap_ms": 1800001}),
    ("period_points", {"period_points": 287}),
)


def find_fixture_root(start=None):
    """Locate the repository root holding the frozen fixtures, or None.

    Checked in order: the given/cwd directory, its parents (a run from a subdirectory still finds
    the fixtures), then the installation-relative root. Returning None rather than guessing is what
    lets `selftest` report exit 4 instead of passing vacuously on a checkout without data/.
    """
    candidates = []
    base = os.path.abspath(start or os.getcwd())
    for _level in range(4):
        candidates.append(base)
        parent = os.path.dirname(base)
        if parent == base:
            break
        base = parent
    candidates.append(_PACKAGE_ROOT)
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "data", "synthetic", "manifest.json")):
            return candidate
    return None


def _read_text(path):
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8")


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


class Fixture(object):
    """The frozen fixture, with the expensive default-spec run computed at most once."""

    def __init__(self, root):
        self.root = root
        self.manifest = json.loads(_read_text(os.path.join(root, "data", "synthetic", "manifest.json")))
        self.truth = json.loads(_read_text(os.path.join(root, "data", "truth", "truth.json")))
        self._parsed = None
        self._anomaly_set = None

    def path(self, relative):
        return os.path.join(self.root, relative.replace("/", os.sep))

    def run(self):
        """`(parsed, anomaly_set)` for the frozen CSV under the default spec."""
        if self._anomaly_set is None:
            self._parsed = csvio.load_series(self.path("data/synthetic/series.csv"))
            _run, self._anomaly_set = detect.detect_all(self._parsed, detect.resolve_spec())
        return self._parsed, self._anomaly_set


# ---------------------------------------------------------------------------
# Check 1: the frozen artifacts are the ones the manifest describes
# ---------------------------------------------------------------------------


def _check_frozen_ledger(fixture):
    problems = []
    for entry in fixture.manifest.get("artifacts", []):
        path = fixture.path(entry["path"])
        if not os.path.isfile(path):
            problems.append("missing: %s" % entry["path"])
            continue
        actual = canon.sha256_hex(_read_bytes(path))
        if actual != entry["sha256"]:
            problems.append("tampered: %s" % entry["path"])
    if not fixture.manifest.get("artifacts"):
        problems.append("the manifest carries no artifact ledger at all")
    hash_path = fixture.path("data/truth/hash.txt")
    if os.path.isfile(hash_path):
        if _read_text(hash_path).strip() != fixture.manifest.get("truth_sha256"):
            problems.append("hash.txt disagrees with the manifest truth digest")
    else:
        problems.append("missing: data/truth/hash.txt")
    if problems:
        return False, "; ".join(problems)
    return True, "%d artifact(s) match the manifest ledger" % len(FROZEN_ARTIFACTS)


def _probe_frozen_ledger(fixture):
    """Flip one byte of a copied artifact: the ledger check must notice."""
    temporary = tempfile.mkdtemp(prefix="zaa-selftest-")
    try:
        for relative in FROZEN_ARTIFACTS:
            target = os.path.join(temporary, relative.replace("/", os.sep))
            directory = os.path.dirname(target)
            if not os.path.isdir(directory):
                os.makedirs(directory)
            shutil.copyfile(fixture.path(relative), target)
        victim = os.path.join(temporary, "data", "synthetic", "series.csv")
        payload = bytearray(_read_bytes(victim))
        payload[0] = payload[0] ^ 0x01
        with open(victim, "wb") as handle:
            handle.write(bytes(payload))
        ok, detail = _check_frozen_ledger(Fixture(temporary))
        if ok:
            return False, "a tampered artifact was accepted by the ledger check"
        return True, "a flipped byte in series.csv goes red (%s)" % detail
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


# ---------------------------------------------------------------------------
# Check 2: every planted segment is accounted for, and the merge rule holds
# ---------------------------------------------------------------------------


def _reconcile(parsed, truth, anomaly_set):
    """Coverage of every planted segment plus each merge probe's verdict."""
    episodes = anomaly_set["episodes"]
    by_series = {}
    for episode in episodes:
        by_series.setdefault(episode["series_id"], []).append(episode)

    missed = []
    families = {}
    for segment in truth["segments"]:
        covering = []
        for episode in by_series.get(segment["series_id"], ()):
            if episode["start_row"] <= segment["end_row"] and segment["start_row"] <= episode["end_row"]:
                covering.append(episode)
        if not covering:
            missed.append(segment["segment_id"])
        else:
            families.setdefault(segment["type"], set()).update(
                episode["detector"] for episode in covering
            )

    stamps = {}
    for rows in parsed.rows_by_series.values():
        for row_no, epoch_ms, _value in rows:
            stamps[row_no] = epoch_ms

    probe_problems = []
    for probe in truth["merge_probes"]:
        separation = stamps[probe["second_row"]] - stamps[probe["first_row"]]
        if (separation <= probe["max_gap_ms"]) != probe["expected_merged"]:
            probe_problems.append(
                "%s: %d ms against max_gap_ms %d does not match expected_merged=%s"
                % (
                    probe["probe_id"],
                    separation,
                    probe["max_gap_ms"],
                    probe["expected_merged"],
                )
            )
            continue
        verdict = _probe_verdict(by_series.get(probe["series_id"], ()), probe)
        if verdict is None:
            probe_problems.append(
                "%s: %s detected neither or both rows, so the probe decides nothing"
                % (probe["probe_id"], PRIMARY_DETECTOR)
            )
        elif verdict != probe["expected_merged"]:
            probe_problems.append(
                "%s: %s merged=%s but truth expects %s"
                % (probe["probe_id"], PRIMARY_DETECTOR, verdict, probe["expected_merged"])
            )

    problems = []
    if missed:
        problems.append("segments with no overlapping episode: %s" % ", ".join(sorted(missed)))
    if probe_problems:
        problems.extend(probe_problems)
    if problems:
        return False, "; ".join(problems)
    detail = "%d/%d planted segments covered; %d/%d merge probes agree on %s (%s)" % (
        len(truth["segments"]) - len(missed),
        len(truth["segments"]),
        len(truth["merge_probes"]),
        len(truth["merge_probes"]),
        PRIMARY_DETECTOR,
        ", ".join(
            "%s:%d" % (kind, len(families.get(kind, ()))) for kind in sorted(families)
        ),
    )
    return True, detail


def _probe_verdict(episodes, probe):
    """True when the primary detector put both probe rows in one episode, False when in two.

    `None` means the probe is not decidable on that detector (a row was not flagged at all), which
    is reported as a defect rather than skipped: a probe that cannot be falsified proves nothing.
    Each row is looked up independently -- when the pair merges, both rows resolve to the *same*
    episode, which a single pass with an `elif` would silently count once.
    """
    first = []
    second = []
    for episode in episodes:
        if episode["detector"] != PRIMARY_DETECTOR:
            continue
        if episode["start_row"] <= probe["first_row"] <= episode["end_row"]:
            first.append(episode["episode_id"])
        if episode["start_row"] <= probe["second_row"] <= episode["end_row"]:
            second.append(episode["episode_id"])
    if len(first) != 1 or len(second) != 1:
        return None
    return first[0] == second[0]


def _check_reconciliation(fixture):
    parsed, anomaly_set = fixture.run()
    return _reconcile(parsed, fixture.truth, anomaly_set)


def _probe_reconciliation(fixture):
    """Add a planted segment nothing could have detected: the check must report it as missed.

    Deleting a segment would falsify nothing -- the requirement disappears with it, so the check
    stays green and proves nothing about whether coverage is really tested. The probe therefore
    *adds* a requirement that cannot be met: a one-point segment at the very first sample of the
    first series, where no detector's window has `min_valid` points yet.
    """
    parsed, anomaly_set = fixture.run()
    mutated = json.loads(json.dumps(fixture.truth))
    series_id = sorted(parsed.rows_by_series)[0]
    row_no, epoch_ms, _value = parsed.rows_by_series[series_id][0]
    mutated["segments"].append(
        {
            "segment_id": "PROBE-S999",
            "series_id": series_id,
            "type": "spike",
            "start_row": row_no,
            "end_row": row_no,
            "start_ms": epoch_ms,
            "end_ms": epoch_ms,
            "n_points": 1,
            "magnitude_milli": 0,
            "magnitude_kind": "additive_milli",
            "at_window_boundary": True,
        }
    )
    ok, detail = _reconcile(parsed, mutated, anomaly_set)
    if ok:
        return False, "a segment nothing detected was reconciled anyway"
    if "PROBE-S999" not in detail:
        return False, "the miss was reported but PROBE-S999 is not named (%s)" % detail
    return True, "an uncoverable segment goes red and is named"


# ---------------------------------------------------------------------------
# Check 3: the frozen digest
# ---------------------------------------------------------------------------


def _check_fixture_digest(fixture):
    _parsed, anomaly_set = fixture.run()
    digest = canon.canonical_digest(anomaly_set)
    if digest != GOLDEN_ANOMALY_DIGEST:
        return False, "anomaly-set digest %s != frozen %s" % (digest[:16], GOLDEN_ANOMALY_DIGEST[:16])
    return True, "anomaly-set digest matches the frozen golden (%s)" % digest[:16]


def _probe_fixture_digest(fixture):
    """The same comparison against a wrong literal must disagree."""
    _parsed, anomaly_set = fixture.run()
    digest = canon.canonical_digest(anomaly_set)
    wrong = "0" * 64
    if digest == wrong:
        return False, "the digest equals the deliberately wrong literal"
    return True, "a wrong literal does not match (%s vs %s)" % (digest[:16], wrong[:16])


# ---------------------------------------------------------------------------
# Check 4: a parameter change moves the digest
# ---------------------------------------------------------------------------


def _check_parameter_sensitivity(fixture):
    parsed, baseline = fixture.run()
    baseline_digest = canon.canonical_digest(baseline)
    unchanged = []
    for label, override in SENSITIVITY_OVERRIDES:
        _run, variant = detect.detect_all(parsed, detect.resolve_spec(override))
        if canon.canonical_digest(variant) == baseline_digest:
            unchanged.append(label)
    if unchanged:
        return False, "digest unchanged by: %s" % ", ".join(unchanged)
    return True, "%d parameter change(s) each moved the digest" % len(SENSITIVITY_OVERRIDES)


def _probe_parameter_sensitivity(fixture):
    """An *unchanged* spec must not be reported as a change: an always-different comparison is
    worthless."""
    parsed, baseline = fixture.run()
    _run, again = detect.detect_all(parsed, detect.resolve_spec())
    if canon.canonical_digest(again) != canon.canonical_digest(baseline):
        return False, "the same spec produced two different digests"
    return True, "an identical spec keeps the digest (the comparison can go both ways)"


# ---------------------------------------------------------------------------
# Check 5: the M1 profile guarantee still holds
# ---------------------------------------------------------------------------


def _check_profile_double_run(fixture):
    source = fixture.path("data/samples/minimal.csv")
    first = _profile_bytes(source)
    second = _profile_bytes(source)
    if first != second:
        return False, "profile output differs between two identical runs"
    return True, "profile is byte-identical across runs (%d bytes)" % len(first)


def _probe_profile_double_run(fixture):
    """A different timezone declaration must change the bytes, or the comparison is vacuous."""
    source = fixture.path("data/samples/minimal.csv")
    default = _profile_bytes(source)
    shifted = _profile_bytes(source, {"timezone_offset_min": 480})
    if default == shifted:
        return False, "a changed spec produced identical bytes"
    return True, "a changed spec changes the bytes (%d vs %d)" % (len(default), len(shifted))


def _profile_bytes(csv_path, spec=None):
    parsed = csvio.load_series(csv_path, spec)
    return canon.canonical_json_bytes(profile.build_profile(parsed, spec))


CHECKS = (
    ("frozen-artifacts-ledgered", _check_frozen_ledger, _probe_frozen_ledger),
    ("truth-reconciliation", _check_reconciliation, _probe_reconciliation),
    ("fixture-digest-frozen", _check_fixture_digest, _probe_fixture_digest),
    ("parameter-change-moves-digest", _check_parameter_sensitivity, _probe_parameter_sensitivity),
    ("profile-double-run-byte-identical", _check_profile_double_run, _probe_profile_double_run),
)


def run_checks(root):
    """Run every check and its falsification probe; a crash counts as a failing check."""
    fixture = Fixture(root)
    results = []
    for name, check, probe in CHECKS:
        ok, detail = _guarded(check, fixture)
        probe_ok, probe_detail = _guarded(probe, fixture)
        results.append(
            {
                "name": name,
                "ok": ok,
                "detail": detail,
                "probe_ok": probe_ok,
                "probe_detail": probe_detail,
            }
        )
    return results


def _guarded(step, fixture):
    try:
        return step(fixture)
    except Exception as exc:  # a crash is a defect, reported -- never a silent skip
        return False, "%s raised %s: %s" % (getattr(step, "__name__", "step"), type(exc).__name__, exc)


def cmd_selftest():
    """CLI body for `selftest`: 0 all green, 1 any defect, 4 fixtures unavailable."""
    from .cli import EXIT_ENV, EXIT_FAIL, EXIT_OK

    root = find_fixture_root()
    if root is None:
        print(
            "error: frozen fixtures not found from %s -- run `selftest` inside the repository "
            "(it needs data/synthetic/ and data/truth/)" % os.getcwd(),
            file=sys.stderr,
        )
        return EXIT_ENV

    results = run_checks(root)
    failing = 0
    for result in results:
        marker = "ok" if result["ok"] else "FAIL"
        probe_marker = "probe ok" if result["probe_ok"] else "probe FAIL"
        print("[%s] %s: %s" % (marker, result["name"], result["detail"]))
        print("       [%s] %s" % (probe_marker, result["probe_detail"]))
        if not result["ok"] or not result["probe_ok"]:
            failing += 1
    print("selftest: %d check(s), %d failing (root %s)" % (len(results), failing, root))
    return EXIT_FAIL if failing else EXIT_OK
