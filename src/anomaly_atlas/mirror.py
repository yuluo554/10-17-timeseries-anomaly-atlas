"""Browser recomputation support (M3): mirror loading, fingerprint export, `verify` wiring.

Planned API:
  load_mirror_js() -> str                             # src/anomaly_atlas/mirror/zaa_mirror.js
  build_fingerprint_block(run_spec, canonical, digest) -> dict
  run_node_mirror(html_path, node_exe, tamper_index=None) -> (digest, first_diff)
  cmd_verify(html_path, node_exe, tamper_index) -> int   # exit 4 when Node is missing

`mirror/zaa_mirror.js` is a hand-written JS re-implementation of detect/episodes/canon
(plus a hand-written SHA-256): it mirrors the Python statement order on purpose, because
the whole moat is that both sides re-derive the same digest. Node is the automated
channel; the browser badge is the human channel. A missing Node exits 4 -- never a
silent skip that a green run could hide behind.
"""
