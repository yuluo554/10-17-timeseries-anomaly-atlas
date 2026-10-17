"""Integer time base (M1, K5): civil<->epoch milliseconds in pure integer arithmetic.

Planned API:
  parse_iso_to_epoch_ms(text, default_tz_offset_min) -> int   # UTC epoch ms
  epoch_ms_to_iso(ms) -> str                                  # 'YYYY-MM-DDTHH:MM:SS.mmmZ'
  civil_from_days(days) / days_from_civil(y, m, d)            # Hinnant integer algorithms

This module is the single authority for time conversion: the browser mirror must
reproduce the same integer algorithm, so no local-timezone database may take part.
Tests cross-check every fixture row against `datetime` (the handwritten algorithm
has to be falsified once by the stdlib before it is trusted).
"""
