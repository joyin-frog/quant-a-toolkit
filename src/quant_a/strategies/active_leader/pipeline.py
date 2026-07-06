from __future__ import annotations

import pandas as pd

from quant_a.benchmarks import daily_equal_weight_returns
from quant_a.cache import cache_exists, load_stock_metadata_cache
from quant_a.cleaning import load_aligned_ohlcv
from quant_a.config import DATA_DIR, REPORTS_DIR
from quant_a.metrics import calculate_metrics
from quant_a.platform.contracts import StrategyResult
from quant_a.plotting import save_equity_vs_benchmark
from quant_a.strategies.active_leader.config import ActiveLeaderConfig
from quant_a.strategies.active_leader.engine import run_stateful_backtest
from quant_a.strategies.active_leader.signals import build_features
from quant_a.trade_rules import build_trade_eligibility
from quant_a.universe import load_mainboard_universe, load_stock_universe


def _industry_map() -> dict[str, str]:
    path = DATA_DIR / "industry_map.csv"
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(path, dtype=str)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return {}
    if not {"symbol", "industry"} <= set(frame.columns):
        return {}
    return dict(zip(frame["symbol"].str.zfill(6), frame["industry"]))


def run_active_leader(
    capital: float = 200_000,
    universe: str = "csi1000",
    config: ActiveLeaderConfig | None = None,
) -> StrategyResult:
    cfg = config or ActiveLeaderConfig()
    if capital <= 0:
        raise ValueError("capital must be positive")
    if universe not in {"mainboard", "csi1000"}:
        raise ValueError("universe must be mainboard or csi1000")
    universe_frame = load_mainboard_universe() if universe == "mainboard" else load_stock_universe()
    symbols = [s for s in universe_frame["symbol"].astype(str).str.zfill(6) if cache_exists(s)]
    if not symbols:
        raise RuntimeError("本地无可用行情缓存")
    ohlcv = load_aligned_ohlcv(symbols)
    close = ohlcv["close"]
    try:
        metadata = load_stock_metadata_cache()
    except Exception:
        metadata = pd.DataFrame()
    eligibility = build_trade_eligibility(
        close_matrix=close,
        high_matrix=ohlcv["high"],
        low_matrix=ohlcv["low"],
        volume_matrix=ohlcv["volume"],
        stock_metadata=metadata,
    )
    industry = _industry_map()
    features = build_features(ohlcv, eligibility["candidate_mask"], industry, cfg)
    backtest = run_stateful_backtest(
        ohlcv,
        features,
        eligibility["can_buy"],
        eligibility["can_sell"],
        capital,
        cfg,
    )
    metrics = calculate_metrics(backtest["returns"], backtest["equity_curve"])

    benchmark_returns = daily_equal_weight_returns(close, eligibility["candidate_mask"])
    benchmark_curve = (1.0 + benchmark_returns).cumprod()
    benchmark_metrics = calculate_metrics(benchmark_returns, benchmark_curve)
    chart = save_equity_vs_benchmark(
        backtest["equity_curve"],
        benchmark_curve,
        REPORTS_DIR / "active_leader" / universe / "equity.png",
        "活跃龙头 vs 股票池等权基准",
        strategy_label="活跃龙头",
        benchmark_label="股票池等权基准",
    )

    # 给网页/报告补齐持仓的名称、现价与成本（引擎只记 symbol/sleeve/shares/entry_price）。
    names = dict(zip(universe_frame["symbol"].astype(str).str.zfill(6), universe_frame["name"].astype(str)))
    holdings = backtest["holdings"]
    if not holdings.empty:
        last_close = close.ffill().iloc[-1]
        holdings = holdings.assign(
            code=holdings["symbol"],
            name=holdings["symbol"].map(names).fillna(""),
            price=holdings["symbol"].map(last_close).astype(float).round(3),
        )
        holdings["cost"] = (holdings["shares"] * holdings["entry_price"]).round(0)
        holdings["lots"] = holdings["shares"] // 100
        holdings["weight"] = (holdings["shares"] * holdings["price"] / float(backtest["equity_curve"].iloc[-1] * capital)).round(4)

    active_counts = features["active"].sum(axis=1)
    warnings = [
        "本地无历史自由流通市值：行业市值前5暂用20日平均成交额前5代理。",
        "本地无历史换手率：5%-15%换手条件暂用成交量/20日均量0.5-1.5代理。",
        "本地无新闻事件数据：利好次日大跌暂用跌超5%且缩量代理。",
        "情绪管理三不看属于人工纪律；算法仅落实不追单日上涨5%以上和限定1-3只龙头。",
        "全主板股票池仍缺历史退市股票，回测残留幸存者偏差。",
    ]
    return StrategyResult(
        strategy_id="active_leader",
        name="活跃龙头底仓+机动仓",
        params={"capital": capital, "universe": universe, **cfg.to_dict()},
        date_range=(close.index.min(), close.index.max()),
        metrics=metrics,
        benchmark_metrics=benchmark_metrics,
        equity_curve=backtest["equity_curve"],
        benchmark_curve=benchmark_curve,
        trades=backtest["trades"],
        holdings=holdings,
        artifacts={"chart": chart},
        warnings=warnings,
        diagnostics={
            "symbols": len(symbols),
            "trade_count": len(backtest["trades"]),
            "active_days": int(active_counts.gt(0).sum()),
            "median_active_leaders": float(active_counts[active_counts.gt(0)].median()) if active_counts.gt(0).any() else 0.0,
            "final_cash": float(backtest["cash"].iloc[-1]),
        },
    )
