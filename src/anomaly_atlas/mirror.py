"""Browser recomputation support (M3): the artifact contract, the Node harness, `verify`.

API:
  CONTRACT_VERSION / MIRROR_VERSION                   # the two versions this file pins
  SHA256_VECTORS                                      # known vectors, shared by both languages
  ArtifactError
  load_mirror_js() -> str                             # src/anomaly_atlas/mirror/zaa_mirror.js
  extract_artifact(html_text) -> dict                 # {payload, mirror_source}
  expected_block(payload) -> dict                     # {"canonical", "sha256", "points"}
  tamper_payload(payload, index) -> (payload, record)
  run_node_mirror(...) -> dict                        # the verdict, straight from Node
  verify_artifact(html_path, node_exe, tamper_index) -> dict   # one place, used by CLI and tool
  cmd_verify(html_path, node_exe, tamper_index) -> int

`zaa_mirror.js` is a hand-written JavaScript re-implementation of detect/episodes/canon (plus a
self-contained SHA-256): it mirrors the Python statement order on purpose, because the whole
product claim is that both sides re-derive the same digest. Node is the automated channel; the
in-page badge is the human one. A missing Node exits 4 -- never a silent skip that a green run
could hide behind (plan/06 D8).

The gate runs the artifact's *own* copy of the mirror, and tampers with the *inlined* data the
mirror consumes: the probe has to bite at the consumption point, or it proves nothing about the
thing that shipped.
"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# Version of the HTML embedding contract (which blocks an artifact carries and under which ids).
CONTRACT_VERSION = "1"
# Version of the JavaScript mirror's implementation. Bump it when the mirror's statements change.
MIRROR_VERSION = "1"

# Script element ids of the embedding contract (plan/03 M3). Single definition point: render.py
# imports them when it writes the artifact, this module uses them to read it back.
SCRIPT_ID_PAYLOAD = "zaa-payload"
SCRIPT_ID_MIRROR = "zaa-mirror"

MIRROR_RELATIVE_PATH = os.path.join("mirror", "zaa_mirror.js")

# SHA-256 known vectors (plan/02 3.4, K13), shared by the Python and the JavaScript assertion:
# the empty string, "abc", a length just past one padding block (55/56), a length just past a
# whole 64-byte block (64/65), a longer printable message, and a multi-byte UTF-8 case. The
# digests are literals, so neither side can "agree" with a broken implementation.
SHA256_VECTORS = (
    ("", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    ("abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    ("a" * 55, "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318"),
    ("a" * 56, "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a"),
    ("a" * 64, "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb"),
    ("a" * 65, "635361c48bb9eab14198e76ea8ab7f1a41685d6ad62aa9146d301d4f17eb0ae0"),
    (
        "timeseries-anomaly-atlas" * 4,
        "5a8163d98f3a12f0690158c54fc45876042a4a4c9d4f22c6a78a6e84e1e77503",
    ),
    ("冷链仓储温控与能耗监测（虚构）", "b5c479714cb35cbf3dfcee3efe5b8d16fbbc71f8fd8c9c8914c6cd2879d1dfa1"),
)

# A large, deterministic displacement for the falsification probe: the series' own span times 1000
# (a constant series falls back to 10^6). Big enough that no plausible detector can miss it, and
# derived from the data rather than from a magic number that would silently stop being an outlier.
TAMPER_SPAN_FACTOR = 1000.0
TAMPER_CONSTANT_OFFSET = 1000000.0

_SCRIPT_RE = re.compile(
    r"<script\b[^>]*\bid=\"(?P<id>[^\"]+)\"[^>]*>(?P<body>.*?)</script>", re.DOTALL | re.IGNORECASE
)

# The Node harness: the artifact's own mirror source, then the smallest possible driver. It first
# re-checks the shared SHA-256 known vectors (so the digest the verdict rests on is itself
# checked), then recomputes, then prints one JSON line so Python never parses prose.
HARNESS_JS = """
/* Node channel harness (verify / mirror_parity): drives the mirror that was inlined in the
   artifact, checks it against the shared SHA-256 known vectors, and prints one JSON line. */
var harnessFs = require("fs");
var harnessPayload = JSON.parse(harnessFs.readFileSync(process.argv[2], "utf8"));
var harnessExpected = JSON.parse(harnessFs.readFileSync(process.argv[3], "utf8"));
var harnessVectors = JSON.parse(harnessFs.readFileSync(process.argv[4], "utf8"));
var harnessBadVectors = [];
for (var harnessIndex = 0; harnessIndex < harnessVectors.length; harnessIndex = harnessIndex + 1) {
  var harnessWant = harnessVectors[harnessIndex][1];
  var harnessGot = ZAA.sha256Hex(ZAA.utf8Bytes(harnessVectors[harnessIndex][0]));
  if (harnessGot !== harnessWant) {
    harnessBadVectors.push([harnessIndex, harnessWant, harnessGot]);
  }
}
var harnessResult = ZAA.recompute(harnessPayload);
var harnessOutput = {
  vectors: harnessBadVectors,
  verdict: ZAA.verdict(harnessResult, harnessExpected, null)
};
process.stdout.write(JSON.stringify(harnessOutput));
process.stdout.write("\\n");
"""

# Fixed-point agreement vectors: the mirror has to reproduce the kernel's half-to-even
# quantisation and its integer-built display string for *any* input, not merely agree on the
# fixture's digest. The digest is a weak probe here and this was measured, not assumed: mutating the
# half-to-even boundary in the mirror from `frac > 0.5` to `frac > 0.4999995` left the frozen-fixture
# parity test green, because no score in the fixture lands inside that 5e-7-wide window. The ties
# are the point, so they are spelled out.
FIXED_POINT_VECTORS = (
    (0.5, 0),
    (1.5, 0),
    (2.5, 0),
    (3.5, 0),
    (-0.5, 0),
    (-1.5, 0),
    (-2.5, 0),
    (0.0, 0),
    (-0.0, 0),
    (0.25, 1),
    (0.125, 3),
    (12.345, 6),
    (-12.3456, 6),
    (123456789.123456, 6),
    (0.0000004, 6),
    (0.0000005, 6),
    (0.0000015, 6),
    (0.5, 6),
    (1.4826, 6),
    (-3.5, 3),
)

# The ties above have unambiguous answers, so they are pinned as literals as well as cross-checked
# against `canon.quantize`: two implementations that agree on a wrong rule would still "agree".
FIXED_POINT_TIES = ((0.5, 0, 0), (1.5, 0, 2), (2.5, 0, 2), (-0.5, 0, 0), (-1.5, 0, -2), (-2.5, 0, -2))

# The Node driver for the fixed-point gate (same shape as the main harness: the artifact's mirror
# source, plus a few lines of glue).
FIXED_POINT_HARNESS_JS = """
/* Node channel harness: the mirror's fixed-point helpers over the shared vectors. */
var harnessFs = require("fs");
var harnessVectors = JSON.parse(harnessFs.readFileSync(process.argv[2], "utf8"));
var harnessQuantized = [];
var harnessStrings = [];
for (var harnessIndex = 0; harnessIndex < harnessVectors.length; harnessIndex = harnessIndex + 1) {
  var harnessDecimals = harnessVectors[harnessIndex][1];
  var harnessQ = ZAA.quantize(harnessVectors[harnessIndex][0], harnessDecimals);
  harnessQuantized.push(harnessQ);
  harnessStrings.push(ZAA.fixedToStr(harnessQ, harnessDecimals));
}
process.stdout.write(JSON.stringify({quantized: harnessQuantized, strings: harnessStrings}));
process.stdout.write("\\n");
"""

# Node's two remediation paths when it is missing (plan/03 M3): never a silent skip.
NODE_REMEDIES = (
    "install Node.js and re-run (for example `winget install OpenJS.NodeJS` on Windows, "
    "`apt-get install nodejs` on Debian/Ubuntu), or pass --node <path-to-node>",
    "check the human channel instead: open the artifact in a browser (no network needed) and "
    "read the VERIFIED / MISMATCH badge",
)


class ArtifactError(ValueError):
    """The file is not an artifact of this contract (wrong shape, broken JSON, missing block)."""


class MirrorRunError(RuntimeError):
    """Node could not run the mirror (crashed, or produced something that is not a verdict)."""


def load_mirror_js():
    """Return the inlinable mirror source, read from next to this module."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), MIRROR_RELATIVE_PATH)
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8")


def _script_body(html_text, script_id):
    for match in _SCRIPT_RE.finditer(html_text):
        if match.group("id") == script_id:
            return match.group("body")
    return None


def extract_artifact(html_text):
    """Read the embedded contract back out of an artifact.

    Returns `{"payload": dict, "mirror_source": str}`. A missing block or unreadable payload is an
    `ArtifactError` -- "this is not an artifact of the contract" is an input error, not a mismatch.
    """
    payload_text = _script_body(html_text, SCRIPT_ID_PAYLOAD)
    if payload_text is None:
        raise ArtifactError("no <%s> block: this is not a recomputation artifact" % SCRIPT_ID_PAYLOAD)
    try:
        payload = json.loads(payload_text)
    except ValueError as exc:
        raise ArtifactError("the %s block is not readable JSON: %s" % (SCRIPT_ID_PAYLOAD, exc))
    if not isinstance(payload, dict):
        raise ArtifactError("the %s block must be a JSON object" % SCRIPT_ID_PAYLOAD)
    for key in ("run", "series", "detections", "anomaly_set_canonical", "anomaly_set_sha256"):
        if key not in payload:
            raise ArtifactError("the %s block has no %r key" % (SCRIPT_ID_PAYLOAD, key))
    mirror_source = _script_body(html_text, SCRIPT_ID_MIRROR)
    if mirror_source is None:
        raise ArtifactError("no <%s> block: the artifact carries no mirror to run" % SCRIPT_ID_MIRROR)
    return {"payload": payload, "mirror_source": mirror_source}


def expected_block(payload):
    """The build-time side of the comparison, taken from the artifact itself."""
    return {
        "canonical": payload["anomaly_set_canonical"],
        "sha256": payload["anomaly_set_sha256"],
        "points": payload["detections"],
    }


def inline_points(payload):
    """The inlined samples in the order `--tamper-index` counts: series as stored, then rows."""
    order = []
    for series_index, series in enumerate(payload.get("series", ())):
        for row_index in range(len(series.get("rows", ()))):
            order.append((series_index, row_index))
    return order


def tamper_payload(payload, index):
    """Change exactly one inlined sample, and say which one.

    Returns `(tampered_payload, record)`. The original payload is not modified, so a caller can
    still compare against the untouched build fingerprint (the probe is only meaningful on a
    healthy artifact). Out-of-range indices raise `IndexError`.
    """
    order = inline_points(payload)
    if index < 0 or index >= len(order):
        raise IndexError(
            "tamper index %d is outside the %d inlined sample(s)" % (index, len(order))
        )
    series_index, row_index = order[index]
    tampered = copy.deepcopy(payload)
    series = tampered["series"][series_index]
    row = series["rows"][row_index]
    present = [float(cell[1]) for cell in series["rows"] if cell[1] is not None]
    if present:
        span = max(present) - min(present)
        offset = span * TAMPER_SPAN_FACTOR if span > 0 else TAMPER_CONSTANT_OFFSET
    else:
        offset = TAMPER_CONSTANT_OFFSET
    original = row[1]
    row[1] = repr((0.0 if original is None else float(original)) + offset)
    record = {
        "inline_index": index,
        "series_id": series["series_id"],
        "row_index": row_index,
        "row_no": row[2],
        "original": original,
        "tampered": row[1],
    }
    return tampered, record


def run_node_mirror(payload, expected, mirror_source, node_executable):
    """Run one mirror source under Node and return `{"vectors": [...], "verdict": {...}}`.

    The harness is `mirror_source` + `HARNESS_JS`, so the code that runs is the code the artifact
    shipped (not a freshly read repository copy) -- and a test can hand in a deliberately broken
    source to prove the harness notices.
    """
    stdout = _run_node_program(
        mirror_source + HARNESS_JS,
        node_executable,
        (
            (
                "payload.json",
                json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
            ),
            (
                "expected.json",
                json.dumps(expected, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
            ),
            (
                "vectors.json",
                json.dumps([list(vector) for vector in SHA256_VECTORS], ensure_ascii=False, indent=2)
                + "\n",
            ),
        ),
    )
    outcome = _last_json_line(stdout)
    if not isinstance(outcome, dict) or "verdict" not in outcome or "vectors" not in outcome:
        raise MirrorRunError("the mirror printed an unexpected object: %r" % (outcome,))
    return outcome


def run_node_fixed_point(mirror_source, node_executable):
    """Run the mirror's fixed-point helpers over the shared vectors; return `{quantized, strings}`.

    Separated from the parity run on purpose: `verify` answers "does this artifact reproduce its
    fingerprint", and a boundary the fixture never crosses does not change that answer. General
    cross-language agreement of the fixed-point rule is a library-level claim (K13) and is checked
    where it belongs -- against vectors, not against one dataset's digest.
    """
    stdout = _run_node_program(
        mirror_source + FIXED_POINT_HARNESS_JS,
        node_executable,
        (
            (
                "fixed-point.json",
                json.dumps([list(vector) for vector in FIXED_POINT_VECTORS], ensure_ascii=False, indent=2)
                + "\n",
            ),
        ),
    )
    outcome = _last_json_line(stdout)
    if not isinstance(outcome, dict) or "quantized" not in outcome or "strings" not in outcome:
        raise MirrorRunError("the mirror printed an unexpected object: %r" % (outcome,))
    return outcome


def _run_node_program(program, node_executable, data_files):
    """Write one program plus its data files into a throwaway directory and run it under Node.

    A non-zero exit or an unexecutable Node is a `MirrorRunError`, which callers report as a defect
    rather than as a mismatch. Cleanup is unconditional: this gate must not litter a repository it
    is checking.
    """
    directory = tempfile.mkdtemp(prefix="zaa-node-")
    try:
        program_path = os.path.join(directory, "program.js")
        argument_paths = []
        for name, text in data_files:
            path = os.path.join(directory, name)
            _write_text(path, text)
            argument_paths.append(path)
        _write_text(program_path, program)
        try:
            completed = subprocess.run(
                [node_executable, program_path] + argument_paths,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise MirrorRunError("cannot execute %s: %s" % (node_executable, exc))
        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")
        if completed.returncode != 0:
            raise MirrorRunError(
                "the mirror exited with %d: %s" % (completed.returncode, stderr.strip()[:2000])
            )
        return stdout
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _last_json_line(stdout):
    line = stdout.strip().splitlines()[-1] if stdout.strip() else ""
    try:
        return json.loads(line)
    except ValueError:
        raise MirrorRunError("the mirror did not print a JSON result: %r" % (stdout[:400],))


def _write_text(path, text):
    """Explicit encoding on the way out (K10): never the console's default code page."""
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-8"))


def verify_artifact(html_path, node_exe="node", tamper_index=None):
    """Recompute one artifact and report the verdict.

    Returns a dict:
      {"status": "verified"|"mismatch"|"probe-failed"|"usage"|"missing-node"|"run-error",
       "detail": str, "verdict": dict|None, "tamper": dict|None}
    so the CLI and tools/mirror_parity.py share one implementation instead of two.
    """
    if not os.path.isfile(html_path):
        return {
            "status": "usage",
            "detail": "HTML artifact not found: %s" % html_path,
            "verdict": None,
            "tamper": None,
        }
    try:
        with open(html_path, "rb") as handle:
            html_text = handle.read().decode("utf-8", "replace")
    except OSError as exc:
        return {"status": "usage", "detail": "cannot read %s: %s" % (html_path, exc), "verdict": None, "tamper": None}
    try:
        artifact = extract_artifact(html_text)
    except ArtifactError as exc:
        return {"status": "usage", "detail": "%s: %s" % (html_path, exc), "verdict": None, "tamper": None}

    payload = artifact["payload"]
    expected = expected_block(payload)
    tamper = None
    if tamper_index is not None:
        try:
            payload, tamper = tamper_payload(payload, tamper_index)
        except IndexError as exc:
            return {"status": "usage", "detail": str(exc), "verdict": None, "tamper": None}

    node = shutil.which(node_exe)
    if node is None:
        return {
            "status": "missing-node",
            "detail": "Node executable not found: %s" % node_exe,
            "verdict": None,
            "tamper": tamper,
        }
    try:
        outcome = run_node_mirror(payload, expected, artifact["mirror_source"], node)
    except MirrorRunError as exc:
        return {"status": "run-error", "detail": str(exc), "verdict": None, "tamper": tamper}

    if outcome["vectors"]:
        return {
            "status": "vector-failed",
            "detail": "; ".join(
                "vector #%d: expected %s, got %s" % (index, want, got)
                for index, want, got in outcome["vectors"][:3]
            ),
            "verdict": outcome["verdict"],
            "tamper": tamper,
        }
    verdict = outcome["verdict"]

    if tamper is None:
        status = "verified" if verdict["verified"] else "mismatch"
        return {"status": status, "detail": "", "verdict": verdict, "tamper": None}

    problem = _probe_problem(verdict, tamper)
    if problem:
        return {"status": "probe-failed", "detail": problem, "verdict": verdict, "tamper": tamper}
    return {"status": "mismatch", "detail": "", "verdict": verdict, "tamper": tamper}


def _probe_problem(verdict, tamper):
    """Why the falsification probe did not do its job, or "" when it did.

    The probe has to (a) go red and (b) localise to the tampered series. "Went red for some other
    reason" is a failed probe, not a passed one -- a gate that cannot attribute its own red to the
    defect it injected is a gate that could be red because it is broken.
    """
    if verdict["verified"]:
        return (
            "the tamper at inline index %d (series %s, row %s) did not move the result -- the probe "
            "proves nothing and is reported as a failure" % (tamper["inline_index"], tamper["series_id"], tamper["row_no"])
        )
    difference = verdict.get("first_point_diff")
    if difference is None:
        return "the tamper moved the digest but no first difference was reported"
    located = difference.get("series_id")
    if located != tamper["series_id"]:
        return "the first difference is in series %r, not in the tampered series %r" % (
            located,
            tamper["series_id"],
        )
    return ""


def cmd_verify(html_path, node_exe="node", tamper_index=None):
    """CLI body for `verify`: 0 verified, 1 mismatch/defect, 2 input error, 4 Node missing."""
    from .cli import EXIT_ENV, EXIT_FAIL, EXIT_OK, EXIT_USAGE

    outcome = verify_artifact(html_path, node_exe or "node", tamper_index)
    status = outcome["status"]

    if status == "usage":
        print("error: %s" % outcome["detail"], file=sys.stderr)
        return EXIT_USAGE

    if status == "missing-node":
        print("error: %s" % outcome["detail"], file=sys.stderr)
        print("hint: the recomputation gate is not skipped when Node is missing (exit 4).", file=sys.stderr)
        for remedy in NODE_REMEDIES:
            print("hint: %s" % remedy, file=sys.stderr)
        return EXIT_ENV

    if status == "run-error":
        print("error: the browser mirror could not be run: %s" % outcome["detail"], file=sys.stderr)
        return EXIT_FAIL

    if status == "vector-failed":
        print(
            "error: the artifact's SHA-256 disagrees with the shared known vectors (%s)"
            % outcome["detail"],
            file=sys.stderr,
        )
        return EXIT_FAIL

    verdict = outcome["verdict"]
    tamper = outcome["tamper"]
    if tamper is not None:
        print(
            "tamper probe: inline index %d -> series %s, source row %s, %s -> %s"
            % (tamper["inline_index"], tamper["series_id"], tamper["row_no"], tamper["original"], tamper["tampered"])
        )

    if status == "probe-failed":
        print("probe FAIL: %s" % outcome["detail"], file=sys.stderr)
        return EXIT_FAIL

    if status == "verified":
        print("VERIFIED: recomputed %s == build %s" % (verdict["digest"], verdict["expected_digest"]))
        print("detector points, the canonical JSON and the digest all agree byte for byte")
        return EXIT_OK

    print(
        "MISMATCH: recomputed %s != build %s" % (verdict["digest"], verdict["expected_digest"]),
        file=sys.stderr,
    )
    print("first difference: %s" % _describe_difference(verdict), file=sys.stderr)
    return EXIT_FAIL


def _describe_difference(verdict):
    """A one-line, human-locatable description of where the recomputation first disagreed."""
    difference = verdict.get("first_point_diff")
    if difference is not None:
        if difference.get("kind") == "point":
            return "point %s / %s / #%d: expected %s, recomputed %s" % (
                difference["series_id"],
                difference["detector"],
                difference["index"],
                difference["expected"],
                difference["actual"],
            )
        return "detector block layout differs: %s" % (difference,)
    if not verdict.get("canonical_equal", True):
        return "canonical JSON differs from byte %d onward" % (verdict.get("first_byte_diff", -1),)
    return "the digests differ although the canonical bytes and the points agree"
