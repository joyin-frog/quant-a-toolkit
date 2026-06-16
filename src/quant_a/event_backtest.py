"""5/20 金叉策略的事件驱动组合回测。

与旧的"目标权重"组合回测不同：这里逐日维护一个持仓字典，按用户规则进出场。

资金管理：最多同时持有 GC_MAX_HOLDINGS 只，每只目标 GC_POSITION_WEIGHT（等权 20%）。
成交：买入按信号给的 entry_price（T+2 最低价），卖出按规则触发价。买卖都叠加滑点+佣金。
为简化，允许碎股（不做 100 股整手取整），这会让结果略偏乐观，作为研究口径可接受。

两套卖出模式：
  short（短线）：涨到 +GC_TAKE_PROFIT 止盈（盘中触及即按目标价成交），
                 或收盘有效跌破 5 日线（按收盘价成交）。
  swing（波段）：收盘有效跌破 20 日线（按收盘价成交），不止盈。
"""

from __future__ import annotations

import pandas as pd

from quant_a.config import (
    COMMISSION,
    GC_BREAK_MARGIN,
    GC_MAX_HOLDINGS,
    GC_POSITION_WEIGHT,
    GC_TAKE_PROFIT,
    INITIAL_CASH,
    SLIPPAGE,
)
from quant_a.signals import compute_moving_averages

SUPPORTED_MODES = {"short", "swing"}


def _buy_fill(price: float) -> float:
    return price * (1.0 + SLIPPAGE)


def _sell_fill(price: float) -> float:
    return price * (1.0 - SLIPPAGE)


def run_event_backtest(
    open_matrix: pd.DataFrame,
    high_matrix: pd.DataFrame,
    low_matrix: pd.DataFrame,
    close_matrix: pd.DataFrame,
    entry_trades: pd.DataFrame,
    mode: str,
    initial_cash: float | None = None,
    fast: int | None = None,
    slow: int | None = None,
    take_profit: float | None = None,
    break_margin: float | None = None,
    max_holdings: int | None = None,
    position_weight: float | None = None,
    stop_loss: float | None = None,
    market_ok: pd.Series | None = None,
) -> dict[str, object]:
    """stop_loss: 硬止损比例（如 0.04 = 跌 4% 无条件止损），None 关闭。
    market_ok: 按日期的布尔序列，为 False 的日子不开新仓（大盘择时过滤），None 关闭。
    """
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported mode: {mode}")

    cash0 = initial_cash if initial_cash is not None else INITIAL_CASH
    tp = take_profit if take_profit is not None else GC_TAKE_PROFIT
    margin = break_margin if break_margin is not None else GC_BREAK_MARGIN
    max_n = max_holdings or GC_MAX_HOLDINGS
    weight = position_weight if position_weight is not None else GC_POSITION_WEIGHT

    mas = compute_moving_averages(close_matrix, fast=fast, slow=slow)
    ma_fast, ma_slow = mas["ma_fast"], mas["ma_slow"]
    # 估值用前向填充的收盘价，避免个股停牌缺值把持仓打成 0。
    close_val = close_matrix.ffill()

    # 把进场计划按日期分组，便于逐日查"今天该买谁"。
    entries_by_date: dict[pd.Timestamp, list[dict]] = {}
    for _, trade in entry_trades.iterrows():
        entries_by_date.setdefault(trade["entry_date"], []).append(trade.to_dict())

    cash = float(cash0)
    positions: dict[str, dict] = {}  # symbol -> {shares, entry_price, entry_date}
    equity_records: list[dict] = []
    trade_log: list[dict] = []

    index = close_matrix.index
    for current_date in index:
        # ---------- 1. 先处理卖出（已持仓的，从买入次日起才检查） ----------
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if current_date <= pos["entry_date"]:
                continue
            close_p = close_matrix.at[current_date, symbol]
            high_p = high_matrix.at[current_date, symbol]
            low_p = low_matrix.at[current_date, symbol]
            if pd.isna(close_p):
                continue

            entry_price = pos["entry_price"]
            sell_price = None
            reason = None

            # 硬止损优先（悲观假设：同一天若既触止损又触止盈，按先触止损算）。
            stop_price = entry_price * (1.0 - stop_loss) if stop_loss else None
            if stop_price is not None and not pd.isna(low_p) and low_p <= stop_price:
                sell_price = stop_price
                reason = "stop_loss"
            elif mode == "short":
                target = entry_price * (1.0 + tp)
                ma5 = ma_fast.at[current_date, symbol]
                if not pd.isna(high_p) and high_p >= target:
                    sell_price = target  # 盘中触及止盈价
                    reason = "take_profit"
                elif not pd.isna(ma5) and close_p < ma5 * (1.0 - margin):
                    sell_price = close_p  # 有效跌破 5 日线
                    reason = "break_ma5"
            else:  # swing
                ma20 = ma_slow.at[current_date, symbol]
                if not pd.isna(ma20) and close_p < ma20 * (1.0 - margin):
                    sell_price = close_p  # 有效跌破 20 日线
                    reason = "break_ma20"

            if sell_price is not None:
                fill = _sell_fill(sell_price)
                proceeds = pos["shares"] * fill * (1.0 - COMMISSION)
                cash += proceeds
                pnl = proceeds - pos["cost"]
                trade_log.append(
                    {
                        "symbol": symbol,
                        "entry_date": pos["entry_date"],
                        "entry_price": entry_price,
                        "exit_date": current_date,
                        "exit_price": sell_price,
                        "reason": reason,
                        "return": pnl / pos["cost"] if pos["cost"] else 0.0,
                        "pnl": pnl,
                    }
                )
                del positions[symbol]

        # ---------- 2. 再处理买入（今天的进场计划，受空位与现金约束） ----------
        # 大盘择时过滤：行情走弱的日子不开新仓（已持仓不受影响）。
        market_allows_entry = True if market_ok is None else bool(market_ok.get(current_date, True))
        for trade in entries_by_date.get(current_date, []):
            if not market_allows_entry:
                break
            symbol = trade["symbol"]
            if symbol in positions:
                continue
            if len(positions) >= max_n:
                continue
            equity_now = cash + sum(
                p["shares"] * _safe_price(close_val, current_date, s) for s, p in positions.items()
            )
            budget = min(weight * equity_now, cash)
            if budget <= 0:
                continue
            fill = _buy_fill(trade["entry_price"])
            shares = budget / (fill * (1.0 + COMMISSION))
            if shares <= 0:
                continue
            cost = shares * fill * (1.0 + COMMISSION)
            cash -= cost
            positions[symbol] = {
                "shares": shares,
                "entry_price": trade["entry_price"],
                "entry_date": current_date,
                "cost": cost,
            }

        # ---------- 3. 记录当日净值 ----------
        holdings_value = sum(
            p["shares"] * _safe_price(close_val, current_date, s) for s, p in positions.items()
        )
        equity_records.append(
            {"date": current_date, "equity": cash + holdings_value, "n_positions": len(positions)}
        )

    equity_df = pd.DataFrame(equity_records).set_index("date")
    equity_curve = equity_df["equity"] / cash0
    returns = equity_curve.pct_change(fill_method=None).fillna(0.0)
    trades_frame = pd.DataFrame(trade_log)

    return {
        "mode": mode,
        "equity_curve": equity_curve,
        "returns": returns,
        "n_positions": equity_df["n_positions"],
        "trades": trades_frame,
    }


def _safe_price(close_matrix: pd.DataFrame, date: pd.Timestamp, symbol: str) -> float:
    price = close_matrix.at[date, symbol]
    return float(price) if pd.notna(price) else 0.0
