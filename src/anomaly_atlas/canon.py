"""Canonical JSON + sha256 (M2, K3): the only hash input form.

Planned API:
  quantize(x, decimals) -> int                        # half-even, integer arithmetic
  fixed_to_str(q, decimals) -> str                    # decimal text built from the integer
  canonical_json(obj) -> str                          # sort_keys, ensure_ascii=False, indent=2, LF
  sha256_hex(data: bytes) -> str
  build_anomaly_set(run_spec, series, episodes) -> (canonical_obj, digest)

The canonical form contains only strings/integers/bools/null -- no float literal ever
reaches the hash. Same rules serve the anomaly-set digest, the truth digest and the
in-browser recomputation digest.
"""
