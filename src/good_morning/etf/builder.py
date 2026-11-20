"""BTC 現物ETF の資金流出入のセクション

合計（全銘柄）と、config/etf.yaml の銘柄ごとの純流入を、同じ日付（確定している最新の日）で並べる。
銘柄によって確定の早さが違う（2026-11-20 9:30 に、GBTC・ARKB・BITB は 11/19 まで、IBIT・FBTC と
合計は 11/18 まで確定していた）ので、日付は合計の最新の確定日にそろえる。合計が取れなかったときは、
取れた銘柄がすべて確定している最新の日にそろえる。

そろえた日より新しい日に確定している銘柄の分も、捨てずに「11/19（一部）」として別に出す
（Farside の表で、まだ出ていない銘柄が空欄の行と同じ見せ方）。一部の銘柄だけなので、合計は作らない。

金額の表記: 純流入は百万ドル（小数1桁。Farside の US$m と同じ単位）、累計と純資産は億ドル（整数）。
ここでの割り算は単位をそろえる表示のためだけで、数値は取得元の値をそのまま使う（大原則1）。
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from good_morning.collector.sosovalue import (
    FlowDay,
    SoSoValueError,
    fetch_fund_history,
    fetch_summary_history,
    get_api_key,
)
from good_morning.context import RunContext, SectionContent
from good_morning.etf.config import EtfConfig, load_etf_config
from good_morning.timeutil import format_month_day

logger = logging.getLogger(__name__)

SOURCE = "SoSoValue（BTC 現物ETF の資金流出入）"
SETTLEMENT_NOTE = "米国の取引日ごとの値。翌営業日に確定するため、引けたばかりの日の分はまだ出ていない。"


@dataclass(frozen=True)
class FundFlow:
    ticker: str
    issuer: str
    day: FlowDay | None  # そろえた日付の確定した行（なければ None）
    failed: bool = False  # 取得に失敗した
    newer: dict[date, FlowDay] = field(default_factory=dict)  # そろえた日より新しい、確定した行


@dataclass(frozen=True)
class EtfFlows:
    basis_date: date  # そろえた日付
    recent: list[FlowDay]  # 合計の確定した日（古い順、recent_days 件まで）。合計が取れなければ空
    total: FlowDay | None  # 合計の basis_date の行
    funds: list[FundFlow]
    summary_failed: bool
    newer_dates: list[date] = field(default_factory=list)  # 一部の銘柄だけ確定している新しい日（古い順）


def short_day(d: date) -> str:
    """かっこの中に入れる日付（11/18）。曜日付きの 11/18（水） をかっこに入れると読みにくいので"""
    return f"{d.month}/{d.day}"


def flow_label(usd: float) -> str:
    """純流入（ドル）→ 百万ドルの表記（例 -306.4、+12.0、0.0）"""
    value = round(usd / 1e6, 1)
    return "0.0" if value == 0 else f"{value:+,.1f}"


def billions_label(usd: float, signed: bool = False) -> str:
    """累計・純資産（ドル）→ 億ドルの表記（例 777、+541）"""
    value = round(usd / 1e8)
    return f"{value:+,d}" if signed and value != 0 else f"{value:,d}"


def _settled(days: list[FlowDay]) -> list[FlowDay]:
    return [d for d in days if d.settled]


def assemble(
    summary: list[FlowDay] | None, funds: dict[str, list[FlowDay] | None], config: EtfConfig
) -> EtfFlows:
    """取得した行から、そろえた日付の表を作る。summary・funds の値が None なら取得失敗"""
    settled_summary = _settled(summary or [])
    if settled_summary:
        basis = max(d.date for d in settled_summary)
    else:
        latest = [max(d.date for d in _settled(days)) for days in funds.values() if days and _settled(days)]
        if not latest:
            raise SoSoValueError("確定した資金流出入のデータがありません")
        basis = min(latest)  # 取れた銘柄がすべて確定している最新の日

    recent = sorted((d for d in settled_summary if d.date <= basis), key=lambda d: d.date)
    total = next((d for d in settled_summary if d.date == basis), None)
    rows = []
    for fund in config.funds:
        days = funds.get(fund.ticker)
        settled = _settled(days or [])
        rows.append(
            FundFlow(
                ticker=fund.ticker,
                issuer=fund.issuer,
                day=next((d for d in settled if d.date == basis), None),
                failed=days is None,
                newer={d.date: d for d in settled if d.date > basis},
            )
        )
    return EtfFlows(
        basis_date=basis,
        recent=recent[-config.recent_days :],
        total=total,
        funds=rows,
        summary_failed=summary is None,
        newer_dates=sorted({d for f in rows for d in f.newer}),
    )


def collect(config: EtfConfig) -> tuple[EtfFlows, list[str]]:
    """合計と銘柄ごとに取得する。1つの失敗は、その部分だけ取得失敗にする"""
    api_key = get_api_key()  # キーがなければセクションごと取得失敗
    problems = []
    try:
        summary = fetch_summary_history(config.symbol, config.country_code, limit=10, api_key=api_key)
    except SoSoValueError as e:
        logger.warning("ETF の合計を取得できませんでした: %s", e)
        summary, problems = None, ["合計"]
    funds: dict[str, list[FlowDay] | None] = {}
    for fund in config.funds:
        try:
            funds[fund.ticker] = fetch_fund_history(fund.ticker, api_key=api_key)
        except SoSoValueError as e:
            logger.warning("ETF %s を取得できませんでした: %s", fund.ticker, e)
            funds[fund.ticker] = None
            problems.append(fund.ticker)
    if summary is None and all(v is None for v in funds.values()):
        raise SoSoValueError("合計・銘柄別とも取得できませんでした")
    return assemble(summary, funds, config), problems


def fund_cell(f: FundFlow) -> str:
    if f.failed:
        return "取得失敗"
    return flow_label(f.day.net_inflow) if f.day else "未確定"


def newer_cell(f: FundFlow, day: date) -> str:
    if f.failed:
        return "—"
    return flow_label(f.newer[day].net_inflow) if day in f.newer else "未確定"


def pending_tickers(flows: EtfFlows, day: date) -> list[str]:
    """新しい日にまだ確定していない銘柄（取得に失敗した銘柄は除く）"""
    return [f.ticker for f in flows.funds if not f.failed and day not in f.newer]


def newer_note(flows: EtfFlows, day: date) -> str:
    pending = pending_tickers(flows, day)
    rest = f"。未確定: {'・'.join(pending)}" if pending else ""
    return f"{short_day(day)} は確定した銘柄だけ（合計はまだ出ていない{rest}）"


def render_body(flows: EtfFlows, problems: list[str]) -> str:
    day = short_day(flows.basis_date)
    body = ["**合計（米国の BTC 現物ETF）**", ""]
    if flows.recent:
        body.extend(["| 日付 | 純流入（百万ドル） |", "|---|---:|"])
        body.extend(f"| {format_month_day(d.date)} | {flow_label(d.net_inflow)} |" for d in flows.recent)
        total = flows.total
        if total and total.cum_inflow is not None and total.net_assets is not None:
            cum = billions_label(total.cum_inflow, signed=True)
            assets = billions_label(total.net_assets)
            body.extend(["", f"累計の純流入 {cum}億ドル・純資産 {assets}億ドル（{day} 時点）"])
    else:
        body.append("取得失敗")
    if flows.funds:
        newer = flows.newer_dates
        head = ["銘柄", "運用会社", day, *(f"{short_day(d)}（一部）" for d in newer), f"純資産（億ドル・{day}）"]
        body.extend(["", "**銘柄別の純流入（百万ドル）**", ""])
        body.extend(["| " + " | ".join(head) + " |", "|---|---|" + "---:|" * (len(head) - 2)])
        for f in flows.funds:
            assets = billions_label(f.day.net_assets) if f.day and f.day.net_assets is not None else "—"
            cells = [f.ticker, f.issuer, fund_cell(f), *(newer_cell(f, d) for d in newer), assets]
            body.append("| " + " | ".join(cells) + " |")
        body.extend(["", *(newer_note(flows, d) for d in newer)] if newer else [])
    body.extend(["", SETTLEMENT_NOTE])
    if problems:
        body.append("")
        body.append(f"⚠ 取得できませんでした（理由はログを参照）: {'、'.join(problems)}")
    return "\n".join(body)


def build_btc_etf(ctx: RunContext) -> SectionContent:
    config = load_etf_config()
    flows, problems = collect(config)
    ctx.data["btc_etf"] = flows
    day = format_month_day(flows.basis_date)
    return SectionContent(
        body=render_body(flows, problems),
        basis=[f"BTC 現物ETF の資金流出入: {day} の確定値（米国の取引日ごと。翌営業日に確定）"],
        sources=[SOURCE],
    )
