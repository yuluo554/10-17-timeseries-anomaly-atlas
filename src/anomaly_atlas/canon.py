"""Canonical JSON + sha256 + fixed-point helpers (K2/K3): the only hash input form.

API:
  quantize(x, decimals=6) -> int            # half-to-even, integer arithmetic only
  fixed_to_str(q, decimals=6) -> str        # decimal display string built from an int
  canonical_json_text(obj) -> str           # sort_keys=True, ensure_ascii=False, indent=2, LF
  canonical_json_bytes(obj) -> bytes        # the only legal sha256 input form
  sha256_hex(data) -> str                   # lowercase hex
  assert_hashable(obj) -> None              # rejects float anywhere in the tree

The canonical form contains only strings/integers/bools/null -- no float literal ever
reaches the hash. The same rules serve the anomaly-set digest, the truth digest and the
in-browser recomputation digest; those must stay byte-identical, which is why they share
this one implementation instead of each re-deriving the rule set.

M1 scope note: this module lands in M1 because `profile.json` (K2 serialisation) and the
frozen truth hash (`data/truth/hash.txt`, K3) both need exactly these primitives, and
"one definition point" beats three copies of the same rules. `build_anomaly_set` (the M2
anomaly-set fingerprint) is deliberately not here yet.
"""

import hashlib
import json
import math

# Hash input is the byte sequence of the canonical JSON text, and that text may contain
# only strings, integers, booleans, null and arrays/objects of those -- never a float
# literal (a float would re-introduce "shortest round-trip representation" divergence
# between CPython and JavaScript).
_ALLOWED_SCALARS = (str, int, bool, type(None))


def assert_hashable(obj, path="$"):
    """Raise TypeError if `obj` contains a float (or any other non-canonical type)."""
    if isinstance(obj, _ALLOWED_SCALARS):
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON keys must be strings: %r at %s" % (key, path))
            assert_hashable(value, "%s.%s" % (path, key))
        return
    if isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            assert_hashable(value, "%s[%d]" % (path, index))
        return
    raise TypeError(
        "value of type %s is not canonical JSON (floats must be fixed-pointed first) at %s"
        % (type(obj).__name__, path)
    )


def quantize(x, decimals=6):
    """Half-to-even fixed-point quantisation to an integer (data/README 4.3).

    Written in integer arithmetic after the one float multiplication, so no
    language-provided float formatting takes part: `f"{x:.6f}"` / `toFixed` boundary
    behaviour is not reproducible across CPython and V8 and is banned for that reason.
    """
    scale = 10 ** decimals
    scaled = float(x) * scale
    floored = math.floor(scaled)
    frac = scaled - floored
    if frac > 0.5:
        return floored + 1
    if frac < 0.5:
        return floored
    return floored + 1 if floored % 2 else floored


def fixed_to_str(q, decimals=6):
    """Build the decimal display string from the fixed-point integer only."""
    q = int(q)
    decimals = int(decimals)
    sign = "-" if q < 0 else ""
    magnitude = abs(q)
    if decimals == 0:
        return sign + str(magnitude)
    scale = 10 ** decimals
    return "%s%d.%s" % (sign, magnitude // scale, str(magnitude % scale).zfill(decimals))


def canonical_json_text(obj):
    """Canonical JSON text: sorted keys, no ASCII escaping, 2-space indent, trailing LF."""
    assert_hashable(obj)
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def canonical_json_bytes(obj):
    """The exact byte sequence sha256 is taken over: UTF-8, no BOM, LF."""
    return canonical_json_text(obj).encode("utf-8")


def sha256_hex(data):
    """Lowercase hex sha256 of a byte sequence (the single hash helper, K3)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
