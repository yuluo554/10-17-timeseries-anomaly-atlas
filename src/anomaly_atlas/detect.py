"""Four deterministic detectors (M2) + `detect` orchestration.

Planned API:
  rolling_mad_z(series, window, k, min_valid) -> list[(index, score)]
  rolling_iqr(series, window, iqr_mult, min_valid) -> list[(index, score)]
  stl_resid_z(series, period_points, inner, outer, window, k, min_valid) -> list[(index, score)]
  rules(series, spec) -> list[(index, score, rule_name)]
  cmd_detect(csv_path, spec_path, out_dir) -> int

Mirrorable arithmetic only (plan/02 3.2): + - * / floor ceil abs min max and comparisons,
powers expanded into multiplication, no transcendental function anywhere on the hash path.
A detector returns raw scores; it never writes an episode or reorders anything.
"""
