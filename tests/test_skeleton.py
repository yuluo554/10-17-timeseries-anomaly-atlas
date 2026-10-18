"""M0 skeleton tests: exit-code contract + encoding guard + no-fake-stub gate.

These tests are loadable two ways on purpose: with `PYTHONPATH=src` (source mode) and
after `pip install -e .` (CI). They import the package instead of loading cli.py by
path, so relative imports inside the package behave exactly as they do for users.
"""

import io
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SRC = os.path.join(_REPO, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from anomaly_atlas import cli  # noqa: E402

# Required arguments per command. Kept next to the placeholder registry so that adding a
# command without test arguments fails loudly instead of silently shrinking the suite
# (a parametrized test that quietly stops covering a command is worse than no test).
_ARGS_BY_COMMAND = {
    "profile": ["x.csv"],
    "detect": ["x.csv"],
    "selftest": [],
    "verify": ["x.html"],
    "render": ["x.csv", "-o", "o.html"],
    "check-report": ["--facts", "f.json", "--text", "t.txt"],
}

# Input files each command requires to exist (empty = no file precondition).
_INPUT_FILES = {
    "profile": ("in.csv",),
    "detect": ("in.csv",),
    "selftest": (),
    "verify": ("in.html",),
    "render": ("in.csv",),
    "check-report": ("facts.json", "narrative.txt"),
}

_SENTINELS = ("NotImplementedError", "TODO: 实现", "placeholder")


def _argv_with_existing_inputs(command, tmp_path):
    """Same command line as _ARGS_BY_COMMAND, but with inputs that actually exist."""
    for name in _INPUT_FILES[command]:
        (tmp_path / name).write_text("stub", encoding="utf-8")
    path = lambda name: str(tmp_path / name)  # noqa: E731
    if command == "render":
        return ["render", path("in.csv"), "-o", path("out.html")]
    if command == "check-report":
        return ["check-report", "--facts", path("facts.json"), "--text", path("narrative.txt")]
    return [command] + [path(name) for name in _INPUT_FILES[command]]


class TestExitCodeContract:
    """plan/02 section 5 / plan/06 D8: 0 ok, 1 gate defect, 2 usage, 4 env. `3` is retired (M5)."""

    def test_codes_are_distinct_and_pinned(self):
        assert (cli.EXIT_OK, cli.EXIT_FAIL, cli.EXIT_USAGE, cli.EXIT_ENV) == (0, 1, 2, 4)

    def test_the_not_ready_constant_is_gone(self):
        # Retiring the last registry key deletes the constant itself (K1): a `3` left behind would
        # be an invitation for a "not ready" answer to grow back.
        assert not hasattr(cli, "EXIT_NOT_READY")
        assert 3 not in (cli.EXIT_OK, cli.EXIT_FAIL, cli.EXIT_USAGE, cli.EXIT_ENV)

    def test_no_args_is_usage_error(self, capsys):
        assert cli.main([]) == cli.EXIT_USAGE
        capsys.readouterr()

    def test_unknown_command_is_usage_error(self):
        # argparse rejects an invalid subcommand with SystemExit(2); the contract is the
        # exit code itself, whichever path raises it.
        with pytest.raises(SystemExit) as exc:
            cli.main(["bogus-command"])
        assert exc.value.code == cli.EXIT_USAGE

    def test_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
        assert exc.value.code == cli.EXIT_OK

    def test_version_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--version"])
        assert exc.value.code == cli.EXIT_OK
        assert "anomaly-atlas" in capsys.readouterr().out

    def test_all_commands_registered(self):
        help_text = cli.build_parser().format_help()
        for name in _ARGS_BY_COMMAND:
            assert name in help_text

    @pytest.mark.parametrize("command", sorted(c for c in _ARGS_BY_COMMAND if _INPUT_FILES[c]))
    def test_missing_file_is_usage_error(self, command, capsys):
        # The input precondition sits in front of the not-yet-landed import, so this
        # contract is exercised from M0 for every command, landed or not: a wrong path is
        # a usage error, never a stage-not-ready answer.
        assert cli.main([command] + _ARGS_BY_COMMAND[command]) == cli.EXIT_USAGE
        capsys.readouterr()


class TestCommandRegistryConsistency:
    """Adding a subcommand must not leave help text, the stage marker and the test-side
    argument table out of sync (a command with no test args shrinks coverage silently)."""

    @staticmethod
    def _parser_commands():
        text = cli.build_parser().format_help()
        match = re.search(r"\{([a-z0-9,\-]+)\}", text)
        assert match, "subcommand choice list not found in help text"
        return set(match.group(1).split(","))

    def test_extractor_actually_reads_the_help_text(self):
        # Positive control: an extractor that returns an empty/garbage set would make the
        # equality assertions below pass for the wrong reason.
        extracted = self._parser_commands()
        assert "profile" in extracted and len(extracted) >= 2

    def test_help_text_matches_public_command_list(self):
        assert self._parser_commands() == set(cli.COMMANDS)

    def test_every_command_has_test_arguments_and_input_spec(self):
        assert set(cli.COMMANDS) == set(_ARGS_BY_COMMAND) == set(_INPUT_FILES)


class TestExitCodeThreeIsRetired:
    """plan/06 D14 + D23: every module landed, so no command answers 3 any more.

    Asserted positively -- by running each command -- rather than by inspecting the (now empty)
    registry: "the dictionary happens to have no keys" is not evidence about what the CLI answers.
    """

    def test_the_registry_is_empty(self):
        assert cli.STAGE_NOT_READY == {}

    def test_every_command_is_in_the_public_list(self):
        assert set(cli.STAGE_NOT_READY) <= set(cli.COMMANDS)

    @pytest.mark.parametrize(
        "command", sorted(command for command in _ARGS_BY_COMMAND if command != "selftest")
    )
    def test_no_command_answers_three(self, command, tmp_path, capsys):
        # Dummy inputs (the files exist but are not valid) reach the real dispatch and come back with
        # a usage error -- never with 3. `selftest` is excluded because running it for real costs a
        # full fixture sweep; the registry emptiness above covers it structurally.
        argv = _argv_with_existing_inputs(command, tmp_path)
        assert cli.main(argv) != 3
        capsys.readouterr()

    def test_selftest_does_not_answer_three_either(self):
        assert "selftest" not in cli.STAGE_NOT_READY


class _FakeStdio:
    def __init__(self, encoding):
        self.encoding = encoding
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


class TestEncodingGuard:
    """K10: a cp1252/ascii console gets reconfigured; a cp936 console is left alone."""

    def test_non_utf8_console_is_reconfigured(self, monkeypatch):
        fake = _FakeStdio("cp1252")
        monkeypatch.setattr(sys, "stdout", fake)
        monkeypatch.setattr(sys, "stderr", fake)
        cli._ensure_utf8_stdio()
        assert fake.calls == [{"encoding": "utf-8"}, {"encoding": "utf-8"}]

    def test_cp936_console_is_left_untouched(self, monkeypatch):
        fake = _FakeStdio("cp936")
        monkeypatch.setattr(sys, "stdout", fake)
        monkeypatch.setattr(sys, "stderr", fake)
        cli._ensure_utf8_stdio()
        assert fake.calls == []

    def test_utf8_console_is_left_untouched(self, monkeypatch):
        fake = _FakeStdio("utf-8")
        monkeypatch.setattr(sys, "stdout", fake)
        monkeypatch.setattr(sys, "stderr", fake)
        cli._ensure_utf8_stdio()
        assert fake.calls == []

    def test_stream_without_encoding_is_skipped(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())
        cli._ensure_utf8_stdio()


def _scan_for_sentinels(root):
    """Scan src/ and tools/ for stub sentinels. Returns [(relpath, lineno, token)]."""
    hits = []
    for base in (os.path.join(root, "src"), os.path.join(root, "tools")):
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "node_modules")]
            for filename in sorted(filenames):
                if not filename.endswith((".py", ".js")):
                    continue
                path = os.path.join(dirpath, filename)
                with io.open(path, encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for token in _SENTINELS:
                            if token in line:
                                hits.append((os.path.relpath(path, root).replace("\\", "/"), lineno, token))
    return hits


class TestNoSentinelStubs:
    """plan/06 D14 as an executed gate, with a falsifiable probe for the scanner itself."""

    def test_scan_scope_is_not_empty(self):
        # A scanner that walks nothing reports "clean" for the same reason an empty
        # directory does. Pin the scope before trusting the verdict.
        assert os.path.isdir(os.path.join(_REPO, "src"))
        py_files = [
            f
            for d, _, fs in os.walk(os.path.join(_REPO, "src"))
            for f in fs
            if f.endswith(".py")
        ]
        assert len(py_files) >= 10

    def test_repository_has_no_sentinel_stubs(self):
        assert _scan_for_sentinels(_REPO) == []

    def test_scanner_detects_an_injected_sentinel(self, tmp_path):
        # Mutation: break the behaviour the gate is supposed to catch, and the gate must
        # go red. Without this the gate could be a no-op that always passes.
        pkg = tmp_path / "src"
        pkg.mkdir()
        (pkg / "bad.py").write_text("def f():\n    raise NotImplementedError\n", encoding="utf-8")
        hits = _scan_for_sentinels(str(tmp_path))
        assert any(hit[2] == "NotImplementedError" and hit[0] == "src/bad.py" for hit in hits)


class TestVersionConsistency:
    """The package version and the packaging metadata must not drift apart."""

    def test_version_matches_pyproject(self):
        import anomaly_atlas

        with io.open(os.path.join(_REPO, "pyproject.toml"), encoding="utf-8") as fh:
            text = fh.read()
        match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
        assert match, "version not found in pyproject.toml"
        assert anomaly_atlas.VERSION == match.group(1)


class TestPackageShape:
    def test_planned_modules_are_importable(self):
        # Docstring-only modules: importable, documented, and carrying no behaviour that
        # could be mistaken for an implementation.
        import importlib

        for name in (
            "timebase",
            "csvio",
            "profile",
            "canon",
            "detect",
            "episodes",
            "layout",
            "render",
            "facts",
            "report",
            "mirror",
            "selftest",
        ):
            module = importlib.import_module("anomaly_atlas." + name)
            assert module.__doc__ and module.__doc__.strip()
