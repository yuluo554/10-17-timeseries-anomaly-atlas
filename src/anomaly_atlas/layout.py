"""Deterministic geometry and binning for the report (M4).

Planned API:
  main_series_layout(profile, episodes, width, height) -> dict
  episode_zoom_layout(episode, series, pad_rows, width, height) -> dict
  density_bins(profile, episodes, heat_bin_ms) -> list[dict]
  small_multiples_layout(profile) -> dict

Integer pixel coordinates only; row index -> pixel via a fixed linear map; bin edges by a
fixed rule. No randomness, no clock, no floating-point layout jitter: the same input must
produce the same visible geometry byte for byte.
"""
