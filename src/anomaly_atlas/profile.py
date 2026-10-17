"""Data profile + quality card (M1) -> profile.json.

Planned API:
  build_profile(parsed, spec) -> dict                 # keys sorted on dump (K2)
  cmd_profile(csv_path, out_path) -> int

Contents: parse summary, timezone/DST record, cadence (interval distribution + dominant
interval), duplicate timestamps, gap intervals, zero-value runs, missing-value runs,
non-monotonic points. Pure rule computation -- no model call, no clock, no randomness.
"""
