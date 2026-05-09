import empyrical as ep
import pandas as pd

from quant_a.config import TRADING_DAYS_PER_YEAR


# 当前指标层是一个轻量适配器；如果后续调整绩效口径，优先改这里而不是散落到主流程里。
def calculate_metrics(returns: pd.Series, equity_curve: pd.Series) -> dict[str, float]:
    clean_returns = returns.astype(float).fillna(0.0)
    non_zero_returns = clean_returns[clean_returns != 0]

    total_return = float(ep.cum_returns_final(clean_returns))
    annualized_return = float(ep.annual_return(clean_returns, annualization=TRADING_DAYS_PER_YEAR))
    max_drawdown = float(ep.max_drawdown(clean_returns))
    volatility = float(ep.annual_volatility(clean_returns, annualization=TRADING_DAYS_PER_YEAR))
    sharpe = float(ep.sharpe_ratio(clean_returns, annualization=TRADING_DAYS_PER_YEAR) or 0.0)
    sortino = float(ep.sortino_ratio(clean_returns, annualization=TRADING_DAYS_PER_YEAR) or 0.0)
    calmar = float(ep.calmar_ratio(clean_returns, annualization=TRADING_DAYS_PER_YEAR) or 0.0)
    win_rate = float((non_zero_returns > 0).mean()) if not non_zero_returns.empty else 0.0

    return {
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "win_rate": win_rate,
    }
