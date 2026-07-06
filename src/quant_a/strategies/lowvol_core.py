"""低波长线（沪深300主板核心）：5 因子（低波动主导）+ 缓冲带 + 行业上限，月度调仓。

= 核心-卫星去掉 AI 卫星（ai_weight=0）。AI 敞口独立成 ai_leader（AI+机器人）策略，
两条线各自记账，杠铃结构由用户在账户层组合。

迁移模式（account 参数）：从记账账户的现有持仓出发生成 卖出/保留/买入 过渡清单；
locked 锁仓的票无条件保留（占名额、计入行业上限）——支持"我就是不卖中航沈飞"。
"""

from __future__ import annotations

import pandas as pd

from quant_a.cache import cache_exists
from quant_a.cleaning import load_aligned_ohlcv
from quant_a.config import CORE_MAX_PER_SECTOR
from quant_a.cs_pipeline import HS300_PATH
from quant_a.factor_strategy import compute_factor_panel
from quant_a.platform.contracts import StrategyResult
from quant_a.portfolio import select_core
from quant_a.trade_rules import build_trade_eligibility
from quant_a.transition import account_stock_positions, build_transition


def _industry_map() -> dict[str, str]:
    from quant_a.cs_pipeline import _load_industry_map

    return _load_industry_map()


def run_lowvol_core(
    capital: float = 200_000,
    holdings: int = 17,
    account: str = "",
    locked: str = "",
) -> StrategyResult:
    from quant_a.cs_pipeline import run_cs_pipeline

    raw = run_cs_pipeline(capital=capital, core_holdings=holdings, ai_weight=0.0)
    result = StrategyResult(
        strategy_id="core_satellite",  # 保留旧 id：记账账户/报告目录的连续性
        name="低波长线（沪深300核心）",
        params={"capital": capital, "holdings": holdings, **({"account": account} if account else {}), **({"locked": locked} if locked else {})},
        date_range=raw["date_range"],
        metrics=raw["metrics"],
        benchmark_metrics=raw["benchmark_metrics"],
        equity_curve=raw["equity_curve"],
        benchmark_curve=raw["benchmark_curve"],
        holdings=raw["buy_list"],
        artifacts={"orders": raw["order_path"], "chart": raw["chart"]},
        diagnostics={
            "avg_cash_pct": raw["avg_cash_pct"],
            "rolling12m": raw["rolling12m"],
            "core_sectors": raw["core_sectors"],
        },
    )

    if account:
        locked_codes = [c.strip().zfill(6) for c in locked.split(",") if c.strip()]
        transition = _build_account_transition(account, holdings, locked_codes)
        result.diagnostics["transition"] = transition["summary"]
        result.diagnostics["transition_orders"] = transition["orders"].to_dict(orient="records")
        result.warnings.extend(transition["summary"]["warnings"])
        if holdings <= 8:
            result.warnings.append(
                f"目标 {holdings} 只属于高集中度：因子的统计优势在 17-30 只时才充分，"
                "6 只口径下应视为『因子圈出的纪律化短名单』而非验证过的组合收益。"
            )
    return result


def _build_account_transition(account: str, holdings: int, locked: list[str]) -> dict[str, object]:
    """账户现有持仓 → 低波长线目标组合。universe = 沪深300主板 ∪ 账户个股 ∪ 锁仓。"""
    held, _cash, _ignored = account_stock_positions(account)

    hs = pd.read_csv(HS300_PATH, dtype=str)
    hs["symbol"] = hs["symbol"].str.zfill(6)
    names = dict(zip(hs["symbol"], hs["name"].astype(str)))
    codes = sorted(
        {c for c in (set(hs["symbol"]) | set(held) | set(locked)) if c.startswith(("60", "00")) and cache_exists(c)}
    )
    ohlcv = load_aligned_ohlcv(codes)
    close = ohlcv["close"]
    eligibility = build_trade_eligibility(
        close_matrix=close, high_matrix=ohlcv["high"], low_matrix=ohlcv["low"],
        volume_matrix=ohlcv["volume"], stock_metadata=pd.DataFrame(),
    )
    candidate = eligibility["candidate_mask"]
    panel = compute_factor_panel(close)
    # 各股缓存结尾参差：取最近一个"合格股≥100只"的交易日选股（与 cs_pipeline 同口径）
    good = candidate.sum(axis=1)
    date = good[good >= 100].index[-1]

    # 补全账户持仓/锁仓票的名称
    from quant_a.portfolio_db import get_trades

    trades = get_trades(account)
    if not trades.empty:
        names.update(dict(zip(trades["code"].astype(str).str.zfill(6), trades["name"].astype(str))))

    # 小持仓数时收紧行业上限，避免 6 只里挤 3 只银行
    cap = 2 if holdings <= 8 else CORE_MAX_PER_SECTOR
    target = select_core(
        date, panel, candidate, set(codes), holdings, names,
        current_holdings=[c for c in held if c in close.columns],
        max_per_sector=cap, industry_map=_industry_map(), locked=locked,
    )
    out = build_transition(account, target, names, locked=locked)
    out["summary"]["as_of"] = f"{date:%Y-%m-%d}"
    return out
