"""M3 gate: Node recomputation parity for an artifact, and the carrier-page builder.

Usage:
  python tools/mirror_parity.py --html <artifact> [--node <exe>] [--tamper-index <n>]
  python tools/mirror_parity.py --build <out.html> [--csv <csv>] [--spec <spec.json>]

`--html` is the machine-readable side of the M3 hard gate: the artifact's own inlined mirror is
executed under Node over the artifact's own inlined samples, and its canonical JSON / sha256 must
match the build values byte for byte. The browser badge is the human-readable side of the same
check (plan/03 M3) -- this is the side CI can run.

`--tamper-index n` is the falsification probe: one inlined sample (in the order the artifact stores
them: series, then row) is displaced by a large deterministic offset, and the run must go red
*and* localise the first difference to that series. A probe that stays green, or that goes red
without naming the series it broke, is reported as a failure -- otherwise a green tick could mean
"the gate is broken" rather than "the artifact is right".

`--build` writes the M3 minimal carrier page (the embedding contract landed in `render.py`; M4
reuses it for the full annotated view). It exists so the artifact CI verifies is *built* by the
repository, not hand-maintained.

Exit codes (plan/06 D8): 0 verified / 1 mismatch or failed probe / 2 usage or input error /
4 environment precondition unmet (no Node -- never a silent skip).
"""

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO_ROOT, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from anomaly_atlas import canon, mirror  # noqa: E402
from anomaly_atlas.cli import _ensure_utf8_stdio  # noqa: E402  (K10: single definition point)
from anomaly_atlas.render import write_carrier  # noqa: E402

DEFAULT_CSV = os.path.join(_REPO_ROOT, "data", "synthetic", "series.csv")


def _load_spec(path):
    """Read a run-spec JSON file, or raise ValueError with the reason."""
    import json

    with open(path, "rb") as handle:
        document = json.loads(handle.read().decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("run-spec must be a JSON object: %s" % path)
    return document


def _build(out_path, csv_path, spec_path):
    """Build the carrier page and report the digest it committed to."""
    spec = None
    if spec_path:
        if not os.path.isfile(spec_path):
            print("error: run-spec file not found: %s" % spec_path, file=sys.stderr)
            return 2
        try:
            spec = _load_spec(spec_path)
        except (ValueError, OSError) as exc:
            print("error: run-spec is not readable JSON: %s" % (exc,), file=sys.stderr)
            return 2
    if not os.path.isfile(csv_path):
        print("error: CSV not found: %s" % csv_path, file=sys.stderr)
        return 2
    try:
        _run_document, anomaly_set = write_carrier(csv_path, out_path, spec)
    except Exception as exc:  # a build failure is an input problem, reported with its reason
        print("error: cannot build the carrier page: %s" % (exc,), file=sys.stderr)
        return 2
    print("built %s" % out_path)
    print("anomaly-set sha256 %s" % canon.canonical_digest(anomaly_set))
    return 0


def main(argv=None):
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="mirror_parity.py",
        description="Run an artifact's inlined JS mirror under Node and compare it with the build fingerprint.",
    )
    parser.add_argument("--html", default=None, help="Artifact to verify (the M3 hard gate).")
    parser.add_argument("--build", default=None, help="Build the M3 carrier page at this path.")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="CSV for --build (default: the frozen fixture).")
    parser.add_argument("--spec", default=None, help="Run-spec JSON for --build.")
    parser.add_argument("--node", default="node", help="Node executable name or path.")
    parser.add_argument(
        "--tamper-index",
        type=int,
        default=None,
        help="Falsification probe: displace one inlined sample and require a localised mismatch.",
    )
    args = parser.parse_args(argv)

    if args.html is None and args.build is None:
        parser.print_help(sys.stderr)
        print("error: give --html (verify) and/or --build (build the carrier page)", file=sys.stderr)
        return 2

    if args.build is not None:
        status = _build(args.build, args.csv, args.spec)
        if status != 0:
            return status

    if args.html is None:
        return 0

    # The verify side is `mirror.cmd_verify` itself: the CLI command and this tool must not be two
    # implementations of one gate (a tool that could disagree with the shipped command is worse
    # than no tool).
    return mirror.cmd_verify(args.html, args.node, args.tamper_index)


if __name__ == "__main__":
    sys.exit(main())
