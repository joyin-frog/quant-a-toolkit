"""低波动多因子组合策略 —— 主力策略总控。

流程：选股池 → 合格过滤(含现价<500) → 算因子 → 20万本金整手月度回测 →
指标 + 等权基准对比 → 输出"本月该买哪 K 只"的下单清单 → 存净值/回撤图。

跑法：PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a.cache import cache_exists
from quant_a.cleaning import load_aligned_ohlcv
from quant_a.config import (
    FACTOR_CAPITAL,
    FACTOR_HOLDINGS,
    FACTOR_MAX_PRICE,
    LOT_SIZE,
    ORDERS_DIR,
    REPORTS_DIR,
)
from quant_a.factor_backtest import build_buy_list, rebalance_dates, run_factor_backtest
from quant_a.factor_strategy import compute_factor_panel, select_holdings_on
from quant_a.fundamentals import load_fundamental_factors, load_holder_factor
from quant_a.metrics import calculate_metrics
from quant_a.trade_rules import build_trade_eligibility
from quant_a.universe import load_mainboard_universe, load_stock_universe
from quant_a.walkforward import per_year_table, rolling_return_summary, summarize


def _benchmark_returns(close_matrix: pd.DataFrame, candidate_mask: pd.DataFrame) -> pd.Series:
    # 公平基准 = 月度等权持有【全部合格股】（同样月调、但不选股）。
    # 策略相对它的超额 = 纯粹的"选股"能力。月调让赢家在月内复利，口径与策略一致。
    # 个别脏价格(0→正)会让 pct_change 出 inf、cumprod 炸成无穷，先把 inf 收益清成 0（与 cs_pipeline 一致）。
    daily = close_matrix.pct_change(fill_method=None).replace([float("inf"), float("-inf")], 0.0)
    rebal = rebalance_dates(close_matrix.index)
    weights = pd.DataFrame(0.0, index=close_matrix.index, columns=close_matrix.columns)
    for date in rebal:
        eligible = candidate_mask.loc[date]
        names = eligible[eligible].index
        if len(names) > 0:
            weights.loc[date, names] = 1.0 / len(names)
    held = weights.loc[rebal].reindex(close_matrix.index).ffill().fillna(0.0)
    return (held.shift(1) * daily).sum(axis=1).fillna(0.0)


def _setup_cjk_font() -> None:
    import matplotlib
    import matplotlib.font_manager as fm

    for font in ["Heiti TC", "Songti SC", "Arial Unicode MS", "PingFang SC", "STHeiti"]:
        if any(font in name.name for name in fm.fontManager.ttflist):
            matplotlib.rcParams["font.sans-serif"] = [font]
            break
    matplotlib.rcParams["axes.unicode_minus"] = False


def _save_charts(equity_curve: pd.Series, benchmark_curve: pd.Series) -> dict[str, Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _setup_cjk_font()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(equity_curve.index, equity_curve.values, color="#1f77b4", lw=1.8, label="低波动多因子策略")
    ax.plot(benchmark_curve.index, benchmark_curve.values, color="black", lw=1.2, label="等权买入持有基准")
    ax.axhline(1.0, color="gray", ls=":", lw=0.8)
    ax.set_title("低波动多因子 vs 基准（20万本金，整手）")
    ax.set_ylabel("净值"); ax.grid(alpha=0.3); ax.legend()
    fig.tight_layout()
    equity_path = REPORTS_DIR / "factor_equity.png"
    fig.savefig(equity_path, dpi=150); plt.close(fig)

    drawdown = equity_curve / equity_curve.cummax() - 1.0
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.fill_between(drawdown.index, drawdown.values, 0, color="salmon", alpha=0.4)
    ax.plot(drawdown.index, drawdown.values, color="firebrick", lw=1.2)
    ax.set_title("策略回撤"); ax.set_ylabel("回撤"); ax.grid(alpha=0.3)
    fig.tight_layout()
    dd_path = REPORTS_DIR / "factor_drawdown.png"
    fig.savefig(dd_path, dpi=150); plt.close(fig)

    return {"equity": equity_path, "drawdown": dd_path}


def run_factor_pipeline(
    capital: float | None = None,
    holdings: int | None = None,
    universe: str = "csi1000",
    walkforward: bool = False,
) -> dict[str, object]:
    cap = capital if capital is not None else FACTOR_CAPITAL
    k = holdings or FACTOR_HOLDINGS

    if universe == "mainboard":
        universe_frame = load_mainboard_universe()  # 全主板，消除指数成分股的幸存者偏差
    else:
        universe_frame = load_stock_universe()
    names = dict(zip(universe_frame["symbol"].astype(str).str.zfill(6), universe_frame["name"].astype(str)))
    symbols = [s for s in names if cache_exists(s)]
    if not symbols:
        raise RuntimeError("本地无缓存，请先运行 fetch_universe.py / fetch_mainboard.py 抓数")

    price = load_aligned_ohlcv(symbols)
    close_m, high_m, low_m, vol_m = price["close"], price["high"], price["low"], price["volume"]
    eligibility = build_trade_eligibility(
        close_matrix=close_m, high_matrix=high_m, low_matrix=low_m, volume_matrix=vol_m, stock_metadata=pd.DataFrame()
    )
    candidate = eligibility["candidate_mask"] & (close_m < FACTOR_MAX_PRICE)

    fundamentals = load_fundamental_factors(close_m)  # 价值/质量因子（报告期+120天滞后）
    panel = compute_factor_panel(close_m, fundamentals=fundamentals)
    panel["holders"] = load_holder_factor(close_m)  # 第5因子:股东人数(有数据才生效,否则中性)
    backtest = run_factor_backtest(close_m, candidate, capital=cap, holdings=k, panel=panel)
    metrics = calculate_metrics(backtest["returns"], backtest["equity_curve"])

    benchmark_returns = _benchmark_returns(close_m, candidate)
    benchmark_curve = (1.0 + benchmark_returns).cumprod()
    benchmark_metrics = calculate_metrics(benchmark_returns, benchmark_curve)

    latest_date = close_m.index[-1]
    picks = select_holdings_on(latest_date, panel, candidate, k, require_full=False)
    buy_list = build_buy_list(latest_date, picks, close_m.loc[latest_date], cap, LOT_SIZE, names)

    ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    order_path = ORDERS_DIR / "factor_holdings.csv"
    buy_list.to_csv(order_path, index=False)
    charts = _save_charts(backtest["equity_curve"], benchmark_curve)

    result: dict[str, object] = {
        "universe": universe,
        "capital": cap,
        "holdings": k,
        "n_symbols": len(symbols),
        "date_range": (close_m.index.min(), latest_date),
        "metrics": metrics,
        "benchmark_metrics": benchmark_metrics,
        "avg_cash_pct": float((backtest["cash"] / backtest["equity_value"]).mean()),
        "rolling12m": rolling_return_summary(backtest["returns"]),
        "buy_list": buy_list,
        "order_path": order_path,
        "charts": charts,
    }

    if walkforward:
        per_year = per_year_table(backtest["returns"], benchmark_returns)
        result["walkforward"] = {"per_year": per_year, "summary": summarize(per_year)}

    return result


def _print_metric_row(label: str, m: dict[str, float]) -> None:
    print(f"  {label:14s} 总收益 {m['total_return']:+8.1%} | 年化 {m['annualized_return']:+6.1%} | "
          f"回撤 {m['max_drawdown']:6.1%} | 夏普 {m['sharpe']:.2f}")


def _print_walkforward(walk: dict[str, object]) -> None:
    per_year = walk["per_year"]
    summary = walk["summary"]
    print("📅 逐年滚动验证（策略 vs 当时合格股票等权基准）：")
    print(f"  {'年份':<6}{'策略收益':>9}{'夏普':>7}{'回撤':>9}{'基准收益':>10}{'超额':>9}  胜")
    for _, r in per_year.iterrows():
        flag = "✓" if r["win"] else "✗"
        print(f"  {int(r['year']):<6}{r['strat_return']:>+8.1%}{r['strat_sharpe']:>7.2f}{r['strat_mdd']:>+8.1%}"
              f"{r['bench_return']:>+9.1%}{r['excess']:>+8.1%}   {flag}")
    print(f"  → {summary['years']} 年里赢基准 {summary['win_rate']:.0%}，年均超额 {summary['avg_excess']:+.1%}，最差一年超额 {summary['worst_year_excess']:+.1%}")
    print()


def main() -> None:
    import sys

    universe = "mainboard" if "--mainboard" in sys.argv else "csi1000"
    walkforward = "--walkforward" in sys.argv
    result = run_factor_pipeline(universe=universe, walkforward=walkforward)
    start, end = result["date_range"]
    uni_cn = {"mainboard": "全主板(去幸存者偏差)", "csi1000": "中证1000主板"}[result["universe"]]
    print(f"低波动多因子组合 | 选股池: {uni_cn} | {result['n_symbols']} 只 | {start:%Y-%m-%d} ~ {end:%Y-%m-%d}")
    print(f"本金 {result['capital']:,.0f} 元 | 持仓 {result['holdings']} 只 | 100股整手 | 平均闲置现金 {result['avg_cash_pct']:.0%}")
    print()
    _print_metric_row("本策略", result["metrics"])
    _print_metric_row("等权基准", result["benchmark_metrics"])
    rs = result["rolling12m"]
    print(f"  滚动12月收益: 中位 {rs['median']:+.1%} | 最好 {rs['best']:+.1%} | 最差 {rs['worst']:+.1%} | 为正占比 {rs['pct_positive']:.0%}")
    print()

    if "walkforward" in result:
        _print_walkforward(result["walkforward"])

    buy_list = result["buy_list"]
    print(f"📋 本月下单清单（{end:%Y-%m-%d} 收盘价，全现金建仓）：投入 {buy_list.attrs['invested']:,.0f} 元，剩余现金 {buy_list.attrs['cash_left']:,.0f} 元")
    print(buy_list.head(10).to_string(index=False))
    if len(buy_list) > 10:
        print(f"  ...（共 {len(buy_list)} 只，完整见 CSV）")
    print(f"\n清单已存：{result['order_path']}")
    print(f"净值图：{result['charts']['equity']} | 回撤图：{result['charts']['drawdown']}")


if __name__ == "__main__":
    main()
