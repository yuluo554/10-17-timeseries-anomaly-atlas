"""Single-file HTML rendering (M4) -- hand-written SVG, zero external resources.

Planned API:
  render_html(profile, run_spec, anomalies, series, mirror_js, facts, narrative) -> str
  assert_no_external_resources(html) -> None          # resident at the render exit, not test-only
  cmd_render(csv_path, out_path, spec_path, narrative_path) -> int

Components: main series + anomaly bands + peak markers + gap textures, episode cards
(zoom, threshold line, detector, score, source rows, episode_id), per-series small
multiples, anomaly density heat strip, sensitivity sliders (deterministic front-end
recomputation through the same JS kernel, slider value rendered as a run-spec snippet),
quality card, report section, VERIFIED/MISMATCH badge, print stylesheet (monochrome-safe).
"""
