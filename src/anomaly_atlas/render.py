"""Single-file HTML: the embedding contract, the carrier page and the M4 annotated view.

API:
  build_payload(parsed, run_document, anomaly_set, detections=None) -> dict
  build_view_html(parsed, run_document, anomaly_set, detections=None, render_spec=None, narrative=None) -> str
  write_view(csv_path, out_path, spec=None) -> (run_document, anomaly_set)
  cmd_render(csv_path, out_path, spec_path=None, narrative_path=None) -> int
  assert_no_external_resources(html_text) -> None      # resident at the exit, not test-only

M3 landed the *embedding contract* (three `<script id>` blocks, inlined samples as decimal text,
the build-time canonical JSON plus digest, the hand-written mirror) and a minimal carrier page whose
whole job was to make the recomputation gate machine-runnable. M4 keeps that contract byte for byte
-- `verify` and `tools/mirror_parity.py` read it, and `tests/test_mirror.py` pins that the inlined
mirror source equals `mirror/zaa_mirror.js` -- and replaces the page body with the annotated view:
main series with anomaly bands, peak markers and the three region textures, one small multiple per
metric, a density strip, the sensitivity sliders, the data-quality card, the per-episode zoom cards
with a threshold line derived from each episode's own `threshold_ref`, the report area and the
VERIFIED / MISMATCH badge.

Contract (plan/03 M3), one `<script>` block per concern:
  * `zaa-payload`   (application/json) -- the *input blob*: the effective run document, the raw
    samples per series, the build-time detector points, and the build-time canonical anomaly JSON
    plus its digest;
  * `zaa-mirror`    (text/javascript)  -- the hand-written mirror source, inlined verbatim;
  * `zaa-boot`      (text/javascript)  -- recompute, compare, render the badge, drive the sliders.

Payload discipline: an inlined sample is the decimal *text* the kernel parsed, never a float
literal, so the whole payload is still "integers, strings, null and their containers" and
`canon.assert_hashable` can vet it (K3). The mirror turns that text into the nearest double; both
platforms round correctly, so both work on the same bits.

Two invariants this module asserts on every build rather than once in a test:
  * zero external resources -- no CDN, no linked stylesheet, no external font, no image source, and
    no network API in the inlined code (K12);
  * no `$` anywhere in the artifact -- `string.Template` leaves an unsubstituted slot verbatim and a
    substituted value is not re-scanned, so a surviving `$` means the page is missing a value (D21i).
"""

import os
import re
import sys
from string import Template

from . import (
    canon,
    csvio,
    detect,
    facts as facts_module,
    layout,
    mirror as mirror_module,
    profile as profile_module,
    report as report_module,
)

# The page title. It names the milestone on purpose: a reader of the committed file must be able to
# tell which artifact they are holding, and the test suite pins the same string.
VIEW_TITLE = "冷链仓储温控与能耗监测 · 单文件异常标注图（M4）"

# The boot block's element id. Single definition point next to the block it names.
SCRIPT_ID_BOOT = "zaa-boot"

# `build_id` = the first 16 hex characters of the anomaly-set digest: content derived, never a
# timestamp (K2 forbids a clock field, and a clock would make two builds of one input differ).
BUILD_ID_LENGTH = 16

VIEW_WIDTH = 940
VIEW_HEIGHT = 268
MINI_HEIGHT = 92
ZOOM_WIDTH = 430
ZOOM_HEIGHT = 132
STRIP_HEIGHT = 78
STRIP_LEFT = 74
STRIP_RIGHT = 12
STRIP_TOP = 8
STRIP_BOTTOM = 28
STRIP_TICK_EVERY = 12

# Detector -> (legend label, dash pattern). The dash pattern, not the colour, is what distinguishes
# the bands: the artifact has to stay readable in a black-and-white print (plan/06 P5).
DETECTOR_STYLE = (
    ("rolling_mad_z", "rolling_mad_z（滚动中位/MAD z）", "none"),
    ("rolling_iqr", "rolling_iqr（滚动四分位距）", "8 3"),
    ("stl_resid_z", "stl_resid_z（STL 残差 z）", "2 3"),
    ("rules.static_threshold", "rules.static_threshold（静态阈值）", "9 2 2 2"),
    ("rules.pct_jump", "rules.pct_jump（阶跃比例）", "5 3"),
    ("rules.missing_run", "rules.missing_run（缺失段）", "1 4"),
    ("rules.zero_run", "rules.zero_run（零值段）", "3 2 1 2"),
    ("rules.cusum", "rules.cusum（差分 CUSUM）", "1 2"),
)

# The sensitivity slider scales exactly these three decimal parameters (D17): the rolling detectors'
# thresholds. The names are spelled here rather than sniffed from the run document, so the set of
# sliders is a reviewable line.
SLIDER_PARAMS = (("rolling_mad_z", "k"), ("rolling_iqr", "iqr_mult"), ("stl_resid_z", "k"))
SLIDER_SCALE_MIN_PERCENT = 50
SLIDER_SCALE_MAX_PERCENT = 150
SLIDER_SCALE_STEP_PERCENT = 5

_KIND_LABEL = {
    layout.KIND_GAP: "时间缺口",
    layout.KIND_ZERO: "零值段",
    layout.KIND_MISSING: "缺失段",
}


def _json_list(value):
    """A tiny literal-only JSON encoder for the boot script's embedded constants.

    The boot script needs the list of sliders as JavaScript literals. `repr` would emit Python
    syntax (`[('rolling_mad_z', 'k')]`), so the handful of literals it needs are spelled here.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value) == int(value) else repr(value)
    if isinstance(value, str):
        return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_json_list(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(
            '"%s": %s' % (key, _json_list(value[key])) for key in sorted(value)
        ) + "}"
    raise TypeError("cannot encode %r into the boot script" % (value,))


_SLIDER_JS_LITERAL = _json_list([[block, field] for block, field in SLIDER_PARAMS])

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

  /* Sensitivity sliders (M4, D17). They drive the *same* inlined kernel over a copy of the run-spec;
     the build fingerprint shown above is the immutable one and is never overwritten by a slide. At
     the baseline setting the recomputation reproduces the build fingerprint exactly, which is what
     makes "the slider only changes the view" a checkable statement rather than a promise. */
  var scaleInput = document.getElementById("k-scale");
  var gapInput = document.getElementById("max-gap");
  var SCALABLE = %s;
  function probeRunSpec() {
    var percent = Number(scaleInput.value);
    var params = JSON.parse(JSON.stringify(payload.run.params));
    var decimals = payload.run.quant_decimals;
    for (var index = 0; index < SCALABLE.length; index = index + 1) {
      var block = SCALABLE[index][0];
      var field = SCALABLE[index][1];
      var scaled = ZAA.quantize(parseFloat(params[block][field]) * percent / 100, decimals);
      params[block][field] = ZAA.fixedToStr(scaled, decimals);
    }
    params.max_gap_ms = Number(gapInput.value);
    return params;
  }
  function slide() {
    var params = probeRunSpec();
    var probePayload = JSON.parse(JSON.stringify(payload));
    probePayload.run.params = params;
    var result = ZAA.recompute(probePayload);
    var summary = JSON.parse(result.canonical).summary;
    document.getElementById("slider-digest").textContent = result.digest;
    document.getElementById("slider-episodes").textContent = summary.n_episodes;
    document.getElementById("slider-detections").textContent =
      summary.n_detections + " 个检测点 / " + summary.n_episodes + " 段";
    document.getElementById("slider-verdict").textContent =
      result.digest === payload.anomaly_set_sha256
        ? "与构建指纹一致（基线设置复算回同一份档案）"
        : "与构建指纹不同：这是当前 run-spec 的复算，上方构建结论不变";
    var fragment = {
      k_scale_percent: Number(scaleInput.value),
      max_gap_ms: params.max_gap_ms,
      rolling_mad_z: {k: params.rolling_mad_z.k},
      rolling_iqr: {iqr_mult: params.rolling_iqr.iqr_mult},
      stl_resid_z: {k: params.stl_resid_z.k}
    };
    document.getElementById("slider-spec").textContent = ZAA.canonicalJsonText(fragment);
  }
  scaleInput.addEventListener("input", slide);
  gapInput.addEventListener("change", slide);
  slide();
})();
"""

_BOOT_JS = _BOOT_JS_TEMPLATE % (
    mirror_module.SCRIPT_ID_PAYLOAD,
    _SLIDER_JS_LITERAL,
)


_CSS = """/* The annotated view is a print-oriented report, so rendering is pinned to the light scheme:
   the strokes, the hatches and the gray steps below mean the same thing on screen and on paper
   (plan/06 P5). Every fill is a primitive or a gray step; no fill is a colour-only distinction. */
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0 auto; padding: 1.5rem; max-width: 68rem; line-height: 1.65; color: #111;
  background: #fff; font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; }
h1 { font-size: 1.4rem; margin: 0 0 0.3rem; }
h2 { font-size: 1.05rem; margin: 1.4rem 0 0.6rem; }
h3 { font-size: 0.95rem; margin: 0 0 0.4rem; }
.lead { margin: 0 0 1rem; color: #444; }
.card { border: 1px solid #b8b8b8; border-radius: 6px; padding: 0.9rem 1.1rem; margin: 0 0 1rem;
  background: #fff; }
.card.verified { border-color: #17803d; background: rgba(23, 128, 61, 0.08); }
.card.mismatch { border-color: #b3261e; background: rgba(179, 38, 30, 0.08); }
#verdict-label { font-size: 1.4rem; font-weight: 700; letter-spacing: 0.08em; margin: 0 0 0.5rem; }
.card.verified #verdict-label { color: #17803d; }
.card.mismatch #verdict-label { color: #b3261e; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.15rem 1rem; margin: 0; }
dt { font-weight: 600; }
dd { margin: 0; font-family: ui-monospace, Consolas, monospace; word-break: break-all; }
ul, ol { margin: 0.3rem 0 0; padding-left: 1.3rem; }
code, pre { font-family: ui-monospace, Consolas, monospace; }
pre { background: #f4f4f4; border: 1px solid #ddd; border-radius: 4px; padding: 0.6rem 0.7rem;
  overflow-x: auto; font-size: 0.82rem; margin: 0.5rem 0 0; }
.meta { color: #444; margin: 0.75rem 0 0; font-size: 0.9rem; }
.chart { display: block; width: 100%; height: auto; margin: 0.4rem 0 0.6rem; background: #fff; }
.chart text { font-family: ui-monospace, Consolas, monospace; font-size: 10px; fill: #333; }
.frame { fill: none; stroke: #999; stroke-width: 1; }
.series-line { fill: none; stroke: #111; stroke-width: 1; }
.region { fill: none; stroke: #444; }
.region-missing { fill: #f2f2f2; stroke-dasharray: 5 3; }
.region-gap { stroke-dasharray: none; stroke-width: 1; }
.region-zero { stroke-width: 1; }
.hatch { stroke: #333; stroke-width: 1; }
.rung { stroke: #333; stroke-width: 1; }
.band { fill: rgba(17, 17, 17, 0.10); stroke: #111; stroke-width: 1; }
.peak { fill: #111; stroke: #111; stroke-width: 1; }
.zero-line { stroke: #888; stroke-width: 1; stroke-dasharray: 2 3; }
.threshold { stroke: #b3261e; stroke-width: 1; stroke-dasharray: 6 3; }
.grid-line { stroke: #e2e2e2; stroke-width: 1; }
.bin { stroke: #fff; stroke-width: 1; }
.bin-0 { fill: #ffffff; }
.bin-1 { fill: #dcdcdc; }
.bin-2 { fill: #b4b4b4; }
.bin-3 { fill: #8a8a8a; }
.bin-4 { fill: #555555; }
.bin-nodata { fill: #ffffff; stroke: #999; stroke-dasharray: 2 2; }
.legend { display: flex; flex-wrap: wrap; gap: 0.35rem 1.1rem; margin: 0.4rem 0 0; padding: 0;
  list-style: none; font-size: 0.86rem; }
.legend li { display: flex; align-items: center; gap: 0.4rem; }
.legend svg { width: 34px; height: 12px; }
.legend .swatch { fill: rgba(17, 17, 17, 0.10); stroke: #111; stroke-width: 1; }
.controls { display: grid; grid-template-columns: max-content 1fr; gap: 0.4rem 1rem;
  align-items: center; margin: 0.6rem 0 0.2rem; }
.controls label { font-weight: 600; }
.controls input, .controls select { width: 100%; max-width: 22rem; }
.episode { margin: 0 0 0.9rem; padding: 0.7rem 0.9rem; border: 1px solid #ccc; border-radius: 6px; }
.episode dl { font-size: 0.88rem; margin-top: 0.3rem; }
.tag { display: inline-block; border: 1px solid #888; border-radius: 3px; padding: 0 0.4rem;
  margin-left: 0.4rem; font-size: 0.82rem; vertical-align: 1px; }
table { border-collapse: collapse; margin: 0.4rem 0 0; font-size: 0.88rem; }
th, td { border: 1px solid #ccc; padding: 0.2rem 0.6rem; text-align: left; }
th { background: #f4f4f4; }
@media print {
  body { max-width: none; padding: 0; }
  .card { break-inside: avoid; page-break-inside: avoid; }
  .episode { break-inside: avoid; page-break-inside: avoid; }
  .chart { break-inside: avoid; page-break-inside: avoid; }
  .controls { display: none; }
  pre { background: #fff; }
}"""

_PAGE_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
$css
</style>
</head>
<body>
<header>
  <h1>$title</h1>
  <p class="lead">单文件、零外链、断网可开。本页在加载时当场重算构建时的 sha256（与徽章同一份内联 JS
  内核），并把它作为可机读的门禁结论；图形全部是手写内联 SVG，坐标取整到整数像素，可文本核验、可黑白打印。</p>
  <dl class="ids">
    <dt>build_id</dt><dd>$build_id</dd>
    <dt>数据集</dt><dd>$source_file（$source_sha256）</dd>
    <dt>异常集指纹</dt><dd>$anomaly_digest</dd>
    <dt>契约 / 镜像版本</dt><dd>$contract_version / $mirror_version</dd>
  </dl>
</header>
<section id="verdict" class="card">
  <p id="verdict-label">复算中…</p>
  <dl>
    <dt>构建指纹</dt><dd id="build-digest">–</dd>
    <dt>复算指纹</dt><dd id="recompute-digest">–</dd>
    <dt>首个差异点</dt><dd id="first-diff">–</dd>
  </dl>
  <p class="meta">复核命令：<code>anomaly-atlas verify &lt;本文件&gt;</code>（Node 通道，逐字节对账
  + 篡改探活）。仅凭浏览器打开无法证明逐字节一致，故徽章绿是必要条件而非充分条件。</p>
</section>
<section class="card" id="quality">
  <h2>数据质量卡</h2>
  <dl>
    <dt>行数 / 指标数</dt><dd>$quality_rows 行 / $quality_series 个 series</dd>
    <dt>有效值 / 缺失值</dt><dd>$quality_present / $quality_missing</dd>
    <dt>零值 / 重复时间戳（多出行）</dt><dd>$quality_zero / $quality_duplicate（+$quality_duplicate_rows）</dd>
    <dt>时间缺口 / 零值段 / 缺失段</dt><dd>$quality_gaps / $quality_zero_runs / $quality_missing_runs</dd>
    <dt>非单调点 / 时区偏移切换</dt><dd>$quality_non_monotonic / $quality_offset_switches</dd>
  </dl>
  <p class="meta">缺口 = 时间轴上的洞（两张相邻采样间隔超过该 series 的缺口阈值 $quality_gap_example），
  零值段 = 连续取值为 0 的行，缺失段 = 连续取值为空的行（空值不补 0、不插值，K9）。三类在图上用
  <strong>不同纹理</strong>画出，不靠颜色深浅区分。</p>
</section>
<section class="card" id="main-series">
  <h2>主序列（$primary_series）：$primary_episodes 段异常 · 全长 $primary_rows 点</h2>
  $main_svg
  <ul class="legend">$main_legend</ul>
  <p class="meta">y 轴范围含异常带 padding（上下各 $y_pad_percent 的幅度）；x 轴是
  <strong>行号 → 像素</strong>的固定线性映射（同一条规则也用于 small multiples）。时间缺口在该映射下
  只有一像素宽，故按缺席样本数就地加宽（加宽的是标注，不是数据）。</p>
</section>
<section class="card" id="small-multiples">
  <h2>多指标 small multiples（共享同一行号 → 像素规则）</h2>
  $small_multiples
</section>
<section class="card" id="density">
  <h2>异常密度热条（每格 $heat_bin_label，覆盖点数 / 格内有效点数）</h2>
  $density_svg
  <ul class="legend">$density_legend</ul>
  <p class="meta">覆盖 = 该 series 的某个 Episode 的时间区间包含该点；分箱从最早样本起按固定宽度切分
  （$n_bins 箱，$empty_bins 箱无有效点）；覆盖度是定点点数（整数比率），不是浮点近似。</p>
</section>
<section class="card" id="sensitivity">
  <h2>阈值灵敏度（只改显示，不改判定）</h2>
  <p class="lead">两个控件只改变<strong>这一页的复算视图</strong>：重算走的就是本文件内联的那份 JS
  内核（与徽章同一份），滑杆值同步渲染成 run-spec 片段。上方徽章里的构建指纹是不可变的那一份，
  滑杆结果<strong>不覆盖</strong>它。基线下（k_scale = 1.0 且 max_gap_ms 不变）复算必须回到同一份
  档案——这是"滑杆只改显示"这条声明的现场证据。</p>
  <div class="controls">
    <label for="k-scale">k_scale（三个滚动类检测器阈值同乘比例，1.0 基线）</label>
    <input type="range" id="k-scale" min="$scale_min" max="$scale_max" step="$scale_step" value="100">
    <label for="max-gap">max_gap_ms（Episode 合并窗口）</label>
    <select id="max-gap">
      <option value="$gap_base">$gap_base（基线）</option>
      <option value="$gap_alt">$gap_alt（两倍）</option>
    </select>
  </div>
  <dl>
    <dt>当前 run-spec 复算指纹</dt><dd id="slider-digest">–</dd>
    <dt>检测点 / Episode</dt><dd id="slider-episodes">–</dd>
    <dt>规模</dt><dd id="slider-detections">–</dd>
    <dt>与构建指纹的关系</dt><dd id="slider-verdict">–</dd>
  </dl>
  <pre id="slider-spec">（等待脚本）</pre>
</section>
<section class="card" id="episodes">
  <h2>Episode 卡片（$n_episodes 段，按严重度降序）</h2>
  <p class="lead">每张卡片是该 Episode 的局部放大（窗口 = [start_row − $pad_rows, end_row + $pad_rows]，
  夹在序列两端之间），阈值线由该 Episode 自己的 <code>threshold_ref</code> 派生（z 类为
  median ± k·scale，四分位类为 Q1/Q3 ∓ m·IQR，静态阈值为 ±level；规则型的比例/差分/存在性阈值没有
  数值线，卡片如实写明而不是画一条无从推导的线）。</p>
  $episode_cards
</section>
<section class="card" id="report">
  <h2>报告区（结论摘要，数字全部来自本页内联的档案）</h2>
  <dl>
    <dt>Episode / 检测点</dt><dd>$n_episodes 段 / $n_detections 个（$detector_streams 条检测器流）</dd>
    <dt>每检测器 Episode 数</dt><dd>$episodes_by_detector</dd>
    <dt>每 series Episode 数</dt><dd>$episodes_by_series</dd>
    <dt>周期口径</dt><dd>period_points = $period_points（$period_source），预算自 run.json 的生效值，复算不重跑估计</dd>
    <dt>渲染参数</dt><dd>pad_rows = $pad_rows，heat_bin_ms = $heat_bin_ms（本页的 render run-spec 片段，不进异常集指纹）</dd>
  </dl>
  <h3>最严重的 $top_count 段</h3>
  <table>
    <tr><th>episode_id</th><th>检测器</th><th>起始（UTC）</th><th>时长 ms</th><th>峰值得分（定点）</th><th>源行号</th></tr>
    $top_rows
  </table>
  $narrative_block
</section>
<script id="$payload_id" type="application/json">$payload_json</script>
<script id="$mirror_id" type="text/javascript">$mirror_source</script>
<script id="$boot_id" type="text/javascript">$boot_js</script>
<noscript>本页需要 JavaScript 才能完成复算与滑杆（不联网，全部在本文件内完成）；图形与表格是静态 SVG /
HTML，无脚本也能读。</noscript>
</body>
</html>
"""
)


# ---------------------------------------------------------------------------
# The payload (M3 contract, unchanged)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# The annotated view (M4)
# ---------------------------------------------------------------------------


def build_view_html(
    parsed,
    run_document,
    anomaly_set,
    detections=None,
    render_spec=None,
    narrative=None,
    profile_document=None,
):
    """Render the full annotated artifact, and assert at the exit that it is self-contained.

    A narrative is gated here, at the artifact's own construction: the numbers are checked against a
    fact ledger built from *this* archive, and any miss raises `report.NarrativeRejected` before a
    single byte is written. There is therefore no code path that produces a page carrying an
    unvalidated report (plan/01 M5 "报告生成中止").
    """
    resolved_render = layout.resolve_render_spec(render_spec)
    if profile_document is None:
        profile_document = profile_module.build_profile(parsed)
    narrative_gate = None
    if narrative:
        narrative_gate = _gate_narrative(
            parsed, run_document, anomaly_set, profile_document, narrative, resolved_render
        )
    payload = build_payload(parsed, run_document, anomaly_set, detections)
    digest = payload["anomaly_set_sha256"]

    episodes_by_series = {}
    for episode in anomaly_set["episodes"]:
        episodes_by_series.setdefault(episode["series_id"], []).append(episode)
    gap_thresholds = dict(
        (series["series_id"], series["cadence"]["gap_threshold_ms"])
        for series in profile_document["series"]
    )

    primary = _primary_series(parsed.rows_by_series, episodes_by_series)
    primary_layout = layout.main_series_layout(
        parsed.rows_by_series[primary],
        episodes_by_series.get(primary, ()),
        VIEW_WIDTH,
        VIEW_HEIGHT,
        gap_thresholds.get(primary),
    )
    miniatures = []
    for entry in layout.small_multiples_layout(
        parsed.rows_by_series,
        episodes_by_series,
        VIEW_WIDTH,
        MINI_HEIGHT,
        None,
    ):
        series_id = entry["series_id"]
        miniatures.append(
            _small_multiple(
                series_id,
                entry["layout"],
                len(parsed.rows_by_series[series_id]),
                len(episodes_by_series.get(series_id, ())),
            )
        )

    quality = profile_document["quality"]
    heat_bin_ms = resolved_render["heat_bin_ms"]
    bins = layout.density_bins(parsed.rows_by_series, episodes_by_series, heat_bin_ms)
    summary = anomaly_set["summary"]
    params = run_document["params"]

    episode_cards = []
    for episode in anomaly_set["episodes"]:
        zoom = layout.episode_zoom_layout(
            parsed.rows_by_series[episode["series_id"]],
            episode,
            resolved_render["pad_rows"],
            ZOOM_WIDTH,
            ZOOM_HEIGHT,
            gap_thresholds.get(episode["series_id"]),
        )
        episode_cards.append(_episode_card(episode, zoom))

    html = _PAGE_TEMPLATE.substitute(
        title=_escape(VIEW_TITLE),
        css=_CSS,
        build_id=digest[:BUILD_ID_LENGTH],
        source_file=_escape(run_document["source"]["file"]),
        source_sha256=run_document["source"]["sha256"][:16],
        anomaly_digest=digest,
        contract_version=payload["contract_version"],
        mirror_version=payload["mirror_version"],
        quality_rows=quality["n_rows"],
        quality_series=quality["n_series"],
        quality_present=quality["n_values_present"],
        quality_missing=quality["n_values_missing"],
        quality_zero=quality["n_values_zero"],
        quality_duplicate=quality["n_duplicate_timestamps"],
        quality_duplicate_rows=quality["n_duplicate_extra_rows"],
        quality_gaps=quality["n_gap_intervals"],
        quality_zero_runs=quality["n_zero_runs"],
        quality_missing_runs=quality["n_missing_runs"],
        quality_non_monotonic=quality["n_non_monotonic_points"],
        quality_offset_switches=quality["n_offset_switches"],
        quality_gap_example=_gap_threshold_example(profile_document["series"]),
        primary_series=_escape(primary),
        primary_episodes=len(episodes_by_series.get(primary, ())),
        primary_rows=len(parsed.rows_by_series[primary]),
        main_svg=_chart_svg(primary_layout, "主序列 %s 的异常标注图" % primary, textures=True, axes=True),
        main_legend=_legend(primary_layout["bands"]),
        y_pad_percent="%.1f%%" % (layout.Y_PAD_PPM / 10000.0),
        small_multiples="\n".join(miniatures),
        heat_bin_label=_duration_label(heat_bin_ms),
        density_svg=_density_svg(bins, heat_bin_ms),
        density_legend=_density_legend(),
        n_bins=len(bins),
        empty_bins=sum(1 for item in bins if item["n_valid"] == 0),
        scale_min=SLIDER_SCALE_MIN_PERCENT,
        scale_max=SLIDER_SCALE_MAX_PERCENT,
        scale_step=SLIDER_SCALE_STEP_PERCENT,
        gap_base=params["max_gap_ms"],
        gap_alt=params["max_gap_ms"] * 2,
        n_episodes=summary["n_episodes"],
        pad_rows=resolved_render["pad_rows"],
        episode_cards="\n".join(episode_cards),
        n_detections=summary["n_detections"],
        detector_streams=len(summary["detections_by_detector"]),
        episodes_by_detector=_counts_text(summary["episodes_by_detector"]),
        episodes_by_series=_counts_text(summary["episodes_by_series"]),
        period_points=params["period_points"],
        period_source=run_document["period_source"],
        heat_bin_ms=heat_bin_ms,
        top_count=min(len(anomaly_set["episodes"]), 5),
        top_rows=_top_rows(anomaly_set["episodes"], 5),
        narrative_block=_narrative_block(narrative, narrative_gate),
        payload_id=mirror_module.SCRIPT_ID_PAYLOAD,
        mirror_id=mirror_module.SCRIPT_ID_MIRROR,
        boot_id=SCRIPT_ID_BOOT,
        payload_json=canon.canonical_json_text(payload),
        mirror_source=mirror_module.load_mirror_js(),
        boot_js=_BOOT_JS,
    )
    assert_no_external_resources(html)
    assert_no_template_slots(html)
    return html


def write_view(csv_path, out_path, spec=None):
    """Build the annotated artifact for one CSV and write it (LF, UTF-8 without BOM).

    `spec` is the run-spec of the *render* command: the detector parameters (resolved exactly as
    `detect` resolves them, so the artifact's fingerprint is the archive's) plus an optional
    `"render"` block for the presentation-only knobs. Keeping the two apart is deliberate: the
    fingerprint covers the archive, and a change of `pad_rows` changes no archive (plan/06 D22).

    Returns `(run_document, anomaly_set)`.
    """
    detector_spec, render_spec = split_spec(spec)
    resolved = detect.resolve_spec(detector_spec)
    resolved_render = layout.resolve_render_spec(render_spec)
    parsed = csvio.load_series(csv_path, detect.csv_spec(resolved))
    return write_view_resolved(parsed, out_path, resolved, resolved_render)


def split_spec(spec):
    """Separate the detector run-spec from the render-only block."""
    if not spec:
        return None, None
    if not isinstance(spec, dict):
        raise ValueError("run-spec must be a JSON object")
    detector_spec = dict(spec)
    render_spec = detector_spec.pop("render", None)
    return detector_spec, render_spec


def write_view_resolved(parsed, out_path, resolved, render_spec, narrative=None):
    """Build and write the artifact from a parsed series and resolved specs."""
    run_document, anomaly_set, detections = detect.detect_all_detailed(parsed, resolved)
    html = build_view_html(
        parsed, run_document, anomaly_set, detections, render_spec, narrative
    )
    directory = os.path.dirname(os.path.abspath(out_path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(out_path, "wb") as handle:
        handle.write(html.encode("utf-8"))
    return run_document, anomaly_set


def _primary_series(rows_by_series, episodes_by_series):
    """The series the main view shows: most episodes, ties broken by `series_id`.

    Deterministic on purpose -- "the most anomalous series" must not depend on dict iteration order,
    or two builds of one input could show two different main views.
    """
    best = None
    for series_id in sorted(rows_by_series):
        count = len(episodes_by_series.get(series_id, ()))
        if best is None or count > best[1]:
            best = (series_id, count)
    return best[0]


def _gap_threshold_example(series_profiles):
    """One concrete gap-threshold value for the quality card's explanation."""
    for series in sorted(series_profiles, key=lambda item: item["series_id"]):
        threshold = series["cadence"]["gap_threshold_ms"]
        if threshold:
            return "%s: %d ms" % (series["series_id"], threshold)
    return "未定（该序列没有可用的主导节奏）"


# ---------------------------------------------------------------------------
# SVG builders. Every coordinate arrives as an integer from `layout`.
# ---------------------------------------------------------------------------


def _escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _detector_class(detector):
    return "d-" + detector.replace(".", "-").replace("_", "-")


def _detector_dash(detector):
    for name, _label, dash in DETECTOR_STYLE:
        if name == detector:
            return dash
    return "none"


def _svg_open(width, height, label):
    return (
        '<svg class="chart" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="%s">'
        % (width, height, width, height, _escape(label))
    )


def _polyline(segment):
    points = " ".join("%d,%d" % (x, y) for x, y in segment)
    return '<polyline class="series-line" points="%s"/>' % points


def _region_markup(region):
    """One abnormal region: an outlined span plus its texture (stripes / rungs / nothing).

    A gap carries explicit slanted stripes, a zero run carries vertical rungs, and a missing run
    carries a dashed outline and no texture at all -- three structures, so an all-black print still
    tells them apart (P5).
    """
    parts = [
        '<rect class="region region-%s" x="%d" y="%d" width="%d" height="%d"/>'
        % (
            region["kind"],
            region["x0"],
            region["y_top"],
            region["x1"] - region["x0"],
            region["y_bottom"] - region["y_top"],
        )
    ]
    for stripe in region["stripes"]:
        parts.append(
            '<line class="hatch" x1="%d" y1="%d" x2="%d" y2="%d"/>'
            % (stripe[0], stripe[1], stripe[2], stripe[3])
        )
    for rung in region["rungs"]:
        parts.append(
            '<line class="rung" x1="%d" y1="%d" x2="%d" y2="%d"/>'
            % (rung[0], rung[1], rung[2], rung[3])
        )
    return "".join(parts)


def _band_markup(band):
    parts = [
        '<rect class="band %s" x="%d" y="%d" width="%d" height="%d" stroke-dasharray="%s"/>'
        % (
            _detector_class(band["detector"]),
            band["x0"],
            band["y_top"],
            band["x1"] - band["x0"],
            band["y_bottom"] - band["y_top"],
            _detector_dash(band["detector"]),
        )
    ]
    if band["peak_x"] is not None:
        parts.append(
            '<polygon class="peak" points="%d,%d %d,%d %d,%d"/>'
            % (
                band["peak_x"],
                band["peak_y"] - 3,
                band["peak_x"] - 4,
                band["peak_y"] + 5,
                band["peak_x"] + 4,
                band["peak_y"] + 5,
            )
        )
    return "".join(parts)


def _axes_markup(layout_document):
    plot = layout_document["frame"]
    parts = [
        '<rect class="frame" x="%d" y="%d" width="%d" height="%d"/>'
        % (plot["left"], plot["top"], plot["plot_width"], plot["plot_height"])
    ]
    if layout_document["zero_y"] is not None:
        parts.append(
            '<line class="zero-line" x1="%d" y1="%d" x2="%d" y2="%d"/>'
            % (plot["left"], layout_document["zero_y"], plot["right"], layout_document["zero_y"])
        )
    for tick in layout_document["y_ticks"]:
        parts.append(
            '<text x="%d" y="%d" text-anchor="end">%s</text>'
            % (plot["left"] - 5, tick["y"] + 3, _escape(tick["label"]))
        )
    for tick in layout_document["x_ticks"]:
        parts.append(
            '<line class="grid-line" x1="%d" y1="%d" x2="%d" y2="%d"/>'
            % (tick["x"], plot["top"], tick["x"], plot["bottom"])
        )
        parts.append(
            '<text x="%d" y="%d" text-anchor="middle">%d</text>'
            % (tick["x"], plot["bottom"] + 14, tick["row_no"])
        )
    parts.append(
        '<text x="%d" y="%d" text-anchor="end">行号</text>'
        % (plot["right"], plot["bottom"] + 26)
    )
    return "".join(parts)


def _chart_svg(layout_document, label, textures=True, axes=False):
    plot = layout_document["frame"]
    parts = [_svg_open(plot["width"], plot["height"], label)]
    for region in layout_document["regions"]:
        if textures:
            parts.append(_region_markup(region))
        else:
            parts.append(
                '<rect class="region region-%s" x="%d" y="%d" width="%d" height="%d"/>'
                % (region["kind"], region["x0"], region["y_top"], region["x1"] - region["x0"], region["y_bottom"] - region["y_top"])
            )
    for band in layout_document["bands"]:
        parts.append(_band_markup(band))
    for segment in layout_document["segments"]:
        parts.append(_polyline(segment))
    if axes:
        parts.append(_axes_markup(layout_document))
    parts.append("</svg>")
    return "".join(parts)


def _legend(bands):
    """A legend for the detectors that actually drew a band, with its dash pattern and its label."""
    present = sorted(set(band["detector"] for band in bands))
    items = []
    for detector in present:
        items.append(
            '<li><svg width="34" height="12" viewBox="0 0 34 12" aria-hidden="true">'
            '<rect class="swatch" x="0" y="1" width="34" height="10" stroke-dasharray="%s"/></svg>'
            "<span>%s</span></li>" % (_detector_dash(detector), _escape(_detector_label(detector)))
        )
    items.append(
        '<li><svg width="34" height="12" viewBox="0 0 34 12" aria-hidden="true">'
        '<line class="hatch" x1="0" y1="11" x2="8" y2="1"/><line class="hatch" x1="10" y1="11" x2="18" y2="1"/>'
        '<line class="hatch" x1="20" y1="11" x2="28" y2="1"/></svg><span>时间缺口（斜纹）</span></li>'
    )
    items.append(
        '<li><svg width="34" height="12" viewBox="0 0 34 12" aria-hidden="true">'
        '<line class="rung" x1="6" y1="2" x2="6" y2="10"/><line class="rung" x1="14" y1="2" x2="14" y2="10"/>'
        '<line class="rung" x1="22" y1="2" x2="22" y2="10"/><line class="rung" x1="30" y1="2" x2="30" y2="10"/>'
        "</svg><span>零值段（竖栅）</span></li>"
    )
    items.append(
        '<li><svg width="34" height="12" viewBox="0 0 34 12" aria-hidden="true">'
        '<rect class="region region-missing" x="0" y="1" width="34" height="10"/></svg>'
        "<span>缺失段（虚线框）</span></li>"
    )
    items.append('<li><span>▲ 峰值标记；红色虚线 = 由 threshold_ref 派生的阈值线</span></li>')
    return "".join(items)


def _detector_label(detector):
    for name, label, _dash in DETECTOR_STYLE:
        if name == detector:
            return label
    return detector


def _small_multiple(series_id, layout_document, n_rows, n_episodes):
    label = "%s：%d 点，%d 段异常" % (series_id, n_rows, n_episodes)
    return (
        '<h3>%s</h3>\n%s'
        % (
            _escape(label),
            _chart_svg(layout_document, "small multiple %s" % series_id, textures=False),
        )
    )


def _density_svg(bins, heat_bin_ms):
    if not bins:
        return "<p>没有可分箱的样本。</p>"
    plot_width = VIEW_WIDTH - STRIP_LEFT - STRIP_RIGHT
    plot_height = STRIP_HEIGHT - STRIP_TOP - STRIP_BOTTOM
    step = plot_width // len(bins)
    if step < 1:
        step = 1
    parts = [_svg_open(VIEW_WIDTH, STRIP_HEIGHT, "异常密度热条")]
    for item in bins:
        x = STRIP_LEFT + item["bin_index"] * plot_width // len(bins)
        if item["n_valid"] == 0:
            css = "bin bin-nodata"
        else:
            css = "bin bin-%s" % _coverage_step(item["coverage_q"])
        parts.append(
            '<rect class="%s" x="%d" y="%d" width="%d" height="%d"/>'
            % (css, x, STRIP_TOP, step, plot_height)
        )
    parts.append(
        '<rect class="frame" x="%d" y="%d" width="%d" height="%d"/>'
        % (STRIP_LEFT, STRIP_TOP, plot_width, plot_height)
    )
    for item in bins:
        if item["bin_index"] % STRIP_TICK_EVERY:
            continue
        x = STRIP_LEFT + item["bin_index"] * plot_width // len(bins)
        parts.append(
            '<text x="%d" y="%d" text-anchor="middle">%s</text>'
            % (x, STRIP_TOP + plot_height + 14, _escape(_short_stamp(item["start_ms"])))
        )
    parts.append(
        '<text x="%d" y="%d" text-anchor="end">%s</text>'
        % (STRIP_LEFT - 6, STRIP_TOP + 12, _escape("每格 " + _duration_label(heat_bin_ms)))
    )
    parts.append("</svg>")
    return "".join(parts)


def _coverage_step(coverage_q):
    """Five discrete gray steps. Discrete on purpose: a continuous ramp would be unreadable in
    black and white, and the legend states what each step means."""
    if coverage_q <= 0:
        return 0
    if coverage_q <= 250000:
        return 1
    if coverage_q <= 500000:
        return 2
    if coverage_q <= 750000:
        return 3
    return 4


def _density_legend():
    items = [
        '<li><svg width="24" height="12" viewBox="0 0 24 12" aria-hidden="true">'
        '<rect class="bin bin-nodata" x="0" y="1" width="24" height="10"/></svg><span>无有效点</span></li>'
    ]
    labels = ("0", "≤ 25%", "≤ 50%", "≤ 75%", "> 75%")
    for step in range(5):
        items.append(
            '<li><svg width="24" height="12" viewBox="0 0 24 12" aria-hidden="true">'
            '<rect class="bin bin-%d" x="0" y="1" width="24" height="10"/></svg><span>覆盖 %s</span></li>'
            % (step, labels[step])
        )
    return "".join(items)


def _short_stamp(epoch_ms):
    """A short axis label derived from the integer timestamp (no parsing, no timezone database)."""
    from .timebase import epoch_ms_to_iso

    return epoch_ms_to_iso(epoch_ms)[5:16]


def _duration_label(ms):
    if ms % 3600000 == 0:
        return "%d 小时" % (ms // 3600000)
    if ms % 60000 == 0:
        return "%d 分钟" % (ms // 60000)
    return "%d 毫秒" % ms


def _episode_card(episode, zoom):
    """One Episode card: the facts, the derived threshold line, and the local zoom."""
    threshold_text = "该检测器的阈值不在数值域（规则型），见下方 threshold_ref"
    if zoom["thresholds"]:
        threshold_text = "；".join(
            "%s = %s" % (_side_label(item["side"]), item["label"]) for item in zoom["thresholds"]
        )
    ref_line = " ".join(canon.canonical_json_text(episode.get("threshold_ref") or {}).split())
    window = zoom["window"]
    peak_text = "（该 Episode 没有可标注的数值点：检测依据是样本的存在性）"
    if zoom["peak"]["value_q"] is not None:
        peak_text = "峰值 %s（行 %d）" % (
            canon.fixed_to_str(zoom["peak"]["value_q"], layout.QUANT_DECIMALS),
            episode["end_row"],
        )
    return (
        '<article class="episode" id="ep-%s">\n'
        "<h3><code>%s</code><span class=\"tag\">%s</span>"
        '<span class="tag">峰值得分 %s</span></h3>\n'
        "<dl>\n"
        "<dt>检测器</dt><dd>%s</dd>\n"
        "<dt>起止（UTC）</dt><dd>%s → %s</dd>\n"
        "<dt>时长 / 点数</dt><dd>%d ms / %d 点</dd>\n"
        "<dt>源行号</dt><dd>%d → %d</dd>\n"
        "<dt>阈值线（由 threshold_ref 派生）</dt><dd>%s</dd>\n"
        "<dt>threshold_ref</dt><dd>%s</dd>\n"
        "<dt>放大窗口</dt><dd>行 %d → %d（pad_rows = %d，共 %d 点；%s）</dd>\n"
        "</dl>\n"
        '<p><svg class="chart" width="%d" height="%d" viewBox="0 0 %d %d" role="img" '
        'aria-label="%s">%s</svg></p>\n'
        "</article>"
        % (
            _escape(episode["episode_id"]),
            _escape(episode["episode_id"]),
            _escape(episode["detector"]),
            canon.fixed_to_str(episode["peak_score_q"], layout.QUANT_DECIMALS),
            _escape(episode["detector"]),
            _escape(episode["start"]),
            _escape(episode["end"]),
            episode["duration_ms"],
            episode["n_points"],
            episode["start_row"],
            episode["end_row"],
            _escape(threshold_text),
            _escape(ref_line),
            window["start_row"],
            window["end_row"],
            window["pad_rows"],
            window["n_points"],
            _escape(peak_text),
            ZOOM_WIDTH,
            ZOOM_HEIGHT,
            ZOOM_WIDTH,
            ZOOM_HEIGHT,
            _escape("Episode %s 的局部放大" % episode["episode_id"]),
            _zoom_body(zoom, episode["detector"]),
        )
    )


def _zoom_body(zoom, detector):
    parts = []
    for region in zoom["regions"]:
        parts.append(_region_markup(region))
    parts.append(
        '<rect class="band %s" x="%d" y="%d" width="%d" height="%d" stroke-dasharray="%s"/>'
        % (
            _detector_class(detector),
            zoom["band"]["x0"],
            zoom["band"]["y_top"],
            zoom["band"]["x1"] - zoom["band"]["x0"],
            zoom["band"]["y_bottom"] - zoom["band"]["y_top"],
            _detector_dash(detector),
        )
    )
    for item in zoom["thresholds"]:
        parts.append(
            '<line class="threshold" x1="%d" y1="%d" x2="%d" y2="%d"/>'
            % (zoom["frame"]["left"], item["y"], zoom["frame"]["right"], item["y"])
        )
    if zoom["peak"]["x"] is not None:
        parts.append(
            '<polygon class="peak" points="%d,%d %d,%d %d,%d"/>'
            % (
                zoom["peak"]["x"],
                zoom["peak"]["y"] - 3,
                zoom["peak"]["x"] - 4,
                zoom["peak"]["y"] + 5,
                zoom["peak"]["x"] + 4,
                zoom["peak"]["y"] + 5,
            )
        )
    for segment in zoom["segments"]:
        parts.append(_polyline(segment))
    for item in zoom["thresholds"]:
        parts.append(
            '<text x="%d" y="%d" text-anchor="end">%s</text>'
            % (zoom["frame"]["left"] - 4, item["y"] + 3, _escape(item["label"]))
        )
    parts.append(
        '<rect class="frame" x="%d" y="%d" width="%d" height="%d"/>'
        % (zoom["frame"]["left"], zoom["frame"]["top"], zoom["frame"]["plot_width"], zoom["frame"]["plot_height"])
    )
    return "".join(parts)


def _side_label(side):
    return {"upper": "上阈值", "lower": "下阈值", "level": "阈值"}.get(side, side)


def _counts_text(counts):
    if not counts:
        return "（无）"
    return "，".join("%s: %d" % (key, counts[key]) for key in sorted(counts))


def _top_rows(episodes, limit):
    if not episodes:
        return "<tr><td colspan=\"6\">（无）</td></tr>"
    rows = []
    for episode in episodes[:limit]:
        rows.append(
            "<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%d → %d</td></tr>"
            % (
                _escape(episode["episode_id"]),
                _escape(episode["detector"]),
                _escape(episode["start"]),
                episode["duration_ms"],
                canon.fixed_to_str(episode["peak_score_q"], layout.QUANT_DECIMALS),
                episode["start_row"],
                episode["end_row"],
            )
        )
    return "\n    ".join(rows)


def _gate_narrative(parsed, run_document, anomaly_set, profile_document, narrative, render_spec):
    """Run the number whitelist over a narrative; raise with every miss, or return the counts.

    The ledger is built here from the same archive the page is built from -- at the artifact's own
    bin width, so a narrative may cite the density strip's coverage and the gate will agree with the
    strip on screen.
    """
    ledger = facts_module.build_facts(
        run_document,
        anomaly_set,
        profile_document=profile_document,
        rows_by_series=parsed.rows_by_series,
        heat_bin_ms=render_spec["heat_bin_ms"],
    )
    result = report_module.audit(narrative, ledger)
    if result["violations"]:
        raise report_module.NarrativeRejected(result["violations"])
    return {
        "summary": report_module.gate_summary(result),
        "n_facts": len(ledger["facts"]),
        "n_episodes": len(ledger["catalog"]["episode_ids"]),
    }


def _narrative_block(narrative, gate=None):
    if not narrative:
        return (
            '<p class="meta">报告区暂不含自由叙事：把模型撰写的叙事（引用 <code>episode_id</code>、'
            "行号与档案里的数字）写成文本，用 <code>render --narrative &lt;path&gt;</code> 交上来；"
            "每个数字都要命中 <code>facts.json</code> 白名单，未命中则整份报告不生成（exit 1）。</p>"
        )
    banner = (
        '<p class="meta">数字白名单：%s 全部命中 <code>facts.json</code>（%d 条事实，'
        "%d 个 episode_id 可解析）；未命中即 exit 1 且不生成产物。</p>"
        % (gate["summary"], gate["n_facts"], gate["n_episodes"])
        if gate
        else ""
    )
    return (
        '<h3>叙事（<code>--narrative</code>，已通过数字白名单门禁）</h3>%s<pre>%s</pre>'
        % (banner, _escape(narrative))
    )


# ---------------------------------------------------------------------------
# CLI body
# ---------------------------------------------------------------------------


def cmd_render(csv_path, out_path, spec_path=None, narrative_path=None):
    """CLI body for `render`: 0 on success, 1 when a narrative fails the whitelist, 2 on usage.

    Nothing is written on 1 or 2 -- a rejected report leaves no half-built artifact behind.
    """
    from .cli import EXIT_FAIL, EXIT_OK, EXIT_USAGE

    spec = None
    if spec_path:
        if not os.path.isfile(spec_path):
            _warn("run-spec file not found: %s" % spec_path)
            return EXIT_USAGE
        try:
            import json

            with open(spec_path, "rb") as handle:
                spec = json.loads(handle.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            _warn("run-spec is not readable JSON: %s" % (exc,))
            return EXIT_USAGE
        except OSError as exc:
            _warn("cannot read %s: %s" % (spec_path, exc))
            return EXIT_USAGE
        if not isinstance(spec, dict):
            _warn("run-spec must be a JSON object: %s" % (spec_path,))
            return EXIT_USAGE

    narrative = None
    if narrative_path:
        if not os.path.isfile(narrative_path):
            _warn("narrative file not found: %s" % narrative_path)
            return EXIT_USAGE
        try:
            with open(narrative_path, "rb") as handle:
                narrative = handle.read().decode("utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            _warn("cannot read %s: %s" % (narrative_path, exc))
            return EXIT_USAGE
        if "$" in narrative:
            # The artifact must contain no `$` at all (D21i). A narrative that carries one would
            # either survive into the page as a stray slot or have to be silently rewritten; a loud
            # usage error is the honest third option.
            _warn("narrative must not contain '$': the artifact forbids any '$' (an unsubstituted "
                  "template slot is how the boot script once shipped looking up a null element)")
            return EXIT_USAGE

    try:
        detector_spec, render_spec = split_spec(spec)
        resolved = detect.resolve_spec(detector_spec)
        resolved_render = layout.resolve_render_spec(render_spec)
    except (KeyError, ValueError) as exc:
        _warn("run-spec: %s" % (exc,))
        return EXIT_USAGE

    try:
        parsed = csvio.load_series(csv_path, detect.csv_spec(resolved))
    except csvio.CsvContractError as exc:
        _warn("input error: %s" % (exc,))
        return EXIT_USAGE
    except OSError as exc:
        _warn("cannot read %s: %s" % (csv_path, exc))
        return EXIT_USAGE

    try:
        run_document, anomaly_set = write_view_resolved(
            parsed, out_path, resolved, resolved_render, narrative
        )
    except report_module.NarrativeRejected as rejected:
        # The whitelist gate refused the report, so nothing was written: list every miss, not just
        # the first, and answer exit 1 (a defect found by a gate, K1/D8).
        _warn(
            "narrative failed the facts.json whitelist: %d unmatched reference(s); report NOT "
            "generated" % len(rejected.violations)
        )
        report_module.render_violations(rejected.violations, sys.stderr)
        return EXIT_FAIL
    except OSError as exc:
        _warn("cannot write %s: %s" % (out_path, exc))
        return EXIT_USAGE

    summary = anomaly_set["summary"]
    print(
        "render: %d episode(s), %d detection(s) over %d series -> %s"
        % (
            summary["n_episodes"],
            summary["n_detections"],
            len(parsed.series_order),
            out_path,
        )
    )
    print("anomaly-set sha256 %s" % canon.canonical_digest(anomaly_set))
    print(
        "render spec: pad_rows=%d heat_bin_ms=%d (presentation only; not part of the fingerprint)"
        % (resolved_render["pad_rows"], resolved_render["heat_bin_ms"])
    )
    return EXIT_OK


def _warn(message):
    import sys

    print("error: %s" % message, file=sys.stderr)


# ---------------------------------------------------------------------------
# Zero external resources (K12) and the no-slot invariant (D21i), both asserted on every build
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


def assert_no_template_slots(html_text):
    """Raise ValueError if any `$` survives into the artifact (D21i).

    `string.Template` leaves an unsubstituted slot verbatim, and a value substituted into another
    value is not scanned again -- so a surviving `$` is exactly the signature of "the page is
    missing a value it will look up at load time". The Node channel cannot see this class of defect
    (it drives the mirror directly and never runs the boot script), which is why the assertion lives
    in the builder, next to the template that could break it.
    """
    if "$" in html_text:
        position = html_text.index("$")
        raise ValueError(
            "the artifact carries a '$' at byte %d: a template slot survived, or a substituted "
            "value introduced one (%r)" % (position, html_text[position : position + 40])
        )
