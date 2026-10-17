"""CLI entry: orchestration + exit-code contract (plan/06 D8) + encoding guard.

Exit codes (locked in tests):
  0 = success
  1 = gate / selftest found a defect (product is wrong)
  2 = usage / input error (missing file, schema failure, unknown subcommand)
  3 = stage not ready (module not landed yet; skeleton-only marker, retired per milestone)
  4 = environment precondition unmet (e.g. `verify` cannot find Node) -- never silent-skip

`3` is a skeleton-phase marker: each time a module lands, its key is removed from
STAGE_NOT_READY in the same commit (constant -> CLI -> tests -> docs -> decision record,
five places in sync). When STAGE_NOT_READY is empty, EXIT_NOT_READY is deleted outright.
"""

import argparse
import os
import sys

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_NOT_READY = 3
EXIT_ENV = 4

# Every subcommand. Public so that tests can assert the help text, the stage marker and
# the input-precondition table stay in sync whenever a command is added.
COMMANDS = ("profile", "detect", "render", "verify", "check-report", "selftest")

# command -> milestone that lands it. Empty = nothing left unwired anywhere.
STAGE_NOT_READY = {
    "verify": "M3",
    "render": "M4",
    "check-report": "M5",
}


def _ensure_utf8_stdio():
    """Reconfigure stdio to UTF-8 when the console encoding is not UTF-8.

    cp936 / gbk (Chinese Windows console) is left untouched: it renders CJK fine and
    reconfiguring it would break other tools sharing the console.
    """
    for stream in (sys.stdout, sys.stderr):
        enc = getattr(stream, "encoding", None)
        if not enc:
            continue
        norm = enc.lower().replace("-", "").replace("_", "")
        if norm in ("utf8", "cp936", "gbk", "gb2312", "gb18030"):
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass


def build_parser():
    from . import VERSION

    parser = argparse.ArgumentParser(
        prog="anomaly-atlas",
        description=(
            "Time series -> reproducible anomaly archive: episodes with detector, params, "
            "score and source rows, plus a single-file HTML that recomputes the same sha256."
        ),
    )
    parser.add_argument("--version", action="version", version="anomaly-atlas %s" % VERSION)
    sub = parser.add_subparsers(dest="command")

    p_profile = sub.add_parser(
        "profile", help="Profile a CSV series (timeline, cadence, gaps, missing/zero runs)."
    )
    p_profile.add_argument("csv", help="Path to the long-format CSV (timestamp, value[, series_id]).")
    p_profile.add_argument("-o", "--output", default="profile.json", help="Output profile JSON path.")

    p_detect = sub.add_parser(
        "detect", help="Run the 4 detectors, merge episodes, emit run.json/anomalies.json/sha256."
    )
    p_detect.add_argument("csv", help="Path to the long-format CSV.")
    p_detect.add_argument("--spec", default=None, help="Run-spec JSON (defaults applied and recorded).")
    p_detect.add_argument("--out-dir", default="out", help="Output directory for run.json/anomalies.json/facts.json.")

    p_render = sub.add_parser("render", help="Render the single-file HTML anomaly archive.")
    p_render.add_argument("csv", help="Path to the long-format CSV.")
    p_render.add_argument("-o", "--output", required=True, help="Output HTML path.")
    p_render.add_argument("--spec", default=None, help="Run-spec JSON.")
    p_render.add_argument("--narrative", default=None, help="Narrative text (numbers must hit facts.json).")

    p_verify = sub.add_parser(
        "verify", help="Recompute the embedded JS mirror through Node and compare with the build fingerprint."
    )
    p_verify.add_argument("html", help="Path to the rendered HTML artifact.")
    p_verify.add_argument("--node", default="node", help="Node executable name or path.")
    p_verify.add_argument("--tamper-index", type=int, default=None, help="Falsifiable probe: tamper one inlined point.")

    p_check_report = sub.add_parser(
        "check-report", help="Gate narrative numbers against facts.json (exit 1 on any miss)."
    )
    p_check_report.add_argument("--facts", required=True, help="Path to facts.json.")
    p_check_report.add_argument("--text", required=True, help="Path to the narrative text to gate.")

    sub.add_parser("selftest", help="Run the built-in falsifiable check suite (fixtures, truth, double run, probes).")

    return parser


def _require_file(path, what="input file"):
    if not os.path.isfile(path):
        print("error: %s not found: %s" % (what, path), file=sys.stderr)
        return False
    return True


# Input preconditions per command: (argparse dest, human-readable name).
_REQUIRED_INPUTS = {
    "profile": (("csv", "CSV"),),
    "detect": (("csv", "CSV"),),
    "render": (("csv", "CSV"),),
    "verify": (("html", "HTML artifact"),),
    "check-report": (("facts", "facts.json"), ("text", "narrative text")),
}


def main(argv=None):
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    # Input preconditions are checked before the stage marker, and the file check sits in
    # front of the not-yet-landed import: "your path is wrong" is a usage error whether or
    # not the command's module has landed, and this ordering keeps that contract testable
    # from M0 for every command.
    for dest, what in _REQUIRED_INPUTS.get(args.command, ()):
        if not _require_file(getattr(args, dest), what):
            return EXIT_USAGE

    if args.command in STAGE_NOT_READY:
        print(
            "stage not ready: '%s' is scheduled for milestone %s (skeleton only, no fake output)"
            % (args.command, STAGE_NOT_READY[args.command]),
            file=sys.stderr,
        )
        return EXIT_NOT_READY

    if args.command == "profile":
        from .profile import cmd_profile

        return cmd_profile(args.csv, args.output)

    if args.command == "detect":
        from .detect import cmd_detect

        return cmd_detect(args.csv, args.spec, args.out_dir)

    if args.command == "render":
        from .render import cmd_render

        return cmd_render(args.csv, args.output, args.spec, args.narrative)

    if args.command == "verify":
        from .mirror import cmd_verify

        return cmd_verify(args.html, args.node, args.tamper_index)

    if args.command == "check-report":
        from .report import cmd_check_report

        return cmd_check_report(args.facts, args.text)

    if args.command == "selftest":
        from .selftest import cmd_selftest

        return cmd_selftest()

    parser.print_help(sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
