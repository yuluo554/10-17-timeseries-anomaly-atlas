"""M5 report-gate tests: extraction, all-misses-listed, the episode and row gates, the CLI codes.

The gate is only worth its green tick if it is falsifiable in both directions: a narrative made of
citations must pass, and every invented thing must be refused *and named*. Each negative case here
injects one specific defect and asserts that the gate reports exactly that defect.
"""

import json
import types

import pytest

from anomaly_atlas import canon, cli, csvio, detect, facts, layout, profile, report

from conftest import SERIES_CSV, read_text


@pytest.fixture(scope="module")
def ledger():
    """The default-spec ledger of the frozen fixture (same construction as `detect`)."""
    parsed = csvio.load_series(SERIES_CSV)
    run_document, anomaly_set, detections = detect.detect_all_detailed(
        parsed, detect.resolve_spec()
    )
    document = facts.build_facts(
        run_document,
        anomaly_set,
        profile_document=profile.build_profile(parsed),
        rows_by_series=parsed.rows_by_series,
        heat_bin_ms=layout.DEFAULT_HEAT_BIN_MS,
    )
    return types.SimpleNamespace(
        parsed=parsed,
        run_document=run_document,
        anomaly_set=anomaly_set,
        detections=detections,
        document=document,
        facts=document["facts"],
        catalog=document["catalog"],
    )


@pytest.fixture
def truth_file(tmp_path):
    """Write a narrative and return its path (as a string) plus the ledger path."""

    def _write(ledger, text, name="narrative.txt"):
        path = tmp_path / name
        path.write_bytes(text.encode("utf-8"))
        return str(path)

    return _write


def _tokens(text):
    return [(token["form"], token["token"]) for token in report.extract_numbers(text)]


class TestExtraction:
    def test_arabic_forms_are_all_caught(self):
        forms = dict((token, form) for form, token in _tokens(
            "12 段；1,234 个点；3.5 倍；1e3 次；42.34% 覆盖；0.5 分"
        ))
        assert forms["12"] == "number"
        assert forms["1,234"] == "number"
        assert forms["3.5"] == "number"
        assert forms["1e3"] == "number"
        assert forms["42.34%"] == "percent"
        assert forms["0.5"] == "number"

    def test_full_width_percent_is_a_percent_too(self):
        assert _tokens("覆盖率 42.34％") == [("percent", "42.34％")]

    def test_chinese_numerals_need_a_quantifier(self):
        assert [token[1] for token in _tokens("三处缺口、十五条规则、两段零值")] == [
            "三处",
            "十五条",
            "两段",
        ]

    def test_ordinary_words_are_not_numbers(self):
        # The reason the quantifier is required: these words are not measurements, and a gate that
        # flagged them would be switched off by its first user. ("唯一的一段" is deliberately *not*
        # in this list: the quantifier reads, and `一段` is one segment -- a true reading, kept.)
        for text in ("统一口径", "一般情形", "同一 series", "十分明显", "万一出现"):
            assert [token["token"] for token in report.extract_numbers(text)] == [], text

    def test_chinese_values_are_parsed_not_guessed(self):
        assert report.extract_numbers("三处缺口")[0]["chinese_value"] == 3
        assert report.extract_numbers("二十个点")[0]["chinese_value"] == 20
        assert report.extract_numbers("一百零五次")[0]["chinese_value"] == 105

    def test_identifiers_and_ids_are_not_read_as_numbers(self):
        # `energy_kwh-E003` is an episode reference, not a number: the digit run sits inside an
        # identifier, which the boundary rule refuses.
        assert report.extract_numbers("energy_kwh-E003 与 v3 与 x2") == []

    def test_row_references_are_masked_out_of_the_number_scan(self):
        assert report.extract_numbers("见 row 13 与第 1943 行") == []
        refs = report.extract_row_refs("见 row 13 与第 1943 行")
        assert [(ref["token"], ref["row_no"]) for ref in refs] == [("row 13", 13), ("第 1943 行", 1943)]

    def test_labelled_physical_lines_are_exempt_from_both_gates(self):
        text = "CSV 行 500 与文件行 12 是解析层面的引用"
        assert report.extract_numbers(text) == []
        assert report.extract_row_refs(text) == []

    def test_iso_timestamps_are_read_into_epoch_milliseconds(self):
        tokens = report.extract_numbers("起于 2024-03-02T07:00:00.000Z。")
        assert len(tokens) == 1
        assert tokens[0]["form"] == "iso"
        assert tokens[0]["epoch_ms"] == 1709362800000
        assert tokens[0]["value_q"] == 1709362800000 * 1000000

    def test_an_unreadable_calendar_date_is_a_miss_rather_than_a_crash(self):
        tokens = report.extract_numbers("2024-02-30T00:00:00.000Z 不是一个存在的日期")
        assert tokens[0]["form"] == "iso"
        assert tokens[0]["value_q"] is None

    def test_context_keeps_the_neighbourhood_of_a_token(self):
        token = report.extract_numbers("全档案共 178 段异常")[0]
        assert token["token"] == "178"
        assert "共 178 段异常" in token["context"]


class TestGateAcceptsCitations:
    def test_a_narrative_made_of_citations_passes(self, ledger):
        text = (
            "共 178 段 Episode、653 个异常点，覆盖 3 个 series；共 2,960 行、3 处缺口。"
            "最严重的一段是 humidity-E001（rolling_mad_z）：row 1943 到 row 1967，"
            "持续 2400000 毫秒，峰值得分 729.714690，起于 2024-03-02T07:00:00.000Z；"
            "窗口 24 点、k 为 3.500000。CSV 行 500 属于解析层面。"
        )
        assert report.check_report(text, ledger.document) == []

    def test_a_percent_token_may_cite_the_underlying_ratio(self, ledger):
        # 5.5556% of a bin's valid points is the same measurement as a coverage ratio of 0.055556.
        # The assertion is "no miss at all": checking the violation *tokens* for a fact id would be an
        # assertion that cannot fail (tokens carry the written text, never a fact id).
        assert report.check_report("覆盖度 5.5556%", ledger.document) == []
        # ...and the allowance belongs to the percent form: written without the sign, the same digits
        # must hit a fact of their own value (0.055556 is not 5.5556), which is the documented rule.
        assert report.check_report("覆盖度 5.5556", ledger.document) != []

    def test_a_chinese_quantified_number_is_checked_like_any_other(self, ledger):
        # `three` is not a fact of this archive (its counts are 178 / 653 / 3 bins of gaps...), so a
        # narrative claiming it must be refused: the Chinese path is not a loophole.
        violations = report.check_report("共三万处缺口", ledger.document)
        assert [violation["token"] for violation in violations] == ["三万处"]


class TestGateRefusesInventions:
    def test_an_invented_count_is_refused_and_names_the_closest_fact(self, ledger):
        violations = report.check_report("共 987654321 段异常", ledger.document)
        assert len(violations) == 1
        assert violations[0]["kind"] == "number"
        assert violations[0]["token"] == "987654321"
        # The hint is the arithmetic nearest fact, recomputed here from the index so the rule itself
        # is pinned rather than one coincidental answer.
        index = facts.numeric_index(ledger.document)
        scaled = facts.scaled_value(
            {"kind": facts.KIND_INT, "value": 987654321},
            ledger.document["quant_decimals"],
        )
        nearest = min(index, key=lambda candidate: abs(candidate - scaled))
        assert violations[0]["closest"]["fact_id"] == index[nearest][0]
        assert violations[0]["closest"]["fact_id"] in ledger.facts

    def test_an_invented_episode_is_refused(self, ledger):
        violations = report.check_report("nonesuch-E777 是一段异常", ledger.document)
        assert [violation["kind"] for violation in violations] == ["episode"]
        assert violations[0]["token"] == "nonesuch-E777"

    def test_an_episode_of_a_real_series_but_a_nonexistent_number_is_still_refused(self, ledger):
        violations = report.check_report("humidity-E999 是一段异常", ledger.document)
        assert [violation["kind"] for violation in violations] == ["episode"]

    def test_an_invented_row_is_refused(self, ledger):
        violations = report.check_report("异常出现在 row 987654321", ledger.document)
        assert [violation["kind"] for violation in violations] == ["row"]
        assert violations[0]["row_no"] == 987654321

    def test_every_miss_is_listed_not_just_the_first(self, ledger):
        # Reporting only the first miss would let a fabricated number hide behind another one.
        text = "共 987654321 段异常，nonesuch-E777 在其中，另见 row 987654321。"
        violations = report.check_report(text, ledger.document)
        assert sorted(violation["kind"] for violation in violations) == [
            "episode",
            "number",
            "row",
        ]

    def test_an_unreadable_iso_date_is_refused(self, ledger):
        violations = report.check_report("起于 2024-02-30T00:00:00.000Z", ledger.document)
        assert [violation["kind"] for violation in violations] == ["number"]
        # Nothing to point at: the token never got a value, so there is no nearest fact to name.
        assert violations[0]["closest"] is None
        assert violations[0]["unreadable"]

    def test_an_iso_timestamp_that_is_not_a_real_boundary_is_refused(self, ledger):
        violations = report.check_report("起于 2024-03-02T07:30:00.000Z", ledger.document)
        assert [violation["token"] for violation in violations] == ["2024-03-02T07:30:00.000Z"]


class TestAuditAndRendering:
    def test_audit_reports_tokens_and_violations_together(self, ledger):
        result = report.audit("共 178 段、nonesuch-E777、row 1943", ledger.document)
        assert report.gate_summary(result).startswith("1 number(s), 1 episode reference(s)")
        assert [violation["kind"] for violation in result["violations"]] == ["episode"]

    def test_render_violations_prints_one_line_per_miss_with_context(self, ledger, capsys):
        violations = report.check_report(
            "共 987654321 段异常，nonesuch-E777 也在。", ledger.document
        )
        count = report.render_violations(violations, __import__("sys").stdout)
        out = capsys.readouterr().out
        assert count == 2
        assert out.count("MISS[") == 2
        assert "987654321" in out and "nonesuch-E777" in out
        assert "closest=" in out
        assert "closest=none" in out
        assert "context=" in out


class TestCheckReportCli:
    def _write_ledger(self, tmp_path, ledger):
        path = tmp_path / "facts.json"
        path.write_bytes(canon.canonical_json_bytes(ledger.document))
        return str(path)

    def test_a_clean_narrative_exits_zero(self, ledger, tmp_path, truth_file, capsys):
        facts_path = self._write_ledger(tmp_path, ledger)
        text_path = truth_file(ledger, "共 178 段异常。")
        assert cli.main(["check-report", "--facts", facts_path, "--text", text_path]) == cli.EXIT_OK
        assert "OK" in capsys.readouterr().out

    def test_a_fabricated_number_exits_one_and_lists_it(self, ledger, tmp_path, truth_file, capsys):
        facts_path = self._write_ledger(tmp_path, ledger)
        text_path = truth_file(ledger, "共 987654321 段异常。")
        code = cli.main(["check-report", "--facts", facts_path, "--text", text_path])
        assert code == cli.EXIT_FAIL
        out = capsys.readouterr().out
        assert "report NOT generated" in out
        assert "987654321" in out

    def test_a_missing_narrative_file_is_a_usage_error(self, ledger, tmp_path):
        facts_path = self._write_ledger(tmp_path, ledger)
        missing = str(tmp_path / "nope.txt")
        assert cli.main(["check-report", "--facts", facts_path, "--text", missing]) == cli.EXIT_USAGE

    def test_a_malformed_ledger_is_a_usage_error(self, ledger, tmp_path, truth_file):
        bad = tmp_path / "facts.json"
        bad.write_text("{not json", encoding="utf-8")
        text_path = truth_file(ledger, "共 178 段异常。")
        assert cli.main(["check-report", "--facts", str(bad), "--text", text_path]) == cli.EXIT_USAGE

    def test_a_json_document_that_is_not_a_ledger_is_a_usage_error(
        self, ledger, tmp_path, truth_file, capsys
    ):
        wrong = tmp_path / "facts.json"
        wrong.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        text_path = truth_file(ledger, "共 178 段异常。")
        assert cli.main(["check-report", "--facts", str(wrong), "--text", text_path]) == cli.EXIT_USAGE
        assert "missing key" in capsys.readouterr().err

    def test_a_ledger_without_a_catalog_is_a_usage_error(self, ledger, tmp_path, truth_file, capsys):
        # The catalog is what the episode and row gates resolve against. A ledger missing it would
        # leave those gates with nothing to accept (fail-closed, but a *silent* one), so its absence
        # is a usage error rather than something the gate quietly works around.
        document = dict(ledger.document)
        document.pop("catalog")
        path = tmp_path / "facts-no-catalog.json"
        path.write_bytes(canon.canonical_json_bytes(document))
        text_path = truth_file(ledger, "共 178 段异常。")
        assert cli.main(["check-report", "--facts", str(path), "--text", text_path]) == cli.EXIT_USAGE
        assert "missing key" in capsys.readouterr().err

    def test_the_gate_never_writes_anything(self, ledger, tmp_path, truth_file):        # `check-report` is a gate: it reads, it judges, it prints. A file appearing next to its
        # inputs would be a side effect nobody asked for.
        facts_path = self._write_ledger(tmp_path, ledger)
        text_path = truth_file(ledger, "共 987654321 段异常。")
        before = sorted(path.name for path in tmp_path.iterdir())
        cli.main(["check-report", "--facts", facts_path, "--text", text_path])
        assert sorted(path.name for path in tmp_path.iterdir()) == before

    def test_the_repository_ledger_is_usable_by_the_cli(self, tmp_path, capsys):
        # End to end from the CLI as a user would run it: `detect` writes the ledger, `check-report`
        # gates a narrative against it.
        out_dir = tmp_path / "out"
        assert cli.main(["detect", SERIES_CSV, "--out-dir", str(out_dir)]) == cli.EXIT_OK
        narrative = tmp_path / "n.txt"
        narrative.write_text("共 178 段异常、653 个异常点。", encoding="utf-8")
        code = cli.main(
            [
                "check-report",
                "--facts",
                str(out_dir / "facts.json"),
                "--text",
                str(narrative),
            ]
        )
        assert code == cli.EXIT_OK
        assert "OK" in capsys.readouterr().out
