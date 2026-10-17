"""Episode merging, severity ordering and id assignment (M2, K6/K7).

Planned API:
  merge_episodes(series, detections, max_gap_ms) -> list[Episode]
  order_episodes(episodes) -> list[Episode]           # severity key, integers/strings only
  assign_ids(episodes) -> list[Episode]               # '<series_id>-E<NNN>'

Severity key: peak_score_q desc -> duration_ms desc -> start_row asc -> detector lex.
Merging is time-domain (`max_gap_ms`), so a data gap never fuses two unrelated episodes.
"""
