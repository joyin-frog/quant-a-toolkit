import pandas as pd

from quant_a.config import MAX_HOLDINGS, MAX_EXPOSURE, MA_WINDOW, MOMENTUM_WINDOW, POSITION_SIZE, REBALANCE_WEEKDAY


# 当前策略只在固定工作日调仓；如果后续接 backtrader，这个调仓节奏通常会迁移成调度规则。
def rebalance_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index[index.weekday == REBALANCE_WEEKDAY]


# 这里把策略真实使用的信号拆出来，方便回测、因子分析、后续 notebook 研究共用同一套定义。
def compute_strategy_signals(close_matrix: pd.DataFrame, momentum_window: int | None = None) -> dict[str, pd.DataFrame]:
    selected_momentum_window = momentum_window or MOMENTUM_WINDOW
    momentum = close_matrix / close_matrix.shift(selected_momentum_window) - 1
    moving_average = close_matrix.rolling(MA_WINDOW).mean()
    eligible = close_matrix.gt(moving_average)
    factor_score = momentum.where(eligible)
    return {
        "momentum": momentum,
        "moving_average": moving_average,
        "eligible": eligible,
        "factor_score": factor_score,
    }


# 这里输出的是“目标权重矩阵”，而不是成交结果；未来替换信号模型或仓位控制时，优先改这个函数。
def build_target_weights(
    close_matrix: pd.DataFrame,
    momentum_window: int | None = None,
    max_holdings: int | None = None,
) -> pd.DataFrame:
    selected_max_holdings = max_holdings or MAX_HOLDINGS
    signals = compute_strategy_signals(close_matrix, momentum_window=momentum_window)
    factor_score = signals["factor_score"]

    targets = pd.DataFrame(0.0, index=close_matrix.index, columns=close_matrix.columns)
    current = pd.Series(0.0, index=close_matrix.columns)

    for current_date in close_matrix.index:
        if current_date.weekday() != REBALANCE_WEEKDAY:
            targets.loc[current_date] = current
            continue

        # 先用均线过滤掉不在趋势上的标的，再按动量排序，避免纯动量把弱趋势资产也排进来。
        ranked = factor_score.loc[current_date].dropna().sort_values(ascending=False)
        selected = ranked.head(selected_max_holdings).index.tolist()

        current = pd.Series(0.0, index=close_matrix.columns)
        for symbol in selected:
            current[symbol] = POSITION_SIZE

        # POSITION_SIZE 控制单标的目标仓位，MAX_EXPOSURE 控制总敞口；超限时按比例整体缩放。
        if current.sum() > MAX_EXPOSURE:
            current *= MAX_EXPOSURE / current.sum()

        targets.loc[current_date] = current

    return targets
