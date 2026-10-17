"""CSV contract parsing + per-row validation (M1).

Planned API:
  load_series(path, spec) -> ParsedSeries            # rows: (row_no, epoch_ms, value|None)
  ERROR_CODES: dict[str, str]                        # single definition point (data/README 4.4)

Column contract: timestamp column + value column, optional series_id column; resolved
by an explicit synonym whitelist or by run-spec override -- ambiguity is an error, never
a guess. Missing values stay `None` (no zero-fill, no interpolation): missingness is
an input to profiling and to the rule detector, not something to silently repair.
Every error carries a source row number and all errors are reported at once (exit 2).
"""
