import math

import pandas as pd

from quant_a.cache import load_cached_bars
from quant_a.config import COMMISSION, INITIAL_CASH, SLIPPAGE


SUPPORTED_ENGINES = {"vectorized", "backtrader"}


def _prepare_target_weights(target_weights: pd.DataFrame) -> pd.DataFrame:
    desired_weights = target_weights.ffill().fillna(0.0).copy()
    desired_weights.index = pd.to_datetime(desired_weights.index)
    desired_weights.index.name = "date"
    return desired_weights


def _prepare_constraint_frame(frame: pd.DataFrame | None, target_index: pd.DatetimeIndex, target_columns: pd.Index) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame(True, index=target_index, columns=target_columns)
    normalized = frame.reindex(index=target_index, columns=target_columns)
    return normalized.fillna(True).astype(bool)


def _build_trades_from_weights(actual_weights: pd.DataFrame) -> pd.DataFrame:
    trades = []
    weight_changes = actual_weights.diff().fillna(actual_weights)
    for trade_date, change_row in weight_changes.iterrows():
        changed = change_row[change_row.abs() > 1e-8]
        for symbol, delta in changed.items():
            trades.append(
                {
                    "date": trade_date,
                    "symbol": symbol,
                    "action": "buy" if delta > 0 else "sell",
                    "weight_change": float(delta),
                }
            )
    return pd.DataFrame(trades)


def _execute_daily_rebalance(
    current_weights: pd.Series,
    target_row: pd.Series,
    can_buy_row: pd.Series,
    can_sell_row: pd.Series,
) -> pd.Series:
    next_weights = current_weights.copy()
    cash = max(0.0, 1.0 - float(next_weights.sum()))
    target_row = target_row.fillna(0.0)

    for symbol, current_weight in current_weights.items():
        target_weight = float(target_row.get(symbol, 0.0))
        if target_weight >= current_weight:
            continue
        if not bool(can_sell_row.get(symbol, True)):
            continue
        delta = current_weight - target_weight
        next_weights[symbol] = target_weight
        cash += delta

    for symbol, current_weight in next_weights.items():
        target_weight = float(target_row.get(symbol, 0.0))
        if target_weight <= current_weight:
            continue
        if not bool(can_buy_row.get(symbol, True)):
            continue
        delta = min(target_weight - current_weight, cash)
        if delta <= 0:
            continue
        next_weights[symbol] = current_weight + delta
        cash -= delta

    return next_weights.clip(lower=0.0)


# 这是一个简化的向量化回测器：按日频收益、下一根 bar 执行、固定成本模型来近似真实持仓表现。
# 如果后续接更多执行引擎，优先保持这里返回 schema 稳定，不动下游指标/订单/报表层。
def run_vectorized_backtest(
    close_matrix: pd.DataFrame,
    target_weights: pd.DataFrame,
    initial_cash: float | None = None,
    can_buy: pd.DataFrame | None = None,
    can_sell: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame | pd.Series]:
    returns = close_matrix.pct_change(fill_method=None).fillna(0.0)
    desired_weights = _prepare_target_weights(target_weights)
    can_buy_frame = _prepare_constraint_frame(can_buy, desired_weights.index, desired_weights.columns)
    can_sell_frame = _prepare_constraint_frame(can_sell, desired_weights.index, desired_weights.columns)

    actual_weights = pd.DataFrame(0.0, index=desired_weights.index, columns=desired_weights.columns)
    current_weights = pd.Series(0.0, index=desired_weights.columns)
    for trade_date in desired_weights.index:
        actual_weights.loc[trade_date] = current_weights
        current_weights = _execute_daily_rebalance(
            current_weights=current_weights,
            target_row=desired_weights.loc[trade_date],
            can_buy_row=can_buy_frame.loc[trade_date],
            can_sell_row=can_sell_frame.loc[trade_date],
        )

    turnover = actual_weights.diff().abs().sum(axis=1).fillna(actual_weights.iloc[0].abs().sum())
    costs = turnover * (COMMISSION + SLIPPAGE)
    gross_returns = (actual_weights.shift(1).fillna(0.0) * returns).sum(axis=1)
    net_returns = gross_returns - costs
    equity_curve = (1.0 + net_returns).cumprod()

    trades_frame = _build_trades_from_weights(actual_weights)
    return {
        "returns": net_returns,
        "equity_curve": equity_curve,
        "target_weights": desired_weights,
        "actual_weights": actual_weights,
        "turnover": turnover,
        "costs": costs,
        "trades": trades_frame,
    }


def _load_backtrader_feed(symbol: str) -> pd.DataFrame:
    bars = load_cached_bars(symbol).copy()
    bars["date"] = pd.to_datetime(bars["date"])
    bars = bars.sort_values("date").drop_duplicates(subset="date", keep="last").set_index("date")
    for column in ["open", "high", "low", "close", "volume"]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    return bars.dropna(subset=["open", "high", "low", "close"])


# backtrader 负责更接近真实成交的执行与资金曲线；目标权重仍然复用 strategy.py 的 pandas 输出。
def run_backtrader_backtest(
    close_matrix: pd.DataFrame,
    target_weights: pd.DataFrame,
    initial_cash: float | None = None,
    can_buy: pd.DataFrame | None = None,
    can_sell: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame | pd.Series]:
    import backtrader as bt

    selected_initial_cash = initial_cash if initial_cash is not None else INITIAL_CASH
    desired_weights = _prepare_target_weights(target_weights)
    can_buy_frame = _prepare_constraint_frame(can_buy, desired_weights.index, desired_weights.columns)
    can_sell_frame = _prepare_constraint_frame(can_sell, desired_weights.index, desired_weights.columns)
    rebalance_flags = desired_weights.diff().abs().sum(axis=1).fillna(desired_weights.abs().sum(axis=1)) > 1e-8

    class TargetWeightsStrategy(bt.Strategy):
        params = dict(target_weights=None, rebalance_flags=None, can_buy=None, can_sell=None)

        def __init__(self):
            self.target_weights = self.p.target_weights
            self.rebalance_flags = self.p.rebalance_flags
            self.can_buy = self.p.can_buy
            self.can_sell = self.p.can_sell
            self.daily_records: list[dict[str, object]] = []
            self.last_seen_date = None

        def next(self):
            current_date = pd.Timestamp(bt.num2date(self.datas[0].datetime[0])).normalize()
            if self.last_seen_date == current_date:
                return
            self.last_seen_date = current_date

            portfolio_value = float(self.broker.getvalue())
            row = {"date": current_date, "equity": portfolio_value / selected_initial_cash}
            for data in self.datas:
                symbol = data._name
                position = self.getposition(data)
                price = float(data.close[0])
                position_value = float(position.size * price) if math.isfinite(price) else 0.0
                row[symbol] = position_value / portfolio_value if portfolio_value else 0.0
            self.daily_records.append(row)

            if current_date not in self.target_weights.index:
                return
            if not bool(self.rebalance_flags.get(current_date, False)):
                return

            target_row = self.target_weights.loc[current_date]
            can_buy_row = self.can_buy.loc[current_date]
            can_sell_row = self.can_sell.loc[current_date]
            for data in self.datas:
                price = float(data.close[0])
                if not math.isfinite(price) or price <= 0:
                    continue
                symbol = data._name
                current_weight = float(self.getposition(data).size * price / portfolio_value) if portfolio_value else 0.0
                target_weight = float(target_row.get(symbol, 0.0))
                if target_weight > current_weight and not bool(can_buy_row.get(symbol, True)):
                    continue
                if target_weight < current_weight and not bool(can_sell_row.get(symbol, True)):
                    continue
                self.order_target_percent(data=data, target=target_weight)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(selected_initial_cash)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.broker.set_slippage_perc(perc=SLIPPAGE)
    cerebro.addstrategy(
        TargetWeightsStrategy,
        target_weights=desired_weights,
        rebalance_flags=rebalance_flags,
        can_buy=can_buy_frame,
        can_sell=can_sell_frame,
    )

    for symbol in desired_weights.columns:
        feed = bt.feeds.PandasData(dataname=_load_backtrader_feed(symbol))
        cerebro.adddata(feed, name=symbol)

    strategy = cerebro.run()[0]
    records = pd.DataFrame(strategy.daily_records)
    if records.empty:
        raise RuntimeError("Backtrader produced no daily records")

    records = records.drop_duplicates(subset="date", keep="last").set_index("date").sort_index()
    equity_curve = records.pop("equity").astype(float)
    actual_weights = records.reindex(columns=desired_weights.columns).astype(float).fillna(0.0)

    actual_weights = actual_weights.reindex(desired_weights.index).ffill().fillna(0.0)
    equity_curve = equity_curve.reindex(desired_weights.index).ffill().fillna(1.0)
    returns = equity_curve.pct_change(fill_method=None).fillna(0.0)

    turnover = actual_weights.diff().abs().sum(axis=1).fillna(0.0)
    if not turnover.empty:
        turnover.iloc[0] = actual_weights.iloc[0].abs().sum()

    # 回测净值已经内含 broker 的成交与成本影响；这里的 costs 只保留统一报表口径，不再二次扣减收益。
    costs = turnover * (COMMISSION + SLIPPAGE)
    trades_frame = _build_trades_from_weights(actual_weights)

    return {
        "returns": returns,
        "equity_curve": equity_curve,
        "target_weights": desired_weights,
        "actual_weights": actual_weights,
        "turnover": turnover,
        "costs": costs,
        "trades": trades_frame,
    }


def run_backtest(
    close_matrix: pd.DataFrame,
    target_weights: pd.DataFrame,
    engine: str = "vectorized",
    initial_cash: float | None = None,
    can_buy: pd.DataFrame | None = None,
    can_sell: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame | pd.Series]:
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"Unsupported backtest engine: {engine}")
    if engine == "backtrader":
        return run_backtrader_backtest(
            close_matrix,
            target_weights,
            initial_cash=initial_cash,
            can_buy=can_buy,
            can_sell=can_sell,
        )
    return run_vectorized_backtest(
        close_matrix,
        target_weights,
        initial_cash=initial_cash,
        can_buy=can_buy,
        can_sell=can_sell,
    )
