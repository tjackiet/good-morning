"""レポートの骨子（good_morning.sections / good_morning.reporter.markdown）のテスト"""

import logging
from datetime import UTC, datetime

from good_morning.reporter.markdown import (
    DISCLAIMER,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_PENDING,
    ReportMeta,
    format_report_date,
    render_report,
    report_filename,
    save_report,
)
from good_morning.sections import (
    SECTION_SPECS,
    RunContext,
    SectionContent,
    SectionSpec,
    build_section,
    build_sections,
)
from good_morning.timeutil import JST, format_jst

# 2026-11-16 22:30 UTC = 2026-11-17 07:30 JST（火）
NOW = datetime(2026, 11, 16, 22, 30, tzinfo=UTC).astimezone(JST)


def _ctx():
    return RunContext(now=NOW)


def test_section_order_follows_spec():
    """指示書「5. レポートの骨子」の並び順"""
    assert [s.title for s in SECTION_SPECS] == [
        "今朝のまとめ",
        "マーケット一覧",
        "セクター別騰落率",
        "BTCの詳細",
        "BTC 現物ETF の資金流出入",
        "暗号資産の需給",
        "暗号資産ウォッチリスト",
        "株式ウォッチリスト",
        "今後の予定",
        "主要ニュース",
        "暗号資産への示唆",
    ]


def test_build_section_without_builder_is_pending():
    section = build_section(SectionSpec("x", "未着手", phase=3), _ctx())

    assert section.status == STATUS_PENDING
    assert section.note == "フェーズ3で実装予定"


def test_build_section_isolates_failure_and_logs(caplog):
    """builder が例外を投げても止めず、取得失敗として返し、理由をログに残す"""

    def broken(ctx):
        raise RuntimeError("upstream timeout")

    def ok(ctx):
        return SectionContent(body="| a |", basis=["基準A"], sources=["yfinance"])

    specs = [SectionSpec("bad", "壊れた欄", 1, broken), SectionSpec("good", "正常な欄", 1, ok)]

    with caplog.at_level(logging.ERROR):
        sections = build_sections(_ctx(), specs)

    assert [s.status for s in sections] == [STATUS_FAILED, STATUS_OK]
    assert "upstream timeout" in caplog.text
    assert "壊れた欄" in caplog.text


def test_render_report_layout():
    def ok(ctx):
        return SectionContent(body="本文", basis=["米国株: NY終値"], sources=["yfinance"])

    def broken(ctx):
        raise ValueError("boom")

    specs = [
        SectionSpec("a", "正常な欄", 1, ok),
        SectionSpec("b", "壊れた欄", 1, broken),
        SectionSpec("c", "未着手の欄", 4),
        SectionSpec("d", "同じ基準の欄", 1, ok),
    ]
    sections = build_sections(_ctx(), specs)
    meta = ReportMeta(generated_at=NOW, notices=["見本の銘柄で作成"])

    report = render_report(sections, meta)

    assert report.startswith("# モーニングレター 2026年11月17日（火）\n")
    assert "- 生成時刻: 2026-11-17 07:30 JST" in report
    assert "  - 米国株: NY終値" in report
    assert "- ⚠ 見本の銘柄で作成" in report
    assert "## 正常な欄\n\n本文\n" in report
    assert "## 壊れた欄\n\n> 取得失敗（理由はログを参照）\n" in report
    assert "## 未着手の欄\n\n> 未実装（フェーズ4で実装予定）\n" in report
    assert DISCLAIMER in report
    assert "データ出典: yfinance" in report
    # 同じ基準の行は1回だけ出す
    assert report.count("米国株: NY終値") == 1
    # セクションの順序が保たれる
    assert report.index("## 正常な欄") < report.index("## 壊れた欄") < report.index("## 未着手の欄")


def test_header_omits_basis_when_no_section_provides_it():
    specs = [SectionSpec("x", "未着手", phase=9)]
    report = render_report(build_sections(_ctx(), specs), ReportMeta(generated_at=NOW))

    assert "データ基準時刻" not in report
    assert "データ出典" not in report


def test_dates_are_jst():
    """UTC の日付をまたぐ時刻でも、表示とファイル名は JST の日付になる"""
    utc_dt = datetime(2026, 11, 16, 22, 30, tzinfo=UTC)

    assert format_report_date(utc_dt) == "2026年11月17日（火）"
    assert report_filename(utc_dt) == "2026-11-17.md"
    assert format_jst(utc_dt) == "2026-11-17 07:30 JST"


def test_save_report_writes_dated_file(tmp_path):
    path = save_report("# test\n", NOW, output_dir=tmp_path / "outputs")

    assert path == tmp_path / "outputs" / "2026-11-17.md"
    assert path.read_text(encoding="utf-8") == "# test\n"
