from __future__ import annotations

from quant_a.platform.contracts import StrategyResult


def run_core_satellite_adapter(**params) -> StrategyResult:
    from quant_a.cs_pipeline import run_cs_pipeline

    kwargs = dict(params)
    if "holdings" in kwargs:  # 平台统一叫 holdings，旧管线的形参叫 core_holdings
        kwargs["core_holdings"] = kwargs.pop("holdings")
    raw = run_cs_pipeline(**kwargs)
    return StrategyResult(
        strategy_id="core_satellite",
        name="沪深300核心-卫星",
        params=params,
        date_range=raw["date_range"],
        metrics=raw["metrics"],
        benchmark_metrics=raw["benchmark_metrics"],
        equity_curve=raw["equity_curve"],
        benchmark_curve=raw["benchmark_curve"],
        holdings=raw["buy_list"],
        artifacts={"orders": raw["order_path"], "chart": raw["chart"]},
        diagnostics={
            "avg_cash_pct": raw["avg_cash_pct"],
            "rolling12m": raw["rolling12m"],
            "core_sectors": raw["core_sectors"],
        },
    )


def run_multi_factor_adapter(**params) -> StrategyResult:
    from quant_a.factor_pipeline import run_factor_pipeline

    raw = run_factor_pipeline(**params)
    return StrategyResult(
        strategy_id="multi_factor",
        name="中证1000低波动多因子",
        params=params,
        date_range=raw["date_range"],
        metrics=raw["metrics"],
        benchmark_metrics=raw["benchmark_metrics"],
        equity_curve=raw["equity_curve"],
        benchmark_curve=raw["benchmark_curve"],
        holdings=raw["buy_list"],
        artifacts={"orders": raw["order_path"], **raw["charts"]},
        diagnostics={"avg_cash_pct": raw["avg_cash_pct"], "rolling12m": raw["rolling12m"]},
    )
