"""Shared test fixtures: repository paths, frozen-data paths, and a CSV writer.

The test suite is loadable two ways on purpose: with `PYTHONPATH=src` (source mode) and
after `pip install -e .` (CI). The path bootstrap below is what makes the first one work
without a conftest-supplied sys.path; in the installed case it is a no-op.
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

DATA_SYNTHETIC = os.path.join(REPO_ROOT, "data", "synthetic")
DATA_TRUTH = os.path.join(REPO_ROOT, "data", "truth")
DATA_SAMPLES = os.path.join(REPO_ROOT, "data", "samples")
TOOLS = os.path.join(REPO_ROOT, "tools")

SERIES_CSV = os.path.join(DATA_SYNTHETIC, "series.csv")
MANIFEST_JSON = os.path.join(DATA_SYNTHETIC, "manifest.json")
TRUTH_JSON = os.path.join(DATA_TRUTH, "truth.json")
TRUTH_HASH = os.path.join(DATA_TRUTH, "hash.txt")
MINIMAL_CSV = os.path.join(DATA_SAMPLES, "minimal.csv")


def repo_path(*parts):
    return os.path.join(REPO_ROOT, *parts)


@pytest.fixture
def write_text_file(tmp_path):
    """Write exact bytes (LF preserved, no BOM) and return the path as a string."""

    def _write(text, name="input.csv"):
        path = tmp_path / name
        path.write_bytes(text.encode("utf-8"))
        return str(path)

    return _write


@pytest.fixture
def write_bytes_file(tmp_path):
    def _write(payload, name="input.csv"):
        path = tmp_path / name
        path.write_bytes(payload)
        return str(path)

    return _write


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def read_text(path):
    return read_bytes(path).decode("utf-8")


def iter_floats(obj, path="$"):
    """Yield the JSON path of every float in a nested structure (K3 forbids all of them)."""
    if isinstance(obj, float):
        yield path
    elif isinstance(obj, dict):
        for key, value in obj.items():
            for hit in iter_floats(value, "%s.%s" % (path, key)):
                yield hit
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            for hit in iter_floats(value, "%s[%d]" % (path, index)):
                yield hit
