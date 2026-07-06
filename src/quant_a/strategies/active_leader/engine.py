from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant_a.strategies.active_leader.config import ActiveLeaderConfig


@dataclass
class SleevePosition:
    shares: int = 0
    entry_price: float = 0.0
    entry_date: pd.Timestamp | None = None
    reduced_for_profit: bool = False
    reduced_for_loss: bool = False
    last_exit_date: pd.Timestamp | None = None
    last_exit_reason: str = ""
    peak_volume: float = 0.0
    trimmed_shares: int = 0  # 止盈减掉的股数：接回时只买回这部分，不是再来一整份预算


def _leaders_on(date: pd.Timestamp, features: dict[str, object], maximum: int) -> list[str]:
    active = features["active"].loc[date]
    score = features["leader_score"].loc[date]
    return score[active & score.notna()].nlargest(maximum).index.tolist()


def _lots_for_budget(budget: float, price: float, lot: int) -> int:
    if not np.isfinite(price) or price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * lot)) * lot


def run_stateful_backtest(
    ohlcv: dict[str, pd.DataFrame],
    features: dict[str, object],
    can_buy: pd.DataFrame,
    can_sell: pd.DataFrame,
    capital: float,
    config: ActiveLeaderConfig | None = None,
) -> dict[str, object]:
    """信号于收盘后确认，下一交易日开盘执行；底仓和机动仓分别记账。"""
    cfg = config or ActiveLeaderConfig()
    close, open_, volume = ohlcv["close"], ohlcv["open"], ohlcv["volume"]
    close_valuation = close.ffill()
    # 跌破20日均线的止损基准：循环外一次算完；数据不足20日时用现有窗口均线兜底（min_periods=1），
    # 避免个股进池前19日该止损静默失效。
    ma20 = close.rolling(20, min_periods=1).mean()
    dates, symbols = close.index, close.columns
    date_pos = {date: i for i, date in enumerate(dates)}
    long_pos = {s: SleevePosition() for s in symbols}
    tactical_pos = {s: SleevePosition() for s in symbols}
    held_long: set[str] = set()
    held_tactical: set[str] = set()
    cash = float(capital)
    trades: list[dict[str, object]] = []
    records: list[dict[str, object]] = []

    def transact(date, symbol, sleeve, action, shares, price, reason) -> int:
        """执行整手交易，返回实际成交股数（0 表示没成交）。"""
        nonlocal cash
        if sleeve == "long":
            pos, held = long_pos[symbol], held_long
        else:
            pos, held = tactical_pos[symbol], held_tactical
        shares = int(shares // cfg.lot_size) * cfg.lot_size
        if shares <= 0 or not np.isfinite(price) or price <= 0:
            return 0
        rate = cfg.commission + cfg.slippage
        if action == "buy":
            was_flat = pos.shares == 0
            affordable = _lots_for_budget(cash / (1 + rate), price, cfg.lot_size)
            shares = min(shares, affordable)
            if shares <= 0:
                return 0
            old_value = pos.shares * pos.entry_price
            cash -= shares * price * (1 + rate)
            pos.shares += shares
            pos.entry_price = (old_value + shares * price) / pos.shares
            pos.entry_date = pos.entry_date or date
            pos.peak_volume = max(pos.peak_volume, float(volume.loc[date, symbol] or 0))
            held.add(symbol)
            if was_flat:
                pos.reduced_for_profit = False
                pos.reduced_for_loss = False
        else:
            shares = min(shares, pos.shares)
            if shares <= 0:
                return 0
            cash += shares * price * (1 - rate)
            pos.shares -= shares
            if pos.shares == 0:
                held.discard(symbol)
                pos.last_exit_date = date
                pos.last_exit_reason = reason
                pos.entry_price = 0.0
                pos.entry_date = None
        trades.append({
            "date": date, "symbol": symbol, "sleeve": sleeve, "action": action,
            "shares": shares, "price": round(float(price), 4), "reason": reason,
        })
        return shares

    def mark_equity(date: pd.Timestamp) -> float:
        total = cash
        row = close_valuation.loc[date]
        for symbol in held_long:
            px = row.get(symbol)
            if pd.notna(px):
                total += long_pos[symbol].shares * float(px)
        for symbol in held_tactical:
            px = row.get(symbol)
            if pd.notna(px):
                total += tactical_pos[symbol].shares * float(px)
        return total

    for i, date in enumerate(dates):
        execution_price = open_.loc[date]
        if i > 0:
            signal_date = dates[i - 1]
            signal_pos = i - 1
            leaders = _leaders_on(signal_date, features, cfg.max_leaders)

            # 先执行退出，确保止损和止盈优先于新开仓。
            for symbol in sorted(held_long):
                lp = long_pos[symbol]
                px_signal = close.loc[signal_date, symbol]
                px_exec = execution_price.get(symbol, np.nan)
                if not (lp.shares and bool(can_sell.loc[date, symbol]) and pd.notna(px_signal)):
                    continue
                gain = px_signal / lp.entry_price - 1 if lp.entry_price else 0.0
                ma = ma20.loc[signal_date, symbol]
                if bool(features["weekly_up3"].loc[signal_date, symbol]):
                    transact(date, symbol, "long", "sell", lp.shares, px_exec, "连续3周收阳清仓")
                elif gain >= cfg.long_take_profit and not lp.reduced_for_profit:
                    sold = transact(date, symbol, "long", "sell", max(cfg.lot_size, lp.shares // 2), px_exec, "单波上涨30%减半")
                    if sold:
                        lp.reduced_for_profit = True
                        lp.trimmed_shares = sold
                        lp.last_exit_date = date
                        lp.last_exit_reason = "profit_trim"
                        lp.peak_volume = float(volume.loc[signal_date, symbol])
                elif (
                    gain <= cfg.long_stop_loss
                    or bool(features["weekly_below_ma10"].loc[signal_date, symbol])
                    or (pd.notna(ma) and px_signal < ma)
                ) and not lp.reduced_for_loss:
                    sold = transact(date, symbol, "long", "sell", max(cfg.lot_size, lp.shares // 2), px_exec, "底仓-8%或跌破均线减半")
                    if sold:
                        lp.reduced_for_loss = True

            for symbol in sorted(held_tactical):
                tp = tactical_pos[symbol]
                px_signal = close.loc[signal_date, symbol]
                px_exec = execution_price.get(symbol, np.nan)
                if not (tp.shares and bool(can_sell.loc[date, symbol]) and pd.notna(px_signal)):
                    continue
                gain = px_signal / tp.entry_price - 1 if tp.entry_price else 0.0
                held_days = signal_pos - date_pos[tp.entry_date] if tp.entry_date in date_pos else 0
                reason = ""
                if gain <= cfg.tactical_stop_loss:
                    reason = "机动仓-5%止损"
                elif gain >= cfg.tactical_take_profit:
                    reason = "机动仓6%-8%止盈"
                elif gain >= cfg.news_rebound_exit and tp.last_exit_reason == "news_proxy":
                    reason = "利好大跌代理次日反弹3%止盈"
                elif int(features["up_streak"].loc[signal_date, symbol]) >= cfg.tactical_up_days_exit:
                    reason = "连涨3天卖出"
                elif bool(features["kdj_dead"].loc[signal_date, symbol]):
                    reason = "KDJ死叉离场"
                elif held_days >= cfg.tactical_max_days:
                    reason = "机动仓5日时间止损"
                if reason:
                    transact(date, symbol, "tactical", "sell", tp.shares, px_exec, reason)

            total_equity = mark_equity(signal_date)  # 以信号日收盘估值定预算
            tactical_weight = (
                cfg.tactical_weight_hot
                if int(features["market_limit_ups"].loc[signal_date]) > cfg.hot_limit_up_count
                else cfg.tactical_weight_normal
            )
            if bool(features["market_weak"].loc[signal_date]):
                tactical_weight = cfg.tactical_weight_normal

            # 长线首次建仓：周线均线多头 + 月线MACD红柱放大。
            long_candidates = [
                s for s in leaders
                if long_pos[s].shares == 0
                and long_pos[s].last_exit_date is None
                and bool(features["weekly_trend"].loc[signal_date, s])
                and bool(features["monthly_macd_growing"].loc[signal_date, s])
            ]
            for symbol in long_candidates:
                if not bool(can_buy.loc[date, symbol]):
                    continue
                budget = total_equity * cfg.long_weight / max(1, cfg.max_leaders)
                transact(date, symbol, "long", "buy", _lots_for_budget(budget, execution_price[symbol], cfg.lot_size), execution_price[symbol], "周线趋势+月线MACD")

            # 止盈后8-10日缩量接回【减掉的那部分】；连续3周清仓退出后，第2周缩量十字星按整份预算接回。
            for symbol in leaders:
                lp = long_pos[symbol]
                if not lp.last_exit_date or not bool(can_buy.loc[date, symbol]):
                    continue
                elapsed = signal_pos - date_pos.get(lp.last_exit_date, signal_pos)
                reenter_profit = (
                    lp.last_exit_reason == "profit_trim"
                    and cfg.long_reentry_min_days <= elapsed <= cfg.long_reentry_max_days
                    and volume.loc[signal_date, symbol] <= lp.peak_volume * cfg.long_reentry_volume_fraction
                )
                reenter_week = lp.last_exit_reason == "连续3周收阳清仓" and elapsed >= 8 and bool(features["weekly_doji_low_volume"].loc[signal_date, symbol])
                if reenter_profit:
                    shares = lp.trimmed_shares  # 原文口径：把减仓的部分接回来
                elif reenter_week:
                    shares = _lots_for_budget(total_equity * cfg.long_weight / max(1, cfg.max_leaders), execution_price[symbol], cfg.lot_size)
                else:
                    continue
                bought = transact(date, symbol, "long", "buy", shares, execution_price[symbol], "回调到位接回底仓")
                if bought:
                    lp.last_exit_date = None
                    lp.last_exit_reason = ""
                    lp.trimmed_shares = 0

            # 机动仓四套入口均实现为 OR；禁止追当日突然拉涨5%的股票。
            for symbol in leaders:
                if tactical_pos[symbol].shares or not bool(can_buy.loc[date, symbol]):
                    continue
                no_chase = float(features["daily_return"].loc[signal_date, symbol]) < 0.05
                entry4down = int(features["down_streak"].loc[signal_date, symbol]) >= cfg.tactical_down_days_entry and bool(features["volume_contract_20"].loc[signal_date, symbol])
                pullback = bool(features["pullback_10"].loc[signal_date, symbol]) and bool(features["small_bull"].loc[signal_date, symbol])
                kdj = bool(features["kdj_golden"].loc[signal_date, symbol]) and bool(features["price_volume_up"].loc[signal_date, symbol])
                news = bool(features["news_drop_proxy"].loc[signal_date, symbol])
                if no_chase and (entry4down or pullback or kdj or news):
                    budget = total_equity * tactical_weight / max(1, cfg.max_leaders)
                    reason = "利好次日缩量大跌代理" if news else "连跌/回调/KDJ机动信号"
                    transact(date, symbol, "tactical", "buy", _lots_for_budget(budget, execution_price[symbol], cfg.lot_size), execution_price[symbol], reason)
                    tactical_pos[symbol].last_exit_reason = "news_proxy" if news else ""

        records.append({
            "date": date, "equity": mark_equity(date), "cash": cash,
            "long_count": len(held_long),
            "tactical_count": len(held_tactical),
        })

    frame = pd.DataFrame(records).set_index("date")
    equity_curve = frame["equity"] / capital
    returns = equity_curve.pct_change(fill_method=None).fillna(0.0)
    final_rows = []
    for symbol in sorted(held_long | held_tactical):
        for sleeve, pos in (("long", long_pos[symbol]), ("tactical", tactical_pos[symbol])):
            if pos.shares:
                final_rows.append({"symbol": symbol, "sleeve": sleeve, "shares": pos.shares, "entry_price": pos.entry_price})
    return {
        "equity_curve": equity_curve,
        "returns": returns,
        "cash": frame["cash"],
        "trades": pd.DataFrame(trades),
        "holdings": pd.DataFrame(final_rows),
        "state": frame,
    }
