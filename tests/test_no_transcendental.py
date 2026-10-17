"""M2 mirrorability gate: no transcendental function, no library reduction, no `**` on the
detection path -- with a mutation test that proves the gate can go red.

The gate is an executed claim, not a comment in a design document. Python sources under
`src/anomaly_atlas/` are parsed with `ast` (so a call spelled across lines, aliased, or reached
through an attribute is still seen), any JavaScript is scanned lexically, and an explicit exemption
table exists so that an exemption is a reviewable line rather than an ad-hoc regex edit.

Why this is load-bearing rather than stylistic: `exp/log/sin/sqrt` are implemented by each
platform's libm and may differ by an ulp between CPython and V8, and a reduction's summation order
is an implementation detail of the library. Either would make the browser recomputation (M3) fail
intermittently, which is the one thing this project cannot survive.
"""

import ast
import io
import os
import re
import shutil

import pytest

from conftest import REPO_ROOT

SRC = os.path.join(REPO_ROOT, "src", "anomaly_atlas")

# Call names that must never appear: transcendentals (libm-dependent) plus the library reducers and
# roundings whose behaviour is not part of our specification.
BANNED_NAMES = frozenset(
    (
        "exp",
        "expm1",
        "log",
        "log1p",
        "log2",
        "log10",
        "pow",
        "sqrt",
        "cbrt",
        "hypot",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "sinh",
        "cosh",
        "tanh",
        "asinh",
        "acosh",
        "atanh",
        "degrees",
        "radians",
        "fsum",
        "prod",
        "dist",
        "isqrt",
        "comb",
        "perm",
        "factorial",
        "gamma",
        "lgamma",
        "erf",
        "erfc",
        "mean",
        "median",
        "median_low",
        "median_high",
        "median_grouped",
        "mode",
        "multimode",
        "quantiles",
        "pvariance",
        "variance",
        "pstdev",
        "stdev",
        "round",
    )
)

# Modules that must not be imported on the detection path: `random` (cross-version sequence is not
# promised), `statistics` (reduction order is a library detail), `datetime`/`time` (no clock may
# reach a product), `decimal`/`fractions` (their rounding is their own).
BANNED_MODULES = frozenset(
    ("random", "statistics", "numpy", "datetime", "time", "decimal", "fractions", "secrets", "uuid", "cmath")
)

# JavaScript tokens that carry the same hazards. `**`/`**=` and every `Math.<transcendental>`.
JS_BANNED_PATTERNS = (
    (r"\*\*", "** (exponent operator: expand into multiplication)"),
    (r"Math\.exp\s*\(", "Math.exp"),
    (r"Math\.log\w*\s*\(", "Math.log"),
    (r"Math\.pow\s*\(", "Math.pow"),
    (r"Math\.sqrt\s*\(", "Math.sqrt"),
    (r"Math\.cbrt\s*\(", "Math.cbrt"),
    (r"Math\.hypot\s*\(", "Math.hypot"),
    (r"Math\.(?:sin|cos|tan|asin|acos|atan|atan2|sinh|cosh|tanh)\s*\(", "Math trigonometric"),
    (r"Math\.round\s*\(", "Math.round"),
)

# file (relative to the package) -> set of tokens that file is allowed to carry, with the reason.
# Empty today: nothing on the detection path needs an exception, and the mechanism is exercised by
# a test so it cannot rot into decoration.
EXEMPTIONS = {}


def _python_sources(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ("__pycache__",)]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                found.append(os.path.join(dirpath, filename))
    return found


def _javascript_sources(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ("__pycache__", "node_modules")]
        for filename in sorted(filenames):
            if filename.endswith(".js"):
                found.append(os.path.join(dirpath, filename))
    return found


def scan_python(path, root):
    """Return `[(relative path, line, token)]` for banned constructs in one Python file."""
    with io.open(path, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=path)
    relative = os.path.relpath(path, root).replace("\\", "/")
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_MODULES:
                    hits.append((relative, node.lineno, "import %s" % alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in BANNED_MODULES:
                hits.append((relative, node.lineno, "from %s import" % node.module))
            for alias in node.names or ():
                if alias.name in BANNED_NAMES:
                    hits.append((relative, node.lineno, alias.name))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            hits.append((relative, node.lineno, "**"))
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Pow):
            hits.append((relative, node.lineno, "**"))
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_NAMES:
            hits.append((relative, node.lineno, node.attr))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_NAMES:
            # Builtins reached without an attribute, `round(a, 2)` / `pow(a, b)` included. Only
            # *calls* (and the attribute reads above) are banned: a local variable that happens to
            # be called `median` is not a library reduction, and flagging it would make the gate
            # red for a naming choice.
            hits.append((relative, node.lineno, node.func.id))
    return hits


def scan_javascript(path, root):
    """Return `[(relative path, line, token)]` for banned tokens in one JavaScript file."""
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    relative = os.path.relpath(path, root).replace("\\", "/")
    hits = []
    for number, line in enumerate(lines, 1):
        for pattern, label in JS_BANNED_PATTERNS:
            if re.search(pattern, line):
                hits.append((relative, number, label))
    return hits


def scan_tree(root, exemptions=None):
    """Scan a package tree; returns the hits that are not covered by the exemption table."""
    exemptions = EXEMPTIONS if exemptions is None else exemptions
    hits = []
    for path in _python_sources(root):
        hits.extend(scan_python(path, root))
    for path in _javascript_sources(root):
        hits.extend(scan_javascript(path, root))
    allowed = set()
    for relative, tokens in exemptions.items():
        for token in tokens:
            allowed.add((relative, token))
    return sorted(hit for hit in hits if (hit[0], hit[2]) not in allowed)


def copy_package(tmp_path):
    """A throwaway copy of the package to mutate, so the gate is exercised on real sources."""
    target = tmp_path / "anomaly_atlas"
    shutil.copytree(SRC, str(target), ignore=shutil.ignore_patterns("__pycache__"))
    return str(target)


def inject_into(path, line):
    """Append one module-level statement, so the file still parses and the gate has something to see."""
    with io.open(path, "a", encoding="utf-8") as handle:
        handle.write("\n" + line)


class TestScanScope:
    def test_the_python_scope_is_the_whole_package(self):
        sources = _python_sources(SRC)
        names = sorted(os.path.basename(path) for path in sources)
        assert len(sources) >= 12, names
        for expected in ("detect.py", "episodes.py", "canon.py", "selftest.py", "timebase.py"):
            assert expected in names

    def test_the_javascript_scope_is_wired_up(self):
        # No mirror lands until M3, so today the JS half finds nothing -- but the scanner must be
        # reachable and correct, which the mutation test below demonstrates on a real file.
        assert isinstance(_javascript_sources(SRC), list)

    def test_the_scanners_read_a_real_file(self, tmp_path):
        target = tmp_path / "sample.py"
        target.write_text("import math\nVALUE = math.floor(1.5)\n", encoding="utf-8")
        assert scan_python(str(target), str(tmp_path)) == []
        target.write_text("import math\nVALUE = math.exp(1.5)\n", encoding="utf-8")
        assert scan_python(str(target), str(tmp_path)) == [("sample.py", 2, "exp")]


class TestRepositoryIsClean:
    def test_no_banned_construct_on_the_detection_path(self):
        assert scan_tree(SRC) == []

    def test_floor_and_ceil_are_still_allowed(self):
        # Positive control: the gate must not be "flag everything". canon.py uses math.floor.
        with io.open(os.path.join(SRC, "canon.py"), encoding="utf-8") as handle:
            assert "math.floor" in handle.read()

    def test_builtin_reductions_used_by_the_code_are_allowed(self, tmp_path):
        # sum/min/max/abs/sorted are builtins with a defined left-to-right order, mirrored by an
        # explicit loop in JS; only library reducers whose order we do not control are banned.
        target = tmp_path / "allowed.py"
        target.write_text(
            "TOTAL = sum([1, 2, 3])\nLOW = min(1, 2)\nHIGH = max(1, 2)\nSIZE = abs(-3)\nORDERED = sorted([3, 1])\n",
            encoding="utf-8",
        )
        assert scan_python(str(target), str(tmp_path)) == []


class TestMutationIsDetected:
    """The gate's own falsification: break it and it must go red."""

    def test_the_unmodified_copy_is_clean(self, tmp_path):
        assert scan_tree(copy_package(tmp_path)) == []

    def test_a_transcendental_call_is_caught(self, tmp_path):
        root = copy_package(tmp_path)
        inject_into(os.path.join(root, "detect.py"), "INJECTED = __import__('math').exp(1.0)\n")
        hits = scan_tree(root)
        assert any(hit[2] == "exp" for hit in hits), hits

    def test_the_power_operator_is_caught(self, tmp_path):
        root = copy_package(tmp_path)
        inject_into(os.path.join(root, "detect.py"), "INJECTED = 2 ** 10\n")
        assert any(hit[2] == "**" for hit in scan_tree(root))

    def test_a_banned_module_import_is_caught(self, tmp_path):
        root = copy_package(tmp_path)
        inject_into(os.path.join(root, "detect.py"), "import statistics\n")
        assert any(hit[2] == "import statistics" for hit in scan_tree(root))

    def test_a_library_reduction_is_caught(self, tmp_path):
        root = copy_package(tmp_path)
        inject_into(os.path.join(root, "detect.py"), "INJECTED = statistics.mean([1.0])\n")
        assert any(hit[2] == "mean" for hit in scan_tree(root))

    def test_a_javascript_transcendental_is_caught(self, tmp_path):
        root = copy_package(tmp_path)
        with io.open(os.path.join(root, "mirror_sample.js"), "w", encoding="utf-8") as handle:
            handle.write("function z(x) { return Math.exp(x); }\n")
        hits = scan_tree(root)
        assert any(hit[0].endswith("mirror_sample.js") and hit[2] == "Math.exp" for hit in hits), hits

    def test_a_javascript_power_operator_is_caught(self, tmp_path):
        root = copy_package(tmp_path)
        with io.open(os.path.join(root, "mirror_sample.js"), "w", encoding="utf-8") as handle:
            handle.write("var w = t * t; var v = w ** 3;\n")
        hits = scan_tree(root)
        assert any(hit[0].endswith("mirror_sample.js") and hit[2].startswith("**") for hit in hits), hits

    def test_javascript_floor_and_abs_are_not_flagged(self, tmp_path):
        root = copy_package(tmp_path)
        with io.open(os.path.join(root, "mirror_sample.js"), "w", encoding="utf-8") as handle:
            handle.write("var q = Math.floor(x); var a = Math.abs(x); var c = Math.ceil(x);\n")
        assert scan_tree(root) == []


class TestExemptionTable:
    def test_an_exemption_suppresses_exactly_one_token_in_one_file(self, tmp_path):
        root = copy_package(tmp_path)
        inject_into(os.path.join(root, "detect.py"), "INJECTED = __import__('math').exp(1.0)\n")
        assert any(hit[2] == "exp" for hit in scan_tree(root))
        table = {"detect.py": {"exp"}}
        assert scan_tree(root, table) == []

    def test_an_exemption_does_not_leak_to_other_files(self, tmp_path):
        root = copy_package(tmp_path)
        inject_into(os.path.join(root, "episodes.py"), "INJECTED = __import__('math').exp(1.0)\n")
        assert scan_tree(root, {"detect.py": {"exp"}}) != []

    def test_the_shipped_table_is_empty_and_documented(self):
        # Nothing today needs an exception. If one is added, it must arrive with a reason in this
        # table -- that is the point of having it rather than editing the patterns.
        assert EXEMPTIONS == {}


class TestDetectionPathHasNoClock:
    def test_no_module_on_the_path_imports_a_clock_source(self):
        for path in _python_sources(SRC):
            with io.open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    assert name.split(".")[0] not in ("time", "datetime"), (path, name)
