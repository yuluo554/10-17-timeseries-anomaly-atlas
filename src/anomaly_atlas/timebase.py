"""Integer time base (M1, K5): civil<->epoch milliseconds in pure integer arithmetic.

API:
  parse_iso_to_epoch_ms(text, default_tz_offset_min=0) -> int   # UTC epoch ms
  parse_timestamp(text, default_tz_offset_min=0) -> ParsedTimestamp
  epoch_ms_to_iso(ms) -> str                                    # 'YYYY-MM-DDTHH:MM:SS.mmmZ'
  epoch_ms_to_civil(ms) -> (y, m, d, hh, mm, ss, milli)
  days_from_civil(y, m, d) / civil_from_days(days)              # Hinnant integer algorithms

This module is the single authority for time conversion: the browser mirror must
reproduce the same integer algorithm, so no local-timezone database may take part and
`datetime.fromisoformat` is deliberately *not* the only path (see plan/06 D11).

Grammar accepted for a timestamp (the `[ T]` separator is required):
  YYYY-MM-DD[T ]HH:MM[:SS[.f{1,9}]][Z | +HH:MM | +HHMM | +HH]

Semantics:
  * a trailing `Z` or numeric offset is an *explicit* UTC offset in minutes east of UTC;
  * no trailing offset means the value is local to the declared zone and is interpreted
    with `default_tz_offset_min` (0 = UTC); the offset used is reported back so callers
    can record it (profile.json, K5/D11);
  * conversion is integer arithmetic end to end -- sub-second digits are truncated
    (not rounded) toward the millisecond, so no float ever touches a timestamp;
  * the civil date must exist (2024-02-30 is rejected, not silently normalised).

Tests cross-check every fixture row against `datetime`: the handwritten algorithm has to
be falsified once by the stdlib before it is trusted.
"""

import re
from collections import namedtuple

MS_PER_SECOND = 1000
MS_PER_MINUTE = 60 * MS_PER_SECOND
MS_PER_HOUR = 60 * MS_PER_MINUTE
MS_PER_DAY = 24 * MS_PER_HOUR

# Hinnant's civil-calendar constants: days between 0000-03-01 and 1970-01-01.
_EPOCH_SHIFT_DAYS = 719468
_DAYS_PER_ERA = 146097

# Legal ISO-8601-shaped forms. Seconds (and the fraction) are optional; a fraction is
# only legal when seconds are present, matching the grammar documented above.
_ISO_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"[T ](?P<h>\d{2}):(?P<mi>\d{2})"
    r"(?::(?P<s>\d{2})(?:\.(?P<f>\d{1,9}))?)?"
    r"(?P<tz>Z|z|[+-]\d{2}(?::?\d{2})?)?$"
)

_TZ_RE = re.compile(r"^(?P<sign>[+-])(?P<h>\d{2})(?::?(?P<m>\d{2}))?$")


class TimeParseError(ValueError):
    """Raised when a timestamp string is not a legal value of the grammar above.

    Subclasses ValueError so callers that only care about "not a timestamp" do not have
    to know this module (csvio maps it to E_TS_UNPARSEABLE with the source row number).
    """


# One parsed timestamp: UTC epoch ms plus the offset that was actually applied.
# `offset_explicit` distinguishes "the text carried Z/+HH:MM" from "the declared default
# was applied", which is what the profile needs in order to record offset switches
# (K5/D11) instead of inventing them.
ParsedTimestamp = namedtuple("ParsedTimestamp", "epoch_ms offset_min offset_explicit")


def days_from_civil(y, m, d):
    """Days since 1970-01-01 for a proleptic-Gregorian civil date (Hinnant).

    Truncating integer division is emulated explicitly (`y - 399`) so the expression
    reads the same in every language that mirrors it; Python's `//` already floors.
    """
    y = int(y)
    m = int(m)
    d = int(d)
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400  # [0, 399]
    doy = (153 * (m - 3 if m > 2 else m + 9) + 2) // 5 + d - 1  # [0, 365]
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy  # [0, 146096]
    return era * _DAYS_PER_ERA + doe - _EPOCH_SHIFT_DAYS


def civil_from_days(days):
    """Inverse of `days_from_civil`: days since epoch -> (year, month, day)."""
    z = int(days) + _EPOCH_SHIFT_DAYS
    era = (z if z >= 0 else z - 146096) // _DAYS_PER_ERA
    doe = z - era * _DAYS_PER_ERA  # [0, 146096]
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365  # [0, 399]
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)  # [0, 365]
    mp = (5 * doy + 2) // 153  # [0, 11]
    d = doy - (153 * mp + 2) // 5 + 1  # [1, 31]
    m = mp + (3 if mp < 10 else -9)  # [1, 12]
    return (y + (1 if m <= 2 else 0), m, d)


def is_valid_civil_date(y, m, d):
    """True iff (y, m, d) is a date that exists in the proleptic Gregorian calendar."""
    if not (1 <= m <= 12):
        return False
    if not (1 <= d <= 31):
        return False
    return civil_from_days(days_from_civil(y, m, d)) == (y, m, d)


def epoch_ms_to_civil(ms):
    """Split UTC epoch milliseconds into (y, m, d, hh, mm, ss, milli).

    `divmod` floors, so pre-epoch instants (negative ms) decompose correctly rather
    than truncating toward zero.
    """
    days, rest = divmod(int(ms), MS_PER_DAY)
    y, m, d = civil_from_days(days)
    hh, rest = divmod(rest, MS_PER_HOUR)
    mm, rest = divmod(rest, MS_PER_MINUTE)
    ss, milli = divmod(rest, MS_PER_SECOND)
    return (y, m, d, hh, mm, ss, milli)


def epoch_ms_to_iso(ms):
    """Render UTC epoch ms as the fixed-width form 'YYYY-MM-DDTHH:MM:SS.mmmZ'.

    Derived from integers only -- no local timezone, no DST, no float formatting.
    """
    y, m, d, hh, mm, ss, milli = epoch_ms_to_civil(ms)
    if y < 0:
        raise ValueError("year out of the 4-digit ISO range: %d" % y)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (y, m, d, hh, mm, ss, milli)


def _parse_offset(text):
    """Parse 'Z'/'z'/'-|+HH[:MM]' into (offset_min, explicit)."""
    if text in ("Z", "z"):
        return (0, True)
    match = _TZ_RE.match(text)
    if not match:
        raise TimeParseError("malformed UTC offset: %r" % (text,))
    hours = int(match.group("h"))
    minutes = int(match.group("m")) if match.group("m") is not None else 0
    if hours > 23 or minutes > 59:
        raise TimeParseError("UTC offset out of range: %r" % (text,))
    total = hours * 60 + minutes
    if match.group("sign") == "-":
        total = -total
    return (total, True)


def parse_timestamp(text, default_tz_offset_min=0):
    """Parse one timestamp string into a `ParsedTimestamp` (UTC epoch ms + offset used).

    `default_tz_offset_min` is the declared zone offset in minutes east of UTC, applied
    only when the text carries no `Z`/`+HH:MM` of its own.
    """
    if not isinstance(text, str):
        raise TimeParseError("timestamp must be a string, got %r" % (type(text).__name__,))
    raw = text.strip()
    if not raw:
        raise TimeParseError("empty timestamp")
    match = _ISO_RE.match(raw)
    if not match:
        raise TimeParseError("not an ISO-8601 timestamp: %r" % (text,))

    y = int(match.group("y"))
    mo = int(match.group("mo"))
    d = int(match.group("d"))
    hh = int(match.group("h"))
    mi = int(match.group("mi"))
    ss = int(match.group("s")) if match.group("s") is not None else 0
    frac = match.group("f") or ""

    if not is_valid_civil_date(y, mo, d):
        raise TimeParseError("no such calendar date: %r" % (text,))
    if hh > 23:
        raise TimeParseError("hour out of range: %r" % (text,))
    if mi > 59:
        raise TimeParseError("minute out of range: %r" % (text,))
    if ss > 59:
        # Leap seconds are not representable in a fixed epoch-ms grid; rejecting them
        # keeps the basin of accepted inputs identical to what `datetime` can confirm.
        raise TimeParseError("second out of range: %r" % (text,))

    # Truncate toward the millisecond on the digit string: 9 digits of a fraction must
    # not round-trip through float.
    milli = int((frac + "000")[:3]) if frac else 0

    tz_text = match.group("tz")
    if tz_text is None:
        offset_min = int(default_tz_offset_min)
        explicit = False
    else:
        offset_min, explicit = _parse_offset(tz_text)

    local_ms = (
        days_from_civil(y, mo, d) * MS_PER_DAY
        + hh * MS_PER_HOUR
        + mi * MS_PER_MINUTE
        + ss * MS_PER_SECOND
        + milli
    )
    return ParsedTimestamp(local_ms - offset_min * MS_PER_MINUTE, offset_min, explicit)


def parse_iso_to_epoch_ms(text, default_tz_offset_min=0):
    """Parse a timestamp string to UTC integer epoch milliseconds (K5)."""
    return parse_timestamp(text, default_tz_offset_min).epoch_ms
