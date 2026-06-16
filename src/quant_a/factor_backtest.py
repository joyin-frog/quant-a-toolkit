"""低波动多因子组合的【真实约束】回测：固定本金 + 100 股整手 + 月度调仓。

与研究用的"分数权重"回测不同，这里逐月把组合调成 K 只等额，但每只只能买整手，
买不满的部分留现金。这样跑出来的净值就是 20 万本金实际能拿到的结果（略保守）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_a.config import (
    COMMISSION,
    FACTOR_CAPITAL,
    FACTOR_HOLDINGS,
    FACTOR_REBALANCE,
    FACTOR_SELL_RANK,
    LOT_SIZE,
    REBALANCE_DAY,
    SLIPPAGE,
)
from quant_a.factor_strategy import compute_factor_panel, select_holdings_on


def rebalance_dates(
    index: pd.DatetimeIndex,
    day_of_month: int | None = None,
    freq: str = FACTOR_REBALANCE,
) -> list[pd.Timestamp]:
    """月度调仓日。day_of_month 给定时取每月"该号之后第一个交易日"（默认读 config.REBALANCE_DAY，
    如 15 = 月中）；为空则取每月最后一个交易日。"""
    day = day_of_month if day_of_month is not None else REBALANCE_DAY
    if not day:
        stamps = pd.Series(index, index=index)
        return [d for d in stamps.resample(freq).last().dropna().tolist() if d in index]
    out: list[pd.Timestamp] = []
    stamps = pd.Series(index, index=index)
    for _, group in stamps.groupby([index.year, index.month]):
        candidates = [d for d in group if d.day >= day]
        out.append(candidates[0] if candidates else group.iloc[-1])
    return [d for d in out if d in index]


def _lot_target(picks: list[str], equity: float, price: pd.Series, lot: int) -> pd.Series:
    target = pd.Series(0.0, index=price.index)
    if not picks:
        return target
    budget = equity / len(picks)
    for symbol in picks:
        unit_price = price.get(symbol, np.nan)
        if pd.notna(unit_price) and unit_price > 0:
            target[symbol] = int(budget // (unit_price * lot)) * lot
    return target


def run_factor_backtest(
    close_matrix: pd.DataFrame,
    candidate_mask: pd.DataFrame,
    capital: float | None = None,
    holdings: int | None = None,
    lot_size: int | None = None,
    panel: dict[str, pd.DataFrame] | None = None,
    weights: dict[str, float] | None = None,
    cost: float | None = None,
    sell_rank: int | None = None,
) -> dict[str, object]:
    cap = capital if capital is not None else FACTOR_CAPITAL
    k = holdings or FACTOR_HOLDINGS
    lot = lot_size or LOT_SIZE
    fee = cost if cost is not None else (COMMISSION + SLIPPAGE)
    sell_threshold = sell_rank if sell_rank is not None else FACTOR_SELL_RANK
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
            picks = select_holdings_on(
                current_date, panel, candidate_mask, k, weights,
                current_holdings=held, sell_rank=sell_threshold,
            )
            target = _lot_target(picks, equity, price, lot)
            delta = target - shares
            cash -= float((delta * price.fillna(0.0)).sum())            # 买减卖加
            cash -= float((delta.abs() * price.fillna(0.0)).sum()) * fee  # 双边成本
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
        "rebalance_dates": sorted(rebal),
        "final_shares": shares,
    }


def build_buy_list(
    date: pd.Timestamp,
    picks: list[str],
    price_row: pd.Series,
    capital: float,
    lot: int,
    names: dict[str, str] | None = None,
) -> pd.DataFrame:
    """从【全现金 capital】出发，按当日价格给出实际下单清单（整手）。"""
    names = names or {}
    budget = capital / len(picks) if picks else 0.0
    rows: list[dict[str, object]] = []
    spent = 0.0
    for symbol in picks:
        unit_price = float(price_row.get(symbol, np.nan))
        if not np.isfinite(unit_price) or unit_price <= 0:
            continue
        lots = int(budget // (unit_price * lot))
        shares = lots * lot
        cost = shares * unit_price
        spent += cost
        rows.append(
            {
                "date": date.date(),
                "code": symbol,
                "name": names.get(symbol, ""),
                "price": round(unit_price, 2),
                "lots": lots,
                "shares": shares,
                "cost": round(cost, 0),
                "weight": round(cost / capital, 4),
            }
        )
    table = pd.DataFrame(rows).sort_values("cost", ascending=False).reset_index(drop=True)
    table.attrs["cash_left"] = round(capital - spent, 0)
    table.attrs["invested"] = round(spent, 0)
    return table
