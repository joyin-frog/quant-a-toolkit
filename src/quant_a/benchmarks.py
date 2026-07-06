"""共享的股票池等权基准。

公平基准 = 等权持有【全部合格股】。策略相对它的超额 = 纯粹的"选股"能力。
个别脏价格(0→正)会让 pct_change 出 inf、cumprod 炸成无穷，这里统一把 inf 收益清成 0。
"""

from __future__ import annotations

import pandas as pd


def _clean_daily_returns(close_matrix: pd.DataFrame) -> pd.DataFrame:
    return close_matrix.pct_change(fill_method=None).replace([float("inf"), float("-inf")], 0.0)


def monthly_equal_weight_returns(close_matrix: pd.DataFrame, candidate_mask: pd.DataFrame) -> pd.Series:
    """月度等权持有全部合格股（同样月调、但不选股），口径与月调策略一致。"""
    from quant_a.factor_backtest import rebalance_dates

    daily = _clean_daily_returns(close_matrix)
    rebal = rebalance_dates(close_matrix.index)
    weights = pd.DataFrame(0.0, index=close_matrix.index, columns=close_matrix.columns)
    for date in rebal:
        eligible = candidate_mask.loc[date]
        names = eligible[eligible].index
        if len(names) > 0:
            weights.loc[date, names] = 1.0 / len(names)
    held = weights.loc[rebal].reindex(close_matrix.index).ffill().fillna(0.0)
    return (held.shift(1) * daily).sum(axis=1).fillna(0.0)


def daily_equal_weight_returns(close_matrix: pd.DataFrame, candidate_mask: pd.DataFrame) -> pd.Series:
    """每日等权持有全部合格股，口径与逐日状态型策略一致。"""
    daily = _clean_daily_returns(close_matrix)
    eligible_count = candidate_mask.sum(axis=1).replace(0, float("nan"))
    return daily.where(candidate_mask).sum(axis=1).div(eligible_count).fillna(0.0)
