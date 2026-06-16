"""月度复盘引擎：把"实盘绩效"变成可分析、可打分、可决策的三件事。

设计原则（见 CLAUDE.md 的分析框架）：把盈亏拆成 市场/选股/执行 三层，分开看。
  - 执行评分卡 execution_scorecard：对"调仓日推荐清单 vs 真实成交"打分（覆盖率/滑点/纪律）。
    打【过程】的分,不打盈亏的分——盈亏是市场发的,纪律才是你能控的。月度看。
  - 归因 attribution：这段收益从哪来——核心 vs AI 卫星、每只贡献、集中度、对基准超额。月度看。
  - 因子体检 factor_health：各因子滚动 rank-IC 全程 vs 近一年,只有【持续衰减】才提示调因子。季度看。

底层数据：实盘来自 portfolio_db（真实成交推导）；策略/基准来自 cs_pipeline 同一套口径。
"""

from __future__ import annotations

import pandas as pd

from quant_a.cache import cache_exists, load_cached_bars
from quant_a.cleaning import load_aligned_ohlcv
from quant_a.config import AI_SATELLITE_WEIGHT, CS_CORE_HOLDINGS, LOT_SIZE
from quant_a.cs_pipeline import HS300_PATH, _load_industry_map
from quant_a.factor_backtest import rebalance_dates
from quant_a.factor_strategy import compute_factor_panel
from quant_a.fundamentals import load_fundamental_factors, load_holder_factor
from quant_a.portfolio import (
    AI_CHAIN, AI_NAMES, ai_symbols, build_cs_buy_list, industry_label, select_ai_leaders, select_core,
)
from quant_a.portfolio_db import current_positions, get_cash_flows, get_trades
from quant_a.trade_rules import build_trade_eligibility

FORWARD_DAYS = 21  # 因子体检的前瞻持有期（约 1 个月交易日）


# ======================================================================
# 纯函数：打分 / 算贡献 / 算 IC —— 不碰 IO，单测就测这些
# ======================================================================
def grade_execution(coverage: float, abs_slippage: float, off_cycle: int, extra: int) -> str:
    """执行评分（过程分,非盈亏分）：覆盖率高、滑点小、不乱动、不买计划外 → A。

    coverage    : 推荐清单里实际买到的比例 [0,1]，越高越好
    abs_slippage: 成交价对清单价的平均绝对偏离（如 0.01=1%），越小越好
    off_cycle   : 非调仓日的成交笔数，越少越好（纪律）
    extra       : 买了但不在推荐清单里的只数，越少越好（乱买）
    """
    score = 100.0
    score -= (1.0 - coverage) * 80.0        # 漏单最伤：满漏扣 80（没按清单买是头号纪律问题）
    score -= min(abs_slippage / 0.005, 6) * 5.0  # 每 0.5% 滑点扣 5，最多 30
    score -= off_cycle * 8.0                # 每笔乱动扣 8
    score -= extra * 6.0                    # 每只计划外扣 6
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def position_contributions(positions: pd.DataFrame, price_now: dict[str, float], capital: float) -> pd.DataFrame:
    """每只持仓对总收益的贡献（占初始本金的百分点）。纯函数，给定持仓+现价+本金即可算。

    positions 需含 code/name/sleeve/shares/avg_cost；贡献 = 股数*(现价-成本)/本金。
    """
    rows: list[dict[str, object]] = []
    for _, p in positions.iterrows():
        cur = price_now.get(p["code"])
        if cur is None:
            continue
        cost = p["shares"] * p["avg_cost"]
        mv = p["shares"] * cur
        rows.append({
            "code": p["code"], "name": p["name"], "sleeve": p["sleeve"],
            "pnl": mv - cost,
            "contrib": (mv - cost) / capital if capital else 0.0,  # 对本金的贡献(百分点)
            "ret": (mv - cost) / cost if cost else 0.0,            # 自身涨跌幅
        })
    return pd.DataFrame(rows)


def rank_ic(factor: pd.Series, forward_return: pd.Series) -> float:
    """单期 rank-IC = 因子排名与未来收益排名的相关（Spearman）。对齐后非空≥5 只才算。"""
    df = pd.concat([factor, forward_return], axis=1).dropna()
    if len(df) < 5:
        return float("nan")
    return float(df.iloc[:, 0].rank().corr(df.iloc[:, 1].rank()))


# ======================================================================
# 数据加载（与 cs_pipeline 同口径；自包含，避免耦合）
# ======================================================================
def _load_context() -> dict[str, object]:
    if not HS300_PATH.exists():
        raise RuntimeError("缺少 data/hs300_mainboard.csv，请先生成沪深300主板清单并抓数")
    hs = pd.read_csv(HS300_PATH, dtype=str); hs["symbol"] = hs["symbol"].str.zfill(6)
    names = dict(zip(hs["symbol"], hs["name"].astype(str))); names.update(AI_NAMES)
    core_universe = {s for s in hs["symbol"] if cache_exists(s)}
    all_syms = sorted(core_universe | {c for c in ai_symbols() if cache_exists(c)})
    price = load_aligned_ohlcv(all_syms)
    close_m, high_m, low_m, vol_m = price["close"], price["high"], price["low"], price["volume"]
    candidate = build_trade_eligibility(
        close_matrix=close_m, high_matrix=high_m, low_matrix=low_m, volume_matrix=vol_m, stock_metadata=pd.DataFrame()
    )["candidate_mask"] & (close_m < 500.0)
    panel = compute_factor_panel(close_m, fundamentals=load_fundamental_factors(close_m))
    panel["holders"] = load_holder_factor(close_m)
    return {
        "close": close_m, "candidate": candidate, "panel": panel, "names": names,
        "core_universe": core_universe, "industry_map": _load_industry_map(),
    }


def _capital() -> float:
    flows = get_cash_flows()
    if flows.empty:
        return 0.0
    dep = flows[flows["type"] != "withdraw"]["amount"].sum()
    wd = flows[flows["type"] == "withdraw"]["amount"].sum()
    return float(dep - wd)


# ======================================================================
# 1) 归因
# ======================================================================
def attribution(ctx: dict[str, object] | None = None) -> dict[str, object]:
    """这段持有期收益从哪来：每只贡献、核心 vs AI 卫星、集中度、对基准超额。"""
    pos = current_positions()
    trades = get_trades()
    if pos.empty or trades.empty:
        return {"empty": True}
    ctx = ctx or _load_context()
    close = ctx["close"]
    cap = _capital() or float((pos["shares"] * pos["avg_cost"]).sum())

    start = trades["date"].min()
    start = close.index[close.index >= start][0]
    now = close.index[-1]
    price_now = {c: float(load_cached_bars(c).sort_values("date")["close"].iloc[-1]) for c in pos["code"] if cache_exists(c)}

    contrib = position_contributions(pos, price_now, cap)
    total_ret = float(contrib["contrib"].sum())
    by_sleeve = contrib.groupby("sleeve")["contrib"].sum().to_dict()

    gains = contrib[contrib["pnl"] > 0]["pnl"].sum()
    top = contrib.sort_values("pnl", ascending=False)
    top1 = float(top["pnl"].iloc[0] / gains) if gains > 0 else 0.0
    top3 = float(top["pnl"].head(3).sum() / gains) if gains > 0 else 0.0

    # 基准：起始日合格的核心股,等权买入持有到现在(同窗口、不选股)
    core_cols = [c for c in close.columns if c in ctx["core_universe"]]
    elig0 = ctx["candidate"].loc[start, core_cols]
    names0 = elig0[elig0].index
    bench_ret = float((close.loc[now, names0] / close.loc[start, names0] - 1).mean()) if len(names0) else 0.0

    return {
        "empty": False, "since": start.strftime("%Y-%m-%d"), "as_of": now.strftime("%Y-%m-%d"),
        "total_return": round(total_ret, 4), "benchmark_return": round(bench_ret, 4),
        "excess": round(total_ret - bench_ret, 4),
        "by_sleeve": {k: round(v, 4) for k, v in by_sleeve.items()},
        "top1_share_of_gains": round(top1, 4), "top3_share_of_gains": round(top3, 4),
        "holdings": [
            {"code": r["code"], "name": r["name"], "sleeve": r["sleeve"],
             "contrib": round(r["contrib"], 4), "ret": round(r["ret"], 4), "pnl": round(r["pnl"], 0)}
            for _, r in top.iterrows()
        ],
    }


# ======================================================================
# 2) 执行评分卡
# ======================================================================
def execution_scorecard(rebalance_date: str | None = None, ctx: dict[str, object] | None = None) -> dict[str, object]:
    """对照"调仓日策略推荐清单 vs 你的真实成交"打过程分：覆盖率 / 滑点 / 纪律。"""
    trades = get_trades()
    if trades.empty:
        return {"empty": True}
    ctx = ctx or _load_context()
    close, candidate, panel, names = ctx["close"], ctx["candidate"], ctx["panel"], ctx["names"]
    cap = _capital() or 100_000.0

    rb = pd.Timestamp(rebalance_date) if rebalance_date else trades["date"].min()
    rb = close.index[close.index >= rb][0]  # 吸附到交易日

    # 重新生成"当时该买什么"（点对点,无未来函数）
    aw, kc = AI_SATELLITE_WEIGHT, CS_CORE_HOLDINGS
    ai_budget = aw * cap / len(AI_CHAIN) if aw > 0 else 0.0
    ai = select_ai_leaders(rb, panel, candidate, price_row=close.loc[rb], budget_per_name=ai_budget)
    core = select_core(rb, panel, candidate, ctx["core_universe"], kc, names, exclude=set(ai.values()), industry_map=ctx["industry_map"])
    rec = build_cs_buy_list(rb, core, ai, close.loc[rb], cap, aw, names, LOT_SIZE)
    rec_price = dict(zip(rec["code"], rec["price"]))
    rec_codes = set(rec["code"])

    # 真实：调仓日当天（±3 交易日窗口内）的买入
    win_lo = close.index[max(0, close.index.get_loc(rb) - 3)]
    win_hi = close.index[min(len(close.index) - 1, close.index.get_loc(rb) + 3)]
    buys = trades[(trades["action"] == "buy") & (trades["date"] >= win_lo) & (trades["date"] <= win_hi)]
    bought = dict(zip(buys["code"], buys["price"]))
    bought_codes = set(bought)

    matched = rec_codes & bought_codes
    missing = sorted(rec_codes - bought_codes)   # 推荐了没买
    extra = sorted(bought_codes - rec_codes)     # 买了但不在推荐里
    coverage = len(matched) / len(rec_codes) if rec_codes else 0.0
    slips = [(bought[c] - rec_price[c]) / rec_price[c] for c in matched if rec_price.get(c)]
    avg_slip = float(pd.Series(slips).mean()) if slips else 0.0
    off_cycle = int(((trades["date"] < win_lo) | (trades["date"] > win_hi)).sum())  # 窗口外的成交=乱动
    grade = grade_execution(coverage, abs(avg_slip), off_cycle, len(extra))

    return {
        "empty": False, "rebalance_date": rb.strftime("%Y-%m-%d"),
        "grade": grade, "coverage": round(coverage, 4),
        "avg_slippage": round(avg_slip, 4), "off_cycle_trades": off_cycle,
        "recommended": len(rec_codes), "bought": len(bought_codes), "matched": len(matched),
        "missing": [names.get(c, c) for c in missing], "extra": [names.get(c, c) for c in extra],
    }


# ======================================================================
# 3) 因子体检
# ======================================================================
def factor_health(ctx: dict[str, object] | None = None, recent_months: int = 12) -> dict[str, object]:
    """各因子滚动 rank-IC：全程 vs 近 N 月。只有【持续衰减】才提示调因子（季度用）。"""
    ctx = ctx or _load_context()
    close, candidate, panel = ctx["close"], ctx["candidate"], ctx["panel"]
    reb = rebalance_dates(close.index)
    fwd = close.shift(-FORWARD_DAYS) / close - 1.0  # 未来约 1 月收益

    rows: list[dict[str, object]] = []
    for factor, mat in panel.items():
        series = []
        for d in reb:
            if d not in close.index:
                continue
            elig = candidate.loc[d]
            ic = rank_ic(mat.loc[d].where(elig), fwd.loc[d].where(elig))
            if pd.notna(ic):
                series.append((d, ic))
        if not series:
            continue
        s = pd.Series(dict(series)).sort_index()
        full = float(s.mean())
        recent = float(s.tail(recent_months).mean()) if len(s) >= 3 else float("nan")
        icir = float(s.mean() / s.std()) if s.std() else 0.0
        rows.append({
            "factor": factor, "ic_full": round(full, 4),
            "ic_recent": round(recent, 4) if pd.notna(recent) else None,
            "decay": round(recent - full, 4) if pd.notna(recent) else None,
            "ic_ir": round(icir, 3), "n": len(s),
        })
    rows.sort(key=lambda r: (r["ic_recent"] if r["ic_recent"] is not None else -9))
    return {"empty": not rows, "recent_months": recent_months, "factors": rows}
