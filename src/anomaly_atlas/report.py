"""Report number whitelist gate (M5) + `check-report` orchestration.

Planned API:
  extract_numbers(text) -> list[(token, context)]
  check_report(text, facts) -> list[dict]             # unmatched tokens with context
  cmd_check_report(facts_path, text_path) -> int      # exit 1 on any miss, report not emitted

Also gates the model's forbidden zone by code: every episode reference in the narrative
must resolve to an episode_id present in anomalies.json (no invented episodes or rows).
"""
