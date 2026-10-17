"""Single-file HTML: the M3 embedding contract and the minimal carrier page.

API:
  build_payload(parsed, run_document, anomaly_set) -> dict
  build_carrier_html(parsed, run_document, anomaly_set) -> str
  assert_no_external_resources(html_text) -> None      # resident at the exit, not test-only
  write_carrier(csv_path, out_path, spec=None) -> None

M3 lands the *embedding contract* and a **minimal carrier page**: the smallest artifact that can
carry the inlined data, the run-spec, the build-time canonical JSON + digest and the hand-written
mirror, and that recomputes the digest in the browser. Its whole job is to make the recomputation
gate machine-runnable (`tools/mirror_parity.py`, `verify`). What M3 deliberately does not build is
the annotated view -- main series, anomaly bands, gap textures, episode cards, small multiples,
density strip, sensitivity sliders, print stylesheet -- which is M4, and which reuses this same
contract through `render_html` in this module.

Contract (plan/03 M3), one `<script>` block per concern:
  * `zaa-payload`   (application/json) -- the *input blob*: the effective run document, the raw
    samples per series, the build-time detector points, and the build-time canonical anomaly JSON
    plus its digest;
  * `zaa-mirror`    (text/javascript)  -- the hand-written mirror source, inlined verbatim;
  * `zaa-boot`      (text/javascript)  -- recompute, compare, render the badge.

Payload discipline: an inlined sample is the decimal *text* the kernel parsed, never a float
literal, so the whole payload is still "integers, strings, null and their containers" and
`canon.assert_hashable` can vet it (K3). The mirror turns that text into the nearest double; both
platforms round correctly, so both work on the same bits.

Zero external resources (K12): no CDN, no linked stylesheet, no external font, no image source --
and, in the boot script, no network API at all. `assert_no_external_resources` runs on every build
rather than once in a test.
"""

import os
import re
from string import Template

from . import canon, csvio, detect
from . import mirror as mirror_module

CARRIER_TITLE = "anomaly-atlas 复算载体页（M3 最小载体）"

# The boot block's element id. Single definition point next to the block it names.
SCRIPT_ID_BOOT = "zaa-boot"

# The boot script, with the payload block's id resolved *here* rather than left as an outer
# `string.Template` slot: a substituted value is not re-scanned for `$`, so a `$payload_id` written
# inside this literal would reach the artifact verbatim and the page would look up a null element.
# (That is not hypothetical -- it is how this shipped the first time, and only the browser channel
# could see it: the Node harness drives the mirror directly and never runs the boot script.)
_BOOT_JS_TEMPLATE = """(function () {
  /* Recompute through the inlined mirror and show the verdict. Nothing here reaches the network:
     every byte compared is already in this file. */
  var payload = JSON.parse(document.getElementById("%s").textContent);
  var expected = {
    canonical: payload.anomaly_set_canonical,
    sha256: payload.anomaly_set_sha256,
    points: payload.detections
  };
  var report = ZAA.verdict(ZAA.recompute(payload), expected, null);
  document.getElementById("build-digest").textContent = report.expected_digest;
  document.getElementById("recompute-digest").textContent = report.digest;
  document.getElementById("verdict-label").textContent = report.verified ? "VERIFIED" : "MISMATCH";
  document.getElementById("verdict").className = "card " + (report.verified ? "verified" : "mismatch");
  var first = report.first_point_diff;
  var text = "无（规范 JSON 逐字节一致，检测点集合逐一相同）";
  if (first !== null) {
    if (first.kind === "point") {
      text = "点 " + first.series_id + " / " + first.detector + " / #" + first.index +
        "：期望 " + JSON.stringify(first.expected) + "，实算 " + JSON.stringify(first.actual);
    } else if (first.kind === "count") {
      text = "点集长度 " + first.series_id + " / " + first.detector + "：期望 " + first.expected_n +
        " 个，实算 " + first.actual_n + " 个";
    } else {
      text = JSON.stringify(first);
    }
  } else if (!report.canonical_equal) {
    text = "规范 JSON 自第 " + report.first_byte_diff + " 字节起不同";
  }
  document.getElementById("first-diff").textContent = text;
})();
"""

_BOOT_JS = _BOOT_JS_TEMPLATE % mirror_module.SCRIPT_ID_PAYLOAD

_CARRIER_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>$title</title>
<style>
:root { color-scheme: light dark; }
body { margin: 0 auto; padding: 1.5rem; max-width: 60rem; line-height: 1.7;
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; }
h1 { font-size: 1.35rem; margin: 0 0 0.25rem; }
h2 { font-size: 1rem; margin: 1.25rem 0 0.5rem; }
.lead { margin: 0 0 1rem; color: #555; }
.card { border: 1px solid #bbb; border-radius: 6px; padding: 0.9rem 1.1rem; margin: 0 0 1rem; }
.card.verified { border-color: #17803d; background: rgba(23, 128, 61, 0.08); }
.card.mismatch { border-color: #b3261e; background: rgba(179, 38, 30, 0.08); }
#verdict-label { font-size: 1.4rem; font-weight: 700; letter-spacing: 0.08em; margin: 0 0 0.5rem; }
.card.verified #verdict-label { color: #17803d; }
.card.mismatch #verdict-label { color: #b3261e; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.15rem 1rem; margin: 0; }
dt { font-weight: 600; }
dd { margin: 0; font-family: ui-monospace, Consolas, monospace; word-break: break-all; }
ul { margin: 0.25rem 0 0; padding-left: 1.2rem; }
code { font-family: ui-monospace, Consolas, monospace; }
.meta { color: #555; margin: 0.75rem 0 0; }
</style>
</head>
<body>
<header>
  <h1>$title</h1>
  <p class="lead">本页刻意保持最小：它唯一要做的事，是加载时当场重算出构建时的 sha256 并给出 VERIFIED /
  MISMATCH。完整的标注图（异常带、Episode 卡片、small multiples、密度热条、打印样式）见 M4，复用同一嵌入契约。</p>
</header>
<section id="verdict" class="card">
  <p id="verdict-label">复算中…</p>
  <dl>
    <dt>构建指纹</dt><dd id="build-digest">–</dd>
    <dt>复算指纹</dt><dd id="recompute-digest">–</dd>
    <dt>首个差异点</dt><dd id="first-diff">–</dd>
  </dl>
</section>
<section class="card">
  <h2>嵌入契约（M3 定义，M4 复用）</h2>
  <ul>
    <li>原始数据：按 series 的行数组 <code>[epoch_ms, 数值文本|null, 源行号]</code>；镜像复用其中的整数毫秒，
    不重做时间解析，数值文本按"最近双精度"解析（不为哈希引入浮点字面量）。</li>
    <li><code>run.json</code>：解析后的生效参数（含 <code>period_points</code>）；镜像消费生效值，
    <strong>不重跑周期估计</strong>。</li>
    <li>构建时规范 JSON（异常集）与构建时 sha256：镜像逐字节比较的对象。</li>
    <li>镜像源码：本页内联的手写 JS 镜像，与 Python 内核同一操作序列。</li>
  </ul>
  <p class="meta">契约版本 <code>$contract_version</code>；镜像版本 <code>$mirror_version</code>；
  源文件 <code>$source_file</code>；内联样本 <code>$n_inline</code> 个；异常段 <code>$n_episodes</code> 段。</p>
</section>
<script id="$payload_id" type="application/json">$payload_json</script>
<script id="$mirror_id" type="text/javascript">$mirror_source</script>
<script id="$boot_id" type="text/javascript">$boot_js</script>
<noscript>本页需要 JavaScript 才能完成复算（不联网，全部在本文件内完成）。</noscript>
</body>
</html>
"""
)


def build_payload(parsed, run_document, anomaly_set, detections=None):
    """Assemble the inlined input blob for one run (plan/03 M3).

    The detector points travel with the archive because the badge and the tamper probe compare
    *points*, not just digests. Passing in the detections `detect_all_detailed` handed back is the
    normal path: the payload's point set is then the one the archive was assembled from, so the two
    cannot drift. When they are omitted they are re-derived from the *dumped* run-spec, which is
    the same reading a recomputation has (run.json + the CSV).
    """
    decimals = run_document["quant_decimals"]
    if detections is None:
        resolved = detect.resolve_spec(run_document["params"])
        detections = detect.run_detectors(parsed, resolved, resolved["period_points"])

    series_blocks = []
    for series_id in sorted(parsed.rows_by_series):
        rows = []
        for row_no, epoch_ms, value in parsed.rows_by_series[series_id]:
            rows.append([epoch_ms, None if value is None else repr(value), row_no])
        series_blocks.append({"series_id": series_id, "rows": rows})

    point_blocks = []
    for series_id in sorted(parsed.rows_by_series):
        for detector in sorted(key[1] for key in detections if key[0] == series_id):
            bucket = sorted(detections[(series_id, detector)], key=lambda item: (item[0], item[1]))
            point_blocks.append(
                {
                    "series_id": series_id,
                    "detector": detector,
                    "points": [
                        [point[0], point[1], canon.quantize(point[2], decimals)] for point in bucket
                    ],
                }
            )

    payload = {
        "contract_version": mirror_module.CONTRACT_VERSION,
        "mirror_version": mirror_module.MIRROR_VERSION,
        "run": run_document,
        "series": series_blocks,
        "detections": point_blocks,
        "anomaly_set_canonical": canon.canonical_json_text(anomaly_set),
        "anomaly_set_sha256": canon.canonical_digest(anomaly_set),
    }
    # The payload carries no float literal (samples travel as decimal text), so the same guard the
    # hashed documents go through applies here too -- one discipline, no exception carved out.
    canon.assert_hashable(payload)
    return payload


def build_carrier_html(parsed, run_document, anomaly_set, detections=None):
    """Render the minimal carrier page, and assert at the exit that it is self-contained."""
    payload = build_payload(parsed, run_document, anomaly_set, detections)
    html = _CARRIER_TEMPLATE.substitute(
        title=CARRIER_TITLE,
        payload_id=mirror_module.SCRIPT_ID_PAYLOAD,
        mirror_id=mirror_module.SCRIPT_ID_MIRROR,
        boot_id=SCRIPT_ID_BOOT,
        payload_json=canon.canonical_json_text(payload),
        mirror_source=mirror_module.load_mirror_js(),
        boot_js=_BOOT_JS,
        contract_version=payload["contract_version"],
        mirror_version=payload["mirror_version"],
        source_file=run_document["source"]["file"],
        n_inline=sum(len(block["rows"]) for block in payload["series"]),
        n_episodes=len(anomaly_set["episodes"]),
    )
    assert_no_external_resources(html)
    return html


def write_carrier(csv_path, out_path, spec=None):
    """Build the carrier for one CSV and write it (LF, UTF-8 without BOM).

    Returns `(run_document, anomaly_set)` so a caller can report the digest it just committed to
    without re-reading the file.
    """
    resolved = detect.resolve_spec(spec)
    parsed = csvio.load_series(csv_path, detect.csv_spec(resolved))
    run_document, anomaly_set, detections = detect.detect_all_detailed(parsed, resolved)
    html = build_carrier_html(parsed, run_document, anomaly_set, detections)
    directory = os.path.dirname(os.path.abspath(out_path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(out_path, "wb") as handle:
        handle.write(html.encode("utf-8"))
    return run_document, anomaly_set


# ---------------------------------------------------------------------------
# Zero external resources (K12), asserted on every build
# ---------------------------------------------------------------------------

_SCRIPT_BODY_RE = re.compile(r"(<script\b[^>]*>)(.*?)(</script\s*>)", re.DOTALL | re.IGNORECASE)

# Markup-level hazards. After the script bodies are masked out, any of these means the page would
# reach outside the file (a linked stylesheet, a script source, a font, a fetch target).
_EXTERNAL_MARKUP_PATTERNS = (
    (r"(?i)\bhttps?://", "absolute http(s) URL"),
    (r"(?i)src\s*=", "src attribute (an external script/image is an external request)"),
    (r"(?i)href\s*=", "href attribute (a linked resource is an external request)"),
    (r"(?i)@import", "CSS @import"),
    (r"(?i)<link\b", "<link> element"),
    (r"(?i)<iframe\b", "<iframe> element"),
    (r"(?i)integrity\s*=", "integrity attribute (implies an external resource)"),
    (r"(?<![:/])//", "protocol-relative URL"),
)

# A `url(...)` is allowed only for an inlined data: payload; anything else leaves the file.
_URL_RE = re.compile(r"(?is)url\s*\(\s*(['\"]?)(.*?)\1\s*\)")

# Network APIs must not appear anywhere in the inlined code either: "no <script src>" is not the
# same claim as "makes no request" (K12), and the second one is the claim the project makes.
_NETWORK_API_PATTERNS = (
    (r"(?i)\bfetch\s*\(", "fetch()"),
    (r"XMLHttpRequest", "XMLHttpRequest"),
    (r"(?i)\bimportScripts\s*\(", "importScripts()"),
    (r"(?i)\bnew\s+WebSocket\b", "WebSocket"),
    (r"(?i)\bnew\s+EventSource\b", "EventSource"),
    (r"(?i)navigator\.sendBeacon", "navigator.sendBeacon"),
)


def assert_no_external_resources(html_text):
    """Raise ValueError if the page could reach outside itself.

    Script bodies are masked out before the markup is scanned -- a mirror full of JavaScript
    operators is not an external reference -- but they are scanned themselves for network APIs,
    because "no external tag" and "no request" are two different claims and both are made here.
    """
    masked = []
    bodies = []
    cursor = 0
    for match in _SCRIPT_BODY_RE.finditer(html_text):
        masked.append(html_text[cursor : match.start(2)])
        bodies.append(match.group(2))
        cursor = match.end(2)
    masked.append(html_text[cursor:])
    markup = "".join(masked)
    for pattern, label in _EXTERNAL_MARKUP_PATTERNS:
        if re.search(pattern, markup):
            raise ValueError("external resource in the artifact: %s" % label)
    for match in _URL_RE.finditer(markup):
        target = match.group(2).strip()
        if not target.lower().startswith("data:"):
            raise ValueError("external resource in the artifact: url(%s)" % target[:80])
    for body in bodies:
        for pattern, label in _NETWORK_API_PATTERNS:
            if re.search(pattern, body):
                raise ValueError("the artifact's inlined code can make a request: %s" % label)
