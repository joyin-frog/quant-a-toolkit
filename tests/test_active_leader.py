import pandas as pd

from quant_a.strategies.active_leader.config import ActiveLeaderConfig
from quant_a.strategies.active_leader.engine import run_stateful_backtest
from quant_a.strategies.active_leader.signals import _streak


def test_streak_counts_consecutive_days_from_first_row():
    idx = pd.bdate_range("2024-01-01", periods=5)
    mask = pd.DataFrame({"A": [True, True, False, True, True]}, index=idx)
    assert _streak(mask)["A"].tolist() == [1, 2, 0, 1, 2]


def _feature_frame(idx, value=False):
    return pd.DataFrame({"A": [value] * len(idx)}, index=idx)


def test_stateful_engine_executes_next_open_and_halves_long_on_stop():
    idx = pd.bdate_range("2024-01-01", periods=4)
    close = pd.DataFrame({"A": [10.0, 10.0, 9.0, 9.0]}, index=idx)
    open_ = pd.DataFrame({"A": [10.0, 10.1, 8.9, 8.8]}, index=idx)
    volume = pd.DataFrame({"A": [1000.0] * 4}, index=idx)
    ohlcv = {"open": open_, "high": close, "low": close, "close": close, "volume": volume}
    features = {
        "active": _feature_frame(idx, True),
        "leader_score": pd.DataFrame({"A": [1.0] * 4}, index=idx),
        "weekly_trend": _feature_frame(idx, True),
        "monthly_macd_growing": _feature_frame(idx, True),
        "weekly_up3": _feature_frame(idx),
        "weekly_below_ma10": _feature_frame(idx),
        "weekly_doji_low_volume": _feature_frame(idx),
        "kdj_dead": _feature_frame(idx),
        "up_streak": pd.DataFrame({"A": [0] * 4}, index=idx),
        "down_streak": pd.DataFrame({"A": [0] * 4}, index=idx),
        "volume_contract_20": _feature_frame(idx),
        "pullback_10": _feature_frame(idx),
        "small_bull": _feature_frame(idx),
        "kdj_golden": _feature_frame(idx),
        "price_volume_up": _feature_frame(idx),
        "news_drop_proxy": _feature_frame(idx),
        "daily_return": pd.DataFrame({"A": [0.0, 0.0, -0.1, 0.0]}, index=idx),
        "market_limit_ups": pd.Series([0] * 4, index=idx),
        "market_weak": pd.Series([False] * 4, index=idx),
    }
    allowed = _feature_frame(idx, True)
    cfg = ActiveLeaderConfig(max_leaders=1, commission=0.0, slippage=0.0)
    result = run_stateful_backtest(ohlcv, features, allowed, allowed, 100_000, cfg)
    trades = result["trades"]
    assert trades.iloc[0]["date"] == idx[1]
    assert trades.iloc[0]["action"] == "buy"
    assert trades.iloc[0]["price"] == 10.1
    assert trades.iloc[1]["date"] == idx[3]
    assert trades.iloc[1]["reason"] == "底仓-8%或跌破均线减半"
    assert trades.iloc[1]["shares"] == (trades.iloc[0]["shares"] // 2 // cfg.lot_size) * cfg.lot_size


def test_profit_trim_reentry_buys_back_only_trimmed_shares():
    """+30% 减半后 8-10 日缩量接回：只买回减掉的那部分，不是再来一整份预算。"""
    n = 16
    idx = pd.bdate_range("2024-01-01", periods=n)
    prices = [10.0, 10.0] + [13.5] * (n - 2)  # 第3天起 +35%
    close = pd.DataFrame({"A": prices}, index=idx)
    open_ = close.copy()
    volumes = [1000.0] * 10 + [300.0] * (n - 10)  # 第11天起缩量到峰值 1/3 以下
    volume = pd.DataFrame({"A": volumes}, index=idx)
    ohlcv = {"open": open_, "high": close, "low": close, "close": close, "volume": volume}
    features = {
        "active": _feature_frame(idx, True),
        "leader_score": pd.DataFrame({"A": [1.0] * n}, index=idx),
        "weekly_trend": _feature_frame(idx, True),
        "monthly_macd_growing": _feature_frame(idx, True),
        "weekly_up3": _feature_frame(idx),
        "weekly_below_ma10": _feature_frame(idx),
        "weekly_doji_low_volume": _feature_frame(idx),
        "kdj_dead": _feature_frame(idx),
        "up_streak": pd.DataFrame({"A": [0] * n}, index=idx),
        "down_streak": pd.DataFrame({"A": [0] * n}, index=idx),
        "volume_contract_20": _feature_frame(idx),
        "pullback_10": _feature_frame(idx),
        "small_bull": _feature_frame(idx),
        "kdj_golden": _feature_frame(idx),
        "price_volume_up": _feature_frame(idx),
        "news_drop_proxy": _feature_frame(idx),
        "daily_return": close.pct_change(fill_method=None).fillna(0.0),
        "market_limit_ups": pd.Series([0] * n, index=idx),
        "market_weak": pd.Series([False] * n, index=idx),
    }
    allowed = _feature_frame(idx, True)
    cfg = ActiveLeaderConfig(max_leaders=1, commission=0.0, slippage=0.0)
    result = run_stateful_backtest(ohlcv, features, allowed, allowed, 100_000, cfg)
    trades = result["trades"]
    assert trades.iloc[0]["action"] == "buy"  # 首日建仓
    trim = trades.iloc[1]
    assert trim["reason"] == "单波上涨30%减半"
    reentry = trades[trades["reason"] == "回调到位接回底仓"]
    assert len(reentry) == 1
    # 接回股数 == 减仓股数（原文“把减仓的部分接回来”），且总持仓回到建仓时的股数
    assert int(reentry.iloc[0]["shares"]) == int(trim["shares"])
    final = result["holdings"]
    assert int(final[final["sleeve"] == "long"].iloc[0]["shares"]) == int(trades.iloc[0]["shares"])
