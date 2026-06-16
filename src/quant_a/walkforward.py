"""滚动验证（walk-forward）：逐年/滚动窗口看策略是否稳定，而非靠某一年。

本策略不拟合任何参数（权重 70/30、K、窗口都是先验固定），且每个调仓日只用过去数据选股，
所以整条回测本身就是"向前"的。这里要回答的是稳健性问题：
  1) 逐年表现——每年是否都跑赢基准（而不是靠 2019-21 那一波）
  2) 滚动 12 个月夏普——风险调整收益是否持续为正
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import empyrical as ep

from quant_a.config import TRADING_DAYS_PER_YEAR


def _stats(returns: pd.Series) -> dict[str, float]:
    r = returns.astype(float).fillna(0.0)
    return {
        "return": float(ep.cum_returns_final(r)),
        "sharpe": float(ep.sharpe_ratio(r, annualization=TRADING_DAYS_PER_YEAR) or 0.0),
        "max_drawdown": float(ep.max_drawdown(r)),
    }


def per_year_table(strategy_returns: pd.Series, benchmark_returns: pd.Series, min_days: int = 20) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year in sorted({d.year for d in strategy_returns.index}):
        s = strategy_returns[strategy_returns.index.year == year]
        b = benchmark_returns.reindex(s.index).fillna(0.0)
        if len(s) < min_days:
            continue
        ss, bs = _stats(s), _stats(b)
        rows.append(
            {
                "year": year,
                "strat_return": ss["return"],
                "strat_sharpe": ss["sharpe"],
                "strat_mdd": ss["max_drawdown"],
                "bench_return": bs["return"],
                "excess": ss["return"] - bs["return"],
                "win": ss["return"] > bs["return"],
            }
        )
    return pd.DataFrame(rows)


def rolling_sharpe(returns: pd.Series, window: int = TRADING_DAYS_PER_YEAR) -> pd.Series:
    r = returns.astype(float).fillna(0.0)
    mean = r.rolling(window).mean()
    std = r.rolling(window).std()
    return (mean / std * np.sqrt(TRADING_DAYS_PER_YEAR)).rename("rolling_sharpe")


def rolling_return_summary(returns: pd.Series, window: int = TRADING_DAYS_PER_YEAR) -> dict[str, float]:
    """滚动 window 日累计收益的分布——比"全程/单年"更能说明"随便哪天入场、接下来一年大概什么体验"。"""
    r = returns.astype(float).fillna(0.0)
    rolling = (1.0 + r).rolling(window).apply(np.prod, raw=True) - 1.0
    rolling = rolling.dropna()
    if rolling.empty:
        return {"window_days": window, "median": 0.0, "best": 0.0, "worst": 0.0, "pct_positive": 0.0}
    return {
        "window_days": window,
        "median": float(rolling.median()),
        "best": float(rolling.max()),
        "worst": float(rolling.min()),
        "pct_positive": float((rolling > 0).mean()),
    }


def summarize(per_year: pd.DataFrame) -> dict[str, float]:
    if per_year.empty:
        return {"years": 0, "win_rate": 0.0, "avg_excess": 0.0, "worst_year_excess": 0.0}
    return {
        "years": int(len(per_year)),
        "win_rate": float(per_year["win"].mean()),
        "avg_excess": float(per_year["excess"].mean()),
        "worst_year_excess": float(per_year["excess"].min()),
    }
