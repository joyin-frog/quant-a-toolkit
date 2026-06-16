"""核心-卫星组合：分散的多因子核心 + AI 产业链龙头卫星。

- 核心（默认 ~85%）：沪深300主板多因子（含缓冲带），加【行业上限】避免扎堆（银行不超过 N 只）。
- AI 卫星（默认 15%）：用户坚定看好的 AI 产业链，每条子链选 1 只龙头（按动量），分散覆盖整条链。
  只用主板（用户无创业板/科创板权限）。卫星是【信仰仓/主动赌注】，不是回测验证的 alpha——
  AI 龙头池是按当下认知挑的，回测含幸存者偏差，实盘会打折，务必控制比例。

行业分类：优先用 data/industry_map.csv（东财行业，可能因接口不稳而缺失）；缺失时用名称兜底
识别金融三类（银行/保险/证券）——这恰好覆盖沪深300上最严重的"全是银行"扎堆问题。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_a.config import (
    AI_SATELLITE_WEIGHT,
    COMMISSION,
    CORE_MAX_PER_SECTOR,
    CS_CORE_HOLDINGS,
    FACTOR_CAPITAL,
    FACTOR_SELL_RANK,
    FACTOR_WEIGHTS,
    LOT_SIZE,
    SLIPPAGE,
)
from quant_a.factor_strategy import compute_factor_panel, factor_scores_on

# 主板 AI 产业链龙头池（排除创业板 300/科创板 688），按子链分组。可按需增减。
AI_CHAIN: dict[str, list[str]] = {
    "光通信": ["600487", "600522", "002281", "603083", "000988"],
    "半导体芯片": ["603501", "002371", "600703", "002156", "600584", "603986", "600745", "600460", "002049"],
    "消费电子": ["002475", "002241", "000725", "000100", "002008", "002273"],
    "算力服务器": ["000977", "603019", "000938", "601138", "000034", "002261"],
    "PCB": ["002463", "002916", "002938", "603228", "600183"],
    "铜箔": ["600110", "000630"],
    "玻纤电子布": ["600176", "603256"],
    "电力": ["600900", "600406", "600011", "600886", "600674", "600642"],
}
AI_NAMES: dict[str, str] = {
    "600487": "亨通光电", "600522": "中天科技", "002281": "光迅科技", "603083": "剑桥科技", "000988": "华工科技",
    "603501": "韦尔股份", "002371": "北方华创", "600703": "三安光电", "002156": "通富微电", "600584": "长电科技",
    "603986": "兆易创新", "600745": "闻泰科技", "600460": "士兰微", "002049": "紫光国微", "002475": "立讯精密",
    "002241": "歌尔股份", "000725": "京东方A", "000100": "TCL科技", "002008": "大族激光", "002273": "水晶光电",
    "000977": "浪潮信息", "603019": "中科曙光", "000938": "紫光股份", "601138": "工业富联", "000034": "神州数码",
    "002261": "拓维信息", "002463": "沪电股份", "002916": "深南电路", "002938": "鹏鼎控股", "603228": "景旺电子",
    "600183": "生益科技", "600110": "诺德股份", "000630": "铜陵有色", "600176": "中国巨石", "603256": "宏和科技",
    "600900": "长江电力", "600406": "国电南瑞", "600011": "华能国际", "600886": "国投电力", "600674": "川投能源",
    "600642": "申能股份",
}
_INSURER_CODES = {"601318", "601601", "601628", "601336", "601319"}


def ai_symbols() -> list[str]:
    return [code for codes in AI_CHAIN.values() for code in codes]


def industry_label(symbol: str, names: dict[str, str], industry_map: dict[str, str] | None = None) -> str:
    """行业标签。industry_map 优先；否则名称兜底识别金融三类；其余按自身代码（不限制）。"""
    if industry_map:
        label = industry_map.get(symbol)
        if isinstance(label, str) and label:
            return label
    name = names.get(symbol, "")
    if "银行" in name:
        return "银行"
    if symbol in _INSURER_CODES or "保险" in name:
        return "保险"
    if "证券" in name:
        return "证券"
    return "X" + symbol  # 无法归类 → 视为独立行业，不参与上限约束


def select_ai_leaders(
    date: pd.Timestamp,
    panel: dict[str, pd.DataFrame],
    candidate_mask: pd.DataFrame,
    price_row: pd.Series | None = None,
    budget_per_name: float | None = None,
    lot: int = LOT_SIZE,
) -> dict[str, str]:
    """每条 AI 子链选 1 只龙头：合格、动量最强、且【买得起】的那只。返回 {子链: 代码}。

    20 万本金下 AI 卫星每只预算很小（15%/8条≈3750元），北方华创/韦尔这类高价龙头 1 手就要几万、
    根本买不起。所以给了 budget_per_name 时，只在"1 手 ≤ 预算"的票里挑动量最强的——
    保证回测和清单都是 20 万真能执行的（半导体会落到三安/通富这种买得起的龙头，而非买不起的北方华创）。
    """
    momentum = panel["mom"]
    leaders: dict[str, str] = {}
    for theme, codes in AI_CHAIN.items():
        eligible = [
            c for c in codes
            if c in candidate_mask.columns and bool(candidate_mask.loc[date, c]) and pd.notna(momentum.loc[date, c])
        ]
        if budget_per_name is not None and price_row is not None:
            eligible = [
                c for c in eligible
                if pd.notna(price_row.get(c)) and float(price_row.get(c)) * lot <= budget_per_name
            ]
        if eligible:
            leaders[theme] = max(eligible, key=lambda c: momentum.loc[date, c])
    return leaders


def select_core(
    date: pd.Timestamp,
    panel: dict[str, pd.DataFrame],
    candidate_mask: pd.DataFrame,
    core_universe: set[str],
    holdings: int,
    names: dict[str, str],
    current_holdings: list[str] | None = None,
    exclude: set[str] | None = None,
    max_per_sector: int | None = None,
    sell_rank: int | None = None,
    industry_map: dict[str, str] | None = None,
    weights: dict[str, float] | None = None,
) -> list[str]:
    """核心选股：多因子排名 + 缓冲带 + 行业上限，只在 core_universe 里、排除 exclude（已在卫星里的票）。"""
    cap = max_per_sector or CORE_MAX_PER_SECTOR
    sell = sell_rank or FACTOR_SELL_RANK
    exclude = exclude or set()
    current_holdings = current_holdings or []
    scored = factor_scores_on(date, panel, candidate_mask, weights or FACTOR_WEIGHTS)
    scored = scored[[s in core_universe and s not in exclude for s in scored.index]]
    position = {s: i + 1 for i, s in enumerate(scored.index)}

    sector_count: dict[str, int] = {}
    chosen: list[str] = []

    def try_add(symbol: str) -> None:
        sector = industry_label(symbol, names, industry_map)
        if len(chosen) < holdings and sector_count.get(sector, 0) < cap:
            chosen.append(symbol)
            sector_count[sector] = sector_count.get(sector, 0) + 1

    # 1) 缓冲：已持有且排名仍在前 sell_rank 内的，优先保留（受行业上限约束）
    for symbol in sorted([h for h in current_holdings if position.get(h, 10**9) <= sell], key=lambda s: position[s]):
        try_add(symbol)
    # 2) 按排名补满，受行业上限约束
    for symbol in scored.index:
        if len(chosen) >= holdings:
            break
        if symbol not in chosen:
            try_add(symbol)
    return chosen


def _budget_to_shares(budget: dict[str, float], price: pd.Series, columns: pd.Index, lot: int) -> pd.Series:
    target = pd.Series(0.0, index=columns)
    for symbol, money in budget.items():
        unit = price.get(symbol, np.nan)
        if pd.notna(unit) and unit > 0:
            target[symbol] = int(money // (unit * lot)) * lot
    return target


def run_core_satellite_backtest(
    close_matrix: pd.DataFrame,
    candidate_mask: pd.DataFrame,
    core_universe: set[str],
    names: dict[str, str],
    panel: dict[str, pd.DataFrame] | None = None,
    capital: float | None = None,
    core_holdings: int | None = None,
    ai_weight: float | None = None,
    max_per_sector: int | None = None,
    sell_rank: int | None = None,
    industry_map: dict[str, str] | None = None,
    lot_size: int | None = None,
    cost: float | None = None,
) -> dict[str, object]:
    """固定本金 + 100 股整手的核心-卫星回测。"""
    from quant_a.factor_backtest import rebalance_dates

    cap = capital if capital is not None else FACTOR_CAPITAL
    kc = core_holdings or CS_CORE_HOLDINGS
    aw = ai_weight if ai_weight is not None else AI_SATELLITE_WEIGHT
    lot = lot_size or LOT_SIZE
    fee = cost if cost is not None else (COMMISSION + SLIPPAGE)
    panel = panel or compute_factor_panel(close_matrix)
    close_val = close_matrix.ffill()
    rebal = set(rebalance_dates(close_matrix.index))

    cash = float(cap)
    shares = pd.Series(0.0, index=close_matrix.columns)
    records: list[dict[str, object]] = []
    for current_date in close_matrix.index:
        price = close_val.loc[current_date]
        if current_date in rebal:
            equity = cash + float((shares * price.fillna(0.0)).sum())
            held = [s for s in shares.index if shares[s] > 0]
            ai_budget = aw * equity / len(AI_CHAIN) if aw > 0 else 0.0
            ai = list(select_ai_leaders(current_date, panel, candidate_mask, price_row=price, budget_per_name=ai_budget).values())
            core = select_core(
                current_date, panel, candidate_mask, core_universe, kc, names,
                current_holdings=held, exclude=set(ai), max_per_sector=max_per_sector,
                sell_rank=sell_rank, industry_map=industry_map,
            )
            budget: dict[str, float] = {}
            if core:
                for s in core:
                    budget[s] = (1.0 - aw) * equity / len(core)
            if ai:
                for s in ai:
                    budget[s] = budget.get(s, 0.0) + aw * equity / len(ai)
            target = _budget_to_shares(budget, price, close_matrix.columns, lot)
            delta = target - shares
            cash -= float((delta * price.fillna(0.0)).sum())
            cash -= float((delta.abs() * price.fillna(0.0)).sum()) * fee
            shares = target
        equity = cash + float((shares * price.fillna(0.0)).sum())
        records.append({"date": current_date, "equity": equity, "cash": cash, "n_holdings": int((shares > 0).sum())})

    frame = pd.DataFrame(records).set_index("date")
    equity_curve = frame["equity"] / cap
    returns = equity_curve.pct_change(fill_method=None).fillna(0.0)
    return {
        "equity_curve": equity_curve,
        "returns": returns,
        "equity_value": frame["equity"],
        "cash": frame["cash"],
        "n_holdings": frame["n_holdings"],
        "final_shares": shares,
    }


def build_cs_buy_list(
    date: pd.Timestamp,
    core: list[str],
    ai: dict[str, str],
    price_row: pd.Series,
    capital: float,
    ai_weight: float,
    names: dict[str, str],
    lot: int = LOT_SIZE,
) -> pd.DataFrame:
    """全现金建仓的核心-卫星下单清单。"""
    rows: list[dict[str, object]] = []
    spent = 0.0
    core_budget = (1.0 - ai_weight) * capital / len(core) if core else 0.0
    ai_budget = ai_weight * capital / len(ai) if ai else 0.0
    plan = [("核心", s, core_budget, "") for s in core] + [("AI卫星", c, ai_budget, t) for t, c in ai.items()]
    for sleeve, symbol, money, theme in plan:
        unit = float(price_row.get(symbol, np.nan))
        if not np.isfinite(unit) or unit <= 0:
            continue
        lots = int(money // (unit * lot))
        if lots <= 0:
            continue
        cost = lots * lot * unit
        spent += cost
        rows.append({
            "date": date.date(), "sleeve": sleeve, "theme": theme, "code": symbol,
            "name": names.get(symbol, ""), "price": round(unit, 2), "lots": lots,
            "cost": round(cost, 0), "weight": round(cost / capital, 4),
        })
    table = pd.DataFrame(rows)
    table.attrs["invested"] = round(spent, 0)
    table.attrs["cash_left"] = round(capital - spent, 0)
    return table
