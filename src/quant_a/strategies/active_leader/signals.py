from __future__ import annotations

import numpy as np
import pandas as pd

from quant_a.strategies.active_leader.config import ActiveLeaderConfig


def _streak(mask: pd.DataFrame) -> pd.DataFrame:
    """连续 True 的天数（False 处归零）。向量化：累计和减去最近一次 False 处的累计和。"""
    m = mask.fillna(False).astype(bool)
    cum = m.cumsum()
    reset = cum.where(~m).ffill().fillna(0)
    return (cum - reset).astype(int)


def _kdj(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    lowest = low.rolling(9, min_periods=9).min()
    highest = high.rolling(9, min_periods=9).max()
    rsv = ((close - lowest) / (highest - lowest).replace(0, np.nan) * 100).clip(0, 100)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    return k, d


def _completed_period_features(close: pd.DataFrame, volume: pd.DataFrame) -> dict[str, pd.DataFrame]:
    weekly_close = close.resample("W-FRI").last()
    weekly_volume = volume.resample("W-FRI").sum()
    wma5 = weekly_close.rolling(5).mean()
    wma10 = weekly_close.rolling(10).mean()
    weekly_up3 = (weekly_close.pct_change(fill_method=None) > 0).rolling(3).sum().eq(3)
    weekly_doji = ((weekly_close / weekly_close.shift(1) - 1).abs() <= 0.015)
    weekly_low_volume = weekly_volume < weekly_volume.rolling(5).mean()

    monthly = close.resample("ME").last()
    ema12 = monthly.ewm(span=12, adjust=False).mean()
    ema26 = monthly.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_hist = dif - dea

    def daily(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.reindex(close.index, method="ffill").reindex(columns=close.columns)

    return {
        "weekly_trend": daily(wma5 > wma10),
        "weekly_up3": daily(weekly_up3),
        "weekly_doji_low_volume": daily(weekly_doji & weekly_low_volume),
        "weekly_below_ma10": daily(weekly_close < wma10),
        "monthly_macd_growing": daily(macd_hist > macd_hist.shift(1)),
    }


def build_features(
    ohlcv: dict[str, pd.DataFrame],
    candidate_mask: pd.DataFrame,
    industry_map: dict[str, str] | None = None,
    config: ActiveLeaderConfig | None = None,
) -> dict[str, pd.DataFrame | pd.Series]:
    cfg = config or ActiveLeaderConfig()
    close, high, low, volume = (ohlcv[key] for key in ("close", "high", "low", "volume"))
    daily_return = close.pct_change(fill_method=None)
    limit_up_count = daily_return.ge(0.095).rolling(cfg.lookback_days).sum()
    volume_avg20 = volume.rolling(20).mean()
    volume_ratio = volume / volume_avg20.replace(0, np.nan)
    traded_value = close * volume

    # 缺少历史流通市值时，以当日成交额排名作为“行业前五”的可审计代理；未知行业不互相竞争。
    industry_map = industry_map or {}
    industry = {symbol: industry_map.get(symbol, f"UNKNOWN:{symbol}") for symbol in close.columns}
    top5 = pd.DataFrame(False, index=close.index, columns=close.columns)
    relative20 = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    group_return = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    ret20 = close.pct_change(20, fill_method=None)
    groups: dict[str, list[str]] = {}
    for symbol, label in industry.items():
        groups.setdefault(label, []).append(symbol)
    market_return = daily_return.mean(axis=1)
    market_ret20 = ret20.mean(axis=1)
    for label, symbols in groups.items():
        block = traded_value[symbols].rolling(20).mean()
        top5[symbols] = block.rank(axis=1, ascending=False, method="min") <= 5
        if label.startswith("UNKNOWN:"):
            relative20[symbols] = ret20[symbols].sub(market_ret20, axis=0)
            group_series = market_return
        else:
            relative20[symbols] = ret20[symbols].sub(ret20[symbols].mean(axis=1), axis=0)
            group_series = daily_return[symbols].mean(axis=1)
        group_return[symbols] = np.repeat(group_series.to_numpy()[:, None], len(symbols), axis=1)

    strong_when_group_up = group_return.ge(0.03) & daily_return.ge(0.05)
    defensive_when_group_down = group_return.le(-0.02) & daily_return.ge(-0.01)
    leader_confirmed = (
        strong_when_group_up.rolling(cfg.lookback_days).sum().ge(1)
        & defensive_when_group_down.rolling(cfg.lookback_days).sum().ge(1)
    )

    active = (
        candidate_mask
        & limit_up_count.ge(cfg.min_limit_ups)
        & volume_ratio.ge(cfg.turnover_proxy_low)
        & volume_ratio.le(cfg.turnover_proxy_high)
        & top5
        & leader_confirmed
    )
    defensive = daily_return - group_return
    leader_score = relative20.fillna(0.0) + defensive.rolling(20).mean().fillna(0.0)

    k, d = _kdj(high, low, close)
    up_streak = _streak(daily_return.gt(0))
    down_streak = _streak(daily_return.lt(0))
    body_return = close / ohlcv["open"] - 1
    small_bull = close.gt(ohlcv["open"]) & body_return.ge(0) & body_return.le(0.02)
    recent_high = close.rolling(20).max()
    period = _completed_period_features(close, volume)
    market_limit_ups = daily_return.ge(0.095).sum(axis=1)
    market_weak = daily_return.gt(0).sum(axis=1) < daily_return.lt(0).sum(axis=1)

    return {
        "daily_return": daily_return,
        "active": active,
        "leader_score": leader_score,
        "up_streak": up_streak,
        "down_streak": down_streak,
        "volume_ratio": volume_ratio,
        "volume_contract_20": volume.le(volume.shift(1) * (1 - cfg.tactical_volume_contraction)),
        "pullback_10": close.div(recent_high).sub(1).le(cfg.pullback_entry),
        "small_bull": small_bull,
        "kdj_golden": (k > d) & (k.shift(1) <= d.shift(1)),
        "kdj_dead": (k < d) & (k.shift(1) >= d.shift(1)),
        "price_volume_up": daily_return.gt(0) & volume.gt(volume.shift(1)),
        "news_drop_proxy": daily_return.le(cfg.news_drop_proxy) & volume.lt(volume.shift(1)),
        "market_limit_ups": market_limit_ups,
        "market_weak": market_weak,
        **period,
    }
