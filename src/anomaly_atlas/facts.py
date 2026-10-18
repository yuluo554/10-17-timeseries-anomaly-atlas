"""Fact ledger (M5) -> facts.json: the only authoritative source of numbers for a report.

API:
  Ledger(decimals)                                  # duplicate fact_id is an error, not an overwrite
  Ledger.add(fact_id, value, kind, label, unit=None)
  scaled_value(entry, decimals=6) -> int|None       # ints and fixed-point strings on one scale
  numeric_index(document) -> {scaled: [fact_id, ...]}
  build_facts(run_document, anomaly_set, profile_document=None, rows_by_series=None,
              heat_bin_ms=None) -> dict

Every number the project can legitimately cite gets a `fact_id` (`episodes.total`,
`episode.<episode_id>.peak_score_q`, `series.<id>.n_gaps`, `detector.<name>.n_points`,
`bin.<index>.coverage_q`, ...). The ledger is assembled from conclusions that already exist -- the
anomaly archive, the run document and the profile -- so this module reads no CSV and runs no
detector: a number in a report is a *citation*, never a fresh computation (K14).

Values are integers or fixed-point strings, never floats (`canon.assert_hashable` guards the dump
outlet), and the document is written through `canon.canonical_json_bytes`, so two runs over the same
archive produce byte-identical ledgers (K2/K3). Fixed-point facts keep the shape `run.json` uses for
decimal parameters, so the value a reader sees and the value the gate compares are one
representation.

Alongside the numbers the document carries a `catalog`: the episode ids, series ids, detector names
and the row numbers that actually occur in the archive. That is what lets the report gate resolve an
episode reference (K14) without a second input file -- facts.json is self-sufficient, which is why
`check-report` needs only `--facts` and `--text`.
"""

import re

from . import canon, layout

LEDGER_VERSION = "1"

# Value forms a fact may take. `int` is a plain integer, `fixed6` is the decimal display string
# built from a scaled integer (the same form decimal parameters take in run.json), and `text` is a
# non-numeric fact (an episode's detector, say) which the number gate never matches against.
KIND_INT = "int"
KIND_FIXED = "fixed6"
KIND_TEXT = "text"
FACT_KINDS = (KIND_INT, KIND_FIXED, KIND_TEXT)

_FACT_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_FIXED_RE = re.compile(r"^-?\d+\.\d+$")


class DuplicateFactError(ValueError):
    """Two facts claimed the same id. The ledger's whole point is that an id names one number."""


def _check_fact_id(fact_id):
    if not isinstance(fact_id, str) or not _FACT_ID_RE.match(fact_id):
        raise ValueError("fact_id must be a dotted identifier, got %r" % (fact_id,))
    return fact_id


def _check_value(value, kind, decimals):
    if kind == KIND_INT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("int fact must carry a real integer, got %r" % (value,))
        return value
    if kind == KIND_FIXED:
        if isinstance(value, bool) or not isinstance(value, str) or not _FIXED_RE.match(value):
            raise ValueError("fixed-point fact must carry a decimal string, got %r" % (value,))
        if len(value.split(".")[1]) != decimals:
            raise ValueError("fixed-point fact %r must carry %d decimals" % (value, decimals))
        return value
    if kind == KIND_TEXT:
        if not isinstance(value, str):
            raise ValueError("text fact must carry a string, got %r" % (value,))
        return value
    raise ValueError("unknown fact kind %r (expected one of %s)" % (kind, ", ".join(FACT_KINDS)))


class Ledger(object):
    """An append-only id -> fact table that refuses a second fact under the same id."""

    def __init__(self, decimals=6):
        self.decimals = int(decimals)
        self._entries = {}

    def add(self, fact_id, value, kind, label, unit=None):
        """Record one fact. Raises on a duplicate id, an unknown kind or a malformed value."""
        fact_id = _check_fact_id(fact_id)
        if fact_id in self._entries:
            raise DuplicateFactError("fact_id %r is already in the ledger" % (fact_id,))
        entry = {
            "kind": kind,
            "label": label,
            "value": _check_value(value, kind, self.decimals),
        }
        if unit is not None:
            entry["unit"] = unit
        self._entries[fact_id] = entry
        return self

    def add_int(self, fact_id, value, label, unit=None):
        return self.add(fact_id, int(value), KIND_INT, label, unit)

    def add_fixed(self, fact_id, q, label, unit=None):
        return self.add(fact_id, canon.fixed_to_str(int(q), self.decimals), KIND_FIXED, label, unit)

    def add_text(self, fact_id, value, label):
        return self.add(fact_id, value, KIND_TEXT, label)

    def ids(self):
        return sorted(self._entries)

    def entries(self):
        """The fact table with ids in sorted order (the dump sorts keys anyway, K2)."""
        return dict((fact_id, self._entries[fact_id]) for fact_id in self.ids())

    def __len__(self):
        return len(self._entries)


def scaled_value(entry, decimals=6):
    """One comparison scale for both value forms: the value scaled by 10**decimals.

    Returns `None` for a text fact. Kept here, next to the two forms' definitions, so the gate
    cannot drift from the ledger by re-deriving the scale on its own.
    """
    kind = entry["kind"]
    value = entry["value"]
    if kind == KIND_TEXT:
        return None
    scale = 1
    for _step in range(int(decimals)):
        scale = scale * 10
    if kind == KIND_INT:
        return value * scale
    sign = -1 if value.startswith("-") else 1
    body = value[1:] if sign < 0 else value
    whole, frac = body.split(".")
    if len(frac) < decimals:
        frac = frac + "0" * (decimals - len(frac))
    elif len(frac) > decimals:
        frac = frac[:decimals]
    return sign * (int(whole) * scale + int(frac))


def numeric_index(document):
    """`{scaled_value: [fact_id, ...]}` over the ledger's numeric facts.

    Several facts may legitimately carry the same number (a zero appears as a count and as a row
    number), so a value maps to a *list* of ids and the gate reports the first id in sorted order:
    matching stays deterministic without pretending the values are unique.
    """
    decimals = int(document.get("quant_decimals", 6))
    index = {}
    for fact_id, entry in document["facts"].items():
        scaled = scaled_value(entry, decimals)
        if scaled is None:
            continue
        index.setdefault(scaled, []).append(fact_id)
    for fact_ids in index.values():
        fact_ids.sort()
    return index


def _episodes_by_series(episodes):
    grouped = {}
    for episode in episodes:
        grouped.setdefault(episode["series_id"], []).append(episode)
    return grouped


def build_facts(
    run_document,
    anomaly_set,
    profile_document=None,
    rows_by_series=None,
    heat_bin_ms=None,
):
    """Assemble the fact ledger from conclusions that already exist.

    `profile_document` (optional) contributes the data-quality counts and the gap / zero / missing
    run tallies; `rows_by_series` plus `heat_bin_ms` (optional) add the density-strip bin coverage,
    which is a *presentation* binning over episodes that already exist -- `layout.density_bins` is
    the single definition of that binning, reused here so the ledger and the page cannot disagree.
    """
    decimals = int(run_document.get("quant_decimals", layout.QUANT_DECIMALS))
    ledger = Ledger(decimals)
    summary = anomaly_set["summary"]
    episodes = anomaly_set["episodes"]

    # --- aggregate counts ---------------------------------------------------
    ledger.add_int("episodes.total", len(episodes), "Episode 总数", "段")
    ledger.add_int(
        "episodes.points_total",
        sum(episode["n_points"] for episode in episodes),
        "所有 Episode 的异常点总数",
        "点",
    )
    ledger.add_int(
        "episodes.duration_ms_total",
        sum(episode["duration_ms"] for episode in episodes),
        "所有 Episode 的时长之和",
        "ms",
    )
    if episodes:
        ledger.add_fixed(
            "episodes.peak_score_q_max",
            max(episode["peak_score_q"] for episode in episodes),
            "全部 Episode 中的最高峰值得分",
        )
    ledger.add_int("detections.total", summary["n_detections"], "全部检测器流命中的点数", "点")

    # --- effective parameters -----------------------------------------------
    # A report that says "k 为 3.500000" is citing the run, not computing anything, so the resolved
    # parameter block belongs in the ledger too: without it the gate would forbid the author from
    # naming the very thresholds the artifact prints (K8: effective values, one representation).
    for name in sorted(run_document["params"]):
        value = run_document["params"][name]
        if isinstance(value, dict):
            for param in sorted(value):
                _add_param(ledger, "detector.%s.%s" % (name, param), value[param], name, param)
        else:
            _add_param(ledger, "run.%s" % name, value, "运行参数", name)

    # --- per detector stream ------------------------------------------------
    detectors = set(summary["detections_by_detector"])
    detectors.update(summary["episodes_by_detector"])
    for detector in sorted(detectors):
        ledger.add_int(
            "detector.%s.n_points" % detector,
            summary["detections_by_detector"].get(detector, 0),
            "检测器 %s 命中的点数" % detector,
            "点",
        )
        ledger.add_int(
            "detector.%s.n_episodes" % detector,
            summary["episodes_by_detector"].get(detector, 0),
            "检测器 %s 形成的 Episode 数" % detector,
            "段",
        )

    # --- per series (run document) ------------------------------------------
    series_ids = []
    for series in run_document["series"]:
        series_id = series["series_id"]
        series_ids.append(series_id)
        for key, value, label, unit in (
            ("n_points", series["n_points"], "行数", "行"),
            ("n_values_present", series["n_values_present"], "有效值个数", "点"),
            ("n_values_missing", series["n_values_missing"], "缺失值个数", "点"),
            ("cadence_ms", series["cadence_ms"], "主导采样节奏", "ms"),
            ("first_ms", series["first_ms"], "最早时间戳（epoch 毫秒）", "ms"),
            ("last_ms", series["last_ms"], "最晚时间戳（epoch 毫秒）", "ms"),
        ):
            if value is None:
                continue
            ledger.add_int(
                "series.%s.%s" % (series_id, key),
                value,
                "series %s 的%s" % (series_id, label),
                unit,
            )
        if series["n_grid_cells"] is not None:
            ledger.add_int(
                "series.%s.n_grid_cells" % series_id,
                series["n_grid_cells"],
                "series %s 的时间栅格格数" % series_id,
                "格",
            )
        ledger.add_int(
            "series.%s.n_episodes" % series_id,
            summary["episodes_by_series"].get(series_id, 0),
            "series %s 的 Episode 数" % series_id,
            "段",
        )

    # --- per episode --------------------------------------------------------
    episode_ids = []
    archive_rows = set()
    for episode in episodes:
        episode_id = episode["episode_id"]
        episode_ids.append(episode_id)
        archive_rows.add(episode["start_row"])
        archive_rows.add(episode["end_row"])
        ledger.add_fixed(
            "episode.%s.peak_score_q" % episode_id,
            episode["peak_score_q"],
            "Episode %s 的峰值得分" % episode_id,
        )
        ledger.add_int(
            "episode.%s.duration_ms" % episode_id,
            episode["duration_ms"],
            "Episode %s 的持续时长" % episode_id,
            "ms",
        )
        ledger.add_int(
            "episode.%s.n_points" % episode_id,
            episode["n_points"],
            "Episode %s 的异常点数" % episode_id,
            "点",
        )
        ledger.add_int(
            "episode.%s.start_row" % episode_id,
            episode["start_row"],
            "Episode %s 的起始行号" % episode_id,
            "行",
        )
        ledger.add_int(
            "episode.%s.end_row" % episode_id,
            episode["end_row"],
            "Episode %s 的结束行号" % episode_id,
            "行",
        )
        # Epoch milliseconds, never the ISO display form: ISO strings belong to anomalies.json
        # alone, so a report cites a timestamp through this integer (K2).
        ledger.add_int(
            "episode.%s.start_ms" % episode_id,
            _iso_ms(episode["start"]),
            "Episode %s 的起始时间戳（epoch 毫秒）" % episode_id,
            "ms",
        )
        ledger.add_int(
            "episode.%s.end_ms" % episode_id,
            _iso_ms(episode["end"]),
            "Episode %s 的结束时间戳（epoch 毫秒）" % episode_id,
            "ms",
        )
        ledger.add_text(
            "episode.%s.detector" % episode_id,
            episode["detector"],
            "Episode %s 的触发检测器" % episode_id,
        )

    # --- data quality (profile) ---------------------------------------------
    quality_params = None
    if profile_document is not None:
        quality_params = profile_document["params"]
        quality = profile_document["quality"]
        for key in sorted(quality):
            ledger.add_int("quality.%s" % key, quality[key], "数据质量计数 %s" % key)
        for series in profile_document["series"]:
            series_id = series["series_id"]
            for key, label in (
                ("n_values_zero", "零值个数"),
                ("n_values_negative", "负值个数"),
                ("span_ms", "时间跨度"),
            ):
                ledger.add_int(
                    "series.%s.%s" % (series_id, key),
                    series[key],
                    "series %s 的%s" % (series_id, label),
                )
            for key, label in (
                ("n_gaps", "数据缺口数"),
                ("n_zero_runs", "零值段数"),
                ("n_missing_runs", "缺失段数"),
            ):
                ledger.add_int(
                    "series.%s.%s" % (series_id, key),
                    len(series[key[2:]]),
                    "series %s 的%s" % (series_id, label),
                    "处",
                )

    # --- density strip bins (a presentation binning of existing conclusions) --
    n_bins = 0
    if rows_by_series and heat_bin_ms:
        ledger.add_int(
            "render.heat_bin_ms",
            int(heat_bin_ms),
            "密度热条的分箱宽度（呈现参数，不进档案指纹）",
            "ms",
        )
        bins = layout.density_bins(rows_by_series, _episodes_by_series(episodes), int(heat_bin_ms))
        n_bins = len(bins)
        ledger.add_int("bins.total", n_bins, "密度热条的分箱数", "箱")
        for entry in bins:
            index = entry["bin_index"]
            prefix = "bin.%d" % index
            ledger.add_int(
                "%s.start_ms" % prefix,
                entry["start_ms"],
                "第 %d 箱的起始时间戳（epoch 毫秒）" % index,
                "ms",
            )
            ledger.add_int("%s.n_valid" % prefix, entry["n_valid"], "第 %d 箱的有效点数" % index, "点")
            ledger.add_int(
                "%s.n_covered" % prefix,
                entry["n_covered"],
                "第 %d 箱被 Episode 覆盖的点数" % index,
                "点",
            )
            ledger.add_fixed(
                "%s.coverage_q" % prefix,
                entry["coverage_q"],
                "第 %d 箱的 Episode 覆盖度（覆盖点数 / 有效点数）" % index,
            )

    document = {
        "schema_version": LEDGER_VERSION,
        "canon_version": canon.CANON_VERSION,
        "quant_decimals": decimals,
        "source": run_document["source"],
        "params": {
            "quality": quality_params,
            "heat_bin_ms": int(heat_bin_ms) if heat_bin_ms else None,
        },
        "facts": ledger.entries(),
        "catalog": {
            "episode_ids": sorted(episode_ids),
            "series_ids": sorted(series_ids),
            "detectors": sorted(detectors),
            "archive_rows": sorted(archive_rows),
        },
    }
    canon.assert_hashable(document)
    return document


def _add_param(ledger, fact_id, value, owner, param):
    """Record one effective parameter, keeping the form `run.json` gave it (K8)."""
    if value is None:
        # A nullable parameter that is switched off has no number to cite; an absent fact is the
        # honest record, and the gate then refuses a citation of it rather than accepting a zero
        # the run never used.
        return
    label = "%s 的生效参数 %s" % (owner, param)
    if isinstance(value, bool):
        ledger.add_text(fact_id, "true" if value else "false", label)
    elif isinstance(value, int):
        ledger.add_int(fact_id, value, label)
    elif isinstance(value, str):
        if _FIXED_RE.match(value):
            ledger.add(fact_id, value, KIND_FIXED, label)
        else:
            ledger.add_text(fact_id, value, label)
    else:
        raise ValueError("parameter %s carries a non-canonical value %r" % (fact_id, value))


def ledger_summary(document):
    """Counts for CLI lines: `(n_facts, n_numeric_facts, n_known_episodes)`."""
    facts = document["facts"]
    numeric = 0
    for entry in facts.values():
        if entry["kind"] != KIND_TEXT:
            numeric += 1
    return len(facts), numeric, len(document["catalog"]["episode_ids"])


def _iso_ms(iso_text):
    """Epoch milliseconds back out of the ISO form that anomalies.json carries.

    The ISO string was built *from* the integer, so this is a lossless read-back of the same
    quantity; facts.json stores the integer (K2) because ISO strings are the archive's display
    form, not the ledger's.
    """
    from .timebase import parse_iso_to_epoch_ms

    return parse_iso_to_epoch_ms(iso_text)
