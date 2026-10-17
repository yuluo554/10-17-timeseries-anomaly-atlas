"""Fact ledger for the narrative number whitelist (M5) -> facts.json.

Planned API:
  build_facts(profile, run_spec, anomalies) -> dict   # every number carries a fact_id

The ledger is the only authoritative source of numbers for the report; the narrative may
not contain a number that is absent from it.
"""
