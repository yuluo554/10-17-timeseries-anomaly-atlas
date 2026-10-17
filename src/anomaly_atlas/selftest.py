"""Built-in falsifiable benchmark suite (M2).

Planned API:
  cmd_selftest() -> int                               # 0 all green, 1 any defect found
  CHECKS: list[dict]                                  # name / callable / falsifiable probe

Checks: fixture files present / profile double-run byte-identical / truth reconciliation
(every injected segment, not a sampled rate) / parameter change must change the digest /
mirror parity through Node / falsifiable probes (tamper an inlined point -> must go red and
localize; inject a defect -> the same check must report a difference).
A check whose probe cannot be falsified counts as a failed check, not as a pass.
"""
