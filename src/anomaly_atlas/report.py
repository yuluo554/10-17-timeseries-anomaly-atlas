"""Report number whitelist gate (M5) + `check-report` orchestration.

API:
  extract_numbers(text) -> list[dict]                 # number tokens with context
  extract_episode_refs(text) -> list[dict]            # '<series>-E<NNN>' references
  extract_row_refs(text) -> list[dict]                # 'row N' / '行 N' / '第 N 行' references
  check_report(text, facts) -> list[dict]             # every unmatched reference, all of them
  audit(text, facts) -> dict                          # tokens + violations + counts
  render_violations(violations, stream) -> None       # human-readable, one line per miss
  load_facts(path) / validate_facts(document)         # shape checks -> usage error, never a pass
  cmd_check_report(facts_path, text_path) -> int      # 0 pass, 1 any miss, 2 unreadable input

The gate answers one question: *is every number in this narrative a citation of a number the kernel
already published?* A miss is a failure, the report is not generated, and every miss is listed --
reporting only the first one would let a fabricated number hide behind another one (plan/01 M5: the
model must not "polish" an anomaly set into something else).

What the narrative may and may not say, in code rather than in prose (M1.1/M5):

* An episode reference (`[A-Za-z0-9_]+-E\\d{3}`) must resolve to an `episode_id` in the archive, so an
  invented episode cannot be smuggled in by naming it.
* A row reference (`row N`, `行 N`, `第 N 行`) must resolve to a row number that occurs in the
  archive. Physical CSV lines -- which come from the *parser*, not the archive -- are exempt by
  being labelled as such (`CSV 行 N` / `文件行 N`), which is exactly the escape hatch the题目 allows.
* A percent token may cite either the percentage itself or the underlying ratio (`42.34%` matches a
  coverage fact of `0.423400`), because both are the same measurement written two ways.

Masking rather than subtracting: episode ids, ISO timestamps, row references and labelled physical
lines are cut out of the text *before* numbers are scanned, so the digits inside them are never
mistaken for report numbers. Masks keep the string length, so every token still carries the offset
and the surrounding text a reader needs to find it.
"""

import re
import string
import sys

from . import canon, facts as facts_module, layout

# One scale for every comparison: 6 decimals, matching `quant_decimals` (K3).
QUANT_DECIMALS = layout.QUANT_DECIMALS

# --- lexical forms ---------------------------------------------------------

# Arabic numbers: thousands separators, decimals, scientific form, optional percent sign. No sign is
# captured: a leading `-` is a separator in prose (`3-5 段`) far more often than it is a negative
# value, and no fact in the ledger is negative.
_NUMBER_RE = re.compile(
    r"(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?(?P<exp>[eE][-+]?\d+)?(?P<pct>%|％)?"
)

# ISO calendar timestamps. They are converted to epoch milliseconds and matched like any other
# number, so a narrative may cite *when* an episode happened straight off the page.
_ISO_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)

# A physical CSV line, named as such. Exempt from the gate: it cites the parser's row numbers, which
# the profile records, not the archive's.
_PHYSICAL_ROW_RE = re.compile(r"(?:文件行|CSV\s*行|CSV行)\s*\d+")

# A row reference into the archive.
_ROW_REF_RE = re.compile(r"(?:row|行)\s*(?P<n1>\d+)|第\s*(?P<n2>\d+)\s*行")

# An episode reference: '<series_id>-E<NNN>'.
_EPISODE_RE = re.compile(r"[A-Za-z0-9_]+-E\d{3}")

# Chinese numerals, only when a quantifier follows ("三处", "十五条", "两段"). Requiring the
# quantifier is what keeps ordinary words out of the ledger's jurisdiction: 统一 / 一般 / 十分 are
# not measurements, and a gate that flagged them would be switched off by its first user.
_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_BIG_UNITS = {"万": 10000, "亿": 100000000}
_CN_UNIT_RE = (
    "处|个|段|条|次|点|列|种|类|组|对|张|块|格|箱|倍|分钟|小时|毫秒|秒|天|月|年"
)
_CN_NUMBER_RE = re.compile(
    "(?P<cn>[零一二三四五六七八九十百千万两]+)(?P<unit>%s)" % _CN_UNIT_RE
)

# Boundary character sets for the number scan. ASCII-only on purpose: `\\w` in Python matches CJK
# ideographs, which would refuse to read the number in "共178段".
_ASCII_WORD = frozenset(string.ascii_letters + string.digits + "_")
_ASCII_WORD_LEFT = _ASCII_WORD | frozenset(".")

_CONTEXT_RADIUS = 14


# --- number-token helpers --------------------------------------------------


def _claim(spans, start, end):
    """Add a claimed span unless it overlaps one already claimed (earlier kinds win)."""
    for existing_start, existing_end in spans:
        if start < existing_end and existing_start < end:
            return False
    spans.append((start, end))
    return True


def _masked(text, spans):
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            chars[index] = " "
    return "".join(chars)


def _context(text, start, end):
    left = text[max(0, start - _CONTEXT_RADIUS):start]
    right = text[end:end + _CONTEXT_RADIUS]
    prefix = "…" if start > _CONTEXT_RADIUS else ""
    suffix = "…" if end + _CONTEXT_RADIUS < len(text) else ""
    return "%s%s%s%s%s" % (prefix, left, text[start:end], right, suffix)


def _scale_digits(digits, frac_len, exponent, decimals=QUANT_DECIMALS):
    """`digits` (decimal digits, no point) with `frac_len` of them after the point, times 10^exp.

    Integer arithmetic end to end, half-to-even on the way down, exactly like `canon.quantize` --
    the gate must not disagree with the kernel about what a written number means.
    """
    number = int(digits) if digits else 0
    shift = decimals - frac_len + exponent
    if shift >= 0:
        scale = 1
        for _step in range(shift):
            scale = scale * 10
        return number * scale
    divisor = 1
    for _step in range(-shift):
        divisor = divisor * 10
    quotient, remainder = divmod(number, divisor)
    if remainder * 2 > divisor:
        quotient += 1
    elif remainder * 2 == divisor:
        quotient += quotient % 2
    return quotient


def _power_of_ten(decimals):
    scale = 1
    for _step in range(int(decimals)):
        scale = scale * 10
    return scale


def chinese_to_int(text):
    """`三`/`十五`/`二十`/`一百零五`/`三万` -> int. Returns None for anything it cannot read."""
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_SMALL_UNITS:
            unit = _CN_SMALL_UNITS[char]
            section += (number if number else 1) * unit
            number = 0
        elif char in _CN_BIG_UNITS:
            section = (section + number) * _CN_BIG_UNITS[char]
            total += section
            section = 0
            number = 0
        else:
            return None
    return total + section + number


def _number_token(text, start, end, form, scaled, extra=None):
    token = {
        "kind": "number",
        "form": form,
        "token": text[start:end],
        "start": start,
        "end": end,
        "context": _context(text, start, end),
        "value_q": scaled,
    }
    if extra:
        token.update(extra)
    return token


def extract_numbers(text):
    """Every number in `text` that is a claim about the archive, with its context.

    Episode ids, ISO timestamps, row references and labelled physical lines are masked first (those
    get their own gates), so a digit sequence inside one of them is never reported as a report
    number. Returns tokens in text order.
    """
    spans = []
    claimed = []
    for match in _ISO_RE.finditer(text):
        if _claim(spans, match.start(), match.end()):
            claimed.append(match)
    for pattern in (_PHYSICAL_ROW_RE, _EPISODE_RE, _ROW_REF_RE):
        for match in pattern.finditer(text):
            _claim(spans, match.start(), match.end())
    masked = _masked(text, spans)

    tokens = []
    for match in _NUMBER_RE.finditer(masked):
        start, end = match.span()
        if start > 0 and masked[start - 1] in _ASCII_WORD_LEFT:
            continue
        if end < len(masked) and masked[end] in _ASCII_WORD:
            continue
        form = "percent" if match.group("pct") else "number"
        digits = match.group("int").replace(",", "") + (
            match.group("frac")[1:] if match.group("frac") else ""
        )
        frac_len = len(match.group("frac")) - 1 if match.group("frac") else 0
        exponent = int(match.group("exp")[1:]) if match.group("exp") else 0
        scaled = _scale_digits(digits, frac_len, exponent)
        tokens.append(_number_token(text, start, end, form, scaled))

    for match in _CN_NUMBER_RE.finditer(masked):
        start, end = match.span()
        if start > 0 and masked[start - 1] in _ASCII_WORD_LEFT:
            continue
        value = chinese_to_int(match.group("cn"))
        if value is None:
            continue
        scaled = value * _power_of_ten(QUANT_DECIMALS)
        tokens.append(
            _number_token(
                text,
                start,
                end,
                "chinese",
                scaled,
                {"chinese_value": value, "quantifier": match.group("unit")},
            )
        )

    for match in claimed:
        start, end = match.start(), match.end()
        token_text = text[start:end]
        try:
            epoch_ms = _iso_to_ms(token_text)
        except ValueError:
            tokens.append(
                _number_token(
                    text,
                    start,
                    end,
                    "iso",
                    None,
                    {"unreadable": "不是可解析的日历时间戳"},
                )
            )
            continue
        scaled = epoch_ms * _power_of_ten(QUANT_DECIMALS)
        tokens.append(_number_token(text, start, end, "iso", scaled, {"epoch_ms": epoch_ms}))

    tokens.sort(key=lambda token: (token["start"], token["end"]))
    return tokens


def _iso_to_ms(token_text):
    from . import timebase

    return timebase.parse_iso_to_epoch_ms(token_text)


def extract_episode_refs(text):
    """Every `<series>-E<NNN>` reference with its offset and context."""
    return [
        {
            "kind": "episode",
            "token": match.group(0),
            "episode_id": match.group(0),
            "start": match.start(),
            "end": match.end(),
            "context": _context(text, match.start(), match.end()),
        }
        for match in _EPISODE_RE.finditer(text)
    ]


def extract_row_refs(text):
    """Every `row N` / `行 N` / `第 N 行` reference, with the number it names.

    Labelled physical lines (`CSV 行 N`) are deliberately absent: they name parser rows, and the
   题目 exempts them from the archive's row set.
    """
    spans = []
    for match in _PHYSICAL_ROW_RE.finditer(text):
        _claim(spans, match.start(), match.end())
    refs = []
    for match in _ROW_REF_RE.finditer(text):
        if not _claim(spans, match.start(), match.end()):
            continue
        raw = match.group("n1") or match.group("n2")
        refs.append(
            {
                "kind": "row",
                "token": match.group(0),
                "row_no": int(raw),
                "start": match.start(),
                "end": match.end(),
                "context": _context(text, match.start(), match.end()),
            }
        )
    return refs


# --- the gate --------------------------------------------------------------


def check_report(text, facts_document):
    """Every unmatched reference in `text`, in text order; an empty list means the report passes.

    Each violation is a dict with `kind` (`number` / `episode` / `row`), the `token`, the surrounding
    `context`, and -- for numbers -- the closest fact the ledger does have, so the author can see
    what they probably meant to cite.
    """
    index = facts_module.numeric_index(facts_document)
    table = facts_document.get("facts", {})
    decimals = int(facts_document.get("quant_decimals", QUANT_DECIMALS))
    catalog = facts_document.get("catalog") or {}
    known_episodes = set(catalog.get("episode_ids", ()))
    known_rows = set(catalog.get("archive_rows", ()))

    violations = []
    for token in extract_numbers(text):
        if _number_hit(token, index):
            continue
        violation = dict(token)
        violation["closest"] = _closest_fact(token.get("value_q"), index, table, decimals)
        violations.append(violation)
    for ref in extract_episode_refs(text):
        if ref["episode_id"] in known_episodes:
            continue
        violation = dict(ref)
        violation["closest"] = None
        violations.append(violation)
    for ref in extract_row_refs(text):
        if ref["row_no"] in known_rows:
            continue
        violation = dict(ref)
        violation["closest"] = None
        violations.append(violation)
    violations.sort(key=lambda violation: (violation["start"], violation["end"]))
    return violations


def _number_hit(token, index):
    """Does any fact carry this token's value? A percent may cite the ratio or the percentage."""
    value_q = token.get("value_q")
    if value_q is None:
        return False
    candidates = [value_q]
    if token["form"] == "percent" and value_q % 100 == 0:
        candidates.append(value_q // 100)
    for candidate in candidates:
        if candidate in index:
            return True
    return False


def _closest_fact(value_q, index, table, decimals):
    """The ledger's nearest number to a miss: `{'fact_id', 'value', 'delta_q'}` or None."""
    if value_q is None or not index:
        return None
    best = None
    for scaled in sorted(index):
        delta = scaled - value_q
        if delta < 0:
            delta = -delta
        if best is None or delta < best[0]:
            best = (delta, scaled)
    if best is None:
        return None
    fact_id = index[best[1]][0]
    return {
        "fact_id": fact_id,
        "value": table[fact_id]["value"],
        "delta_q": best[0],
    }


def audit(text, facts_document):
    """Tokens plus violations plus counts: one scan, used by the CLI and by the render gate."""
    return {
        "numbers": extract_numbers(text),
        "episodes": extract_episode_refs(text),
        "rows": extract_row_refs(text),
        "violations": check_report(text, facts_document),
    }


def gate_summary(result):
    """`'12 number(s), 3 episode reference(s), 2 row reference(s)'` for OK lines and banners."""
    return "%d number(s), %d episode reference(s), %d row reference(s)" % (
        len(result["numbers"]),
        len(result["episodes"]),
        len(result["rows"]),
    )


class NarrativeRejected(ValueError):
    """A narrative failed the whitelist. Carries the violations so the caller can print them all."""

    def __init__(self, violations):
        ValueError.__init__(
            self,
            "narrative failed the facts.json whitelist: %d unmatched reference(s)" % len(violations),
        )
        self.violations = violations


def render_violations(violations, stream):
    """One line per miss, all of them, with the closest fact where there is one."""
    for index, violation in enumerate(violations, 1):
        closest = violation.get("closest")
        if closest is None:
            nearest = "closest=none"
        else:
            nearest = "closest=%s(%s)" % (closest["fact_id"], closest["value"])
        print(
            "MISS[%d] kind=%s token=%r offset=%d %s context=%s"
            % (
                index,
                violation["kind"],
                violation["token"],
                violation["start"],
                nearest,
                violation["context"],
            ),
            file=stream,
        )
    return len(violations)


# --- facts.json loading ----------------------------------------------------


def validate_facts(document):
    """Raise ValueError unless `document` is a facts.json this gate can work with."""
    if not isinstance(document, dict):
        raise ValueError("facts.json must be a JSON object")
    for key in ("schema_version", "quant_decimals", "facts", "catalog"):
        if key not in document:
            raise ValueError("facts.json is missing key %r" % (key,))
    if not isinstance(document["facts"], dict):
        raise ValueError("facts.json 'facts' must be an object")
    if not isinstance(document["catalog"], dict):
        raise ValueError("facts.json 'catalog' must be an object")
    return document


def load_facts(path):
    """Read and validate facts.json. Raises ValueError/OSError/UnicodeDecodeError on bad input."""
    import json
    import os

    if not os.path.isfile(path):
        raise OSError("facts.json not found: %s" % (path,))
    with open(path, "rb") as handle:
        payload = handle.read()
    try:
        document = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("facts.json is not readable JSON: %s" % (exc,))
    return validate_facts(document)


def cmd_check_report(facts_path, text_path):
    """CLI body for `check-report`: 0 pass, 1 any miss (listing all of them), 2 unreadable input."""
    from .cli import EXIT_FAIL, EXIT_OK, EXIT_USAGE

    try:
        document = load_facts(facts_path)
    except (OSError, ValueError) as exc:
        print("error: %s" % (exc,), file=sys.stderr)
        return EXIT_USAGE
    try:
        with open(text_path, "rb") as handle:
            text = handle.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print("error: cannot read narrative %s: %s" % (text_path, exc), file=sys.stderr)
        return EXIT_USAGE

    result = audit(text, document)
    violations = result["violations"]
    n_facts = len(document["facts"])
    if violations:
        print(
            "check-report: %d unmatched reference(s) of %s against %d fact(s); report NOT generated"
            % (len(violations), gate_summary(result), n_facts)
        )
        render_violations(violations, sys.stdout)
        return EXIT_FAIL
    print(
        "check-report: OK -- %s all matched against %d fact(s) (%d episode id(s) resolvable)"
        % (
            gate_summary(result),
            n_facts,
            len(document["catalog"].get("episode_ids", ())),
        )
    )
    return EXIT_OK
