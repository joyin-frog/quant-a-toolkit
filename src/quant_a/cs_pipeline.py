"""核心-卫星组合总控：沪深300分散核心 + AI 产业链龙头卫星。

跑法：PYTHONPATH=src .venv/bin/python -m quant_a.cs_pipeline
输出：orders/cs_holdings.csv（核心+AI卫星下单清单）、reports/cs_equity.png。

前置数据：data/hs300_mainboard.csv（沪深300主板清单）+ 各股日线/财报缓存。
行业分类 data/industry_map.csv 可选（缺失时核心行业上限退化为只卡金融三类）。
"""

from __future__ import annotations

import pandas as pd

from quant_a.cache import cache_exists
from quant_a.cleaning import load_aligned_ohlcv
from quant_a.config import AI_SATELLITE_WEIGHT, CS_CORE_HOLDINGS, DATA_DIR, FACTOR_CAPITAL, LOT_SIZE, ORDERS_DIR, REPORTS_DIR
from quant_a.factor_strategy import compute_factor_panel, factor_scores_on  # noqa: F401
from quant_a.fundamentals import load_fundamental_factors, load_holder_factor
from quant_a.metrics import calculate_metrics
from quant_a.portfolio import (
    AI_NAMES,
    ai_symbols,
    build_cs_buy_list,
    industry_label,
    run_core_satellite_backtest,
    select_ai_leaders,
    select_core,
)
from quant_a.trade_rules import build_trade_eligibility
from quant_a.walkforward import rolling_return_summary

HS300_PATH = DATA_DIR / "hs300_mainboard.csv"
INDUSTRY_PATH = DATA_DIR / "industry_map.csv"


def _load_industry_map() -> dict[str, str]:
    if not INDUSTRY_PATH.exists():
        return {}
    try:
        frame = pd.read_csv(INDUSTRY_PATH, dtype=str)
        return dict(zip(frame["symbol"].str.zfill(6), frame["industry"]))
    except Exception:
        return {}


def _save_equity_chart(equity_curve: pd.Series, benchmark_curve: pd.Series):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    for font in ["Heiti TC", "Songti SC", "Arial Unicode MS", "PingFang SC", "STHeiti"]:
        if any(font in n.name for n in fm.fontManager.ttflist):
            matplotlib.rcParams["font.sans-serif"] = [font]
            break
    matplotlib.rcParams["axes.unicode_minus"] = False
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(equity_curve.index, equity_curve.values, color="#1f77b4", lw=1.8, label="核心+AI卫星")
    ax.plot(benchmark_curve.index, benchmark_curve.values, color="black", lw=1.2, label="沪深300主板等权基准")
    ax.axhline(1.0, color="gray", ls=":", lw=0.8)
    ax.set_title("核心-卫星组合 vs 基准（20万本金，整手）")
    ax.set_ylabel("净值"); ax.grid(alpha=0.3); ax.legend()
    fig.tight_layout()
    path = REPORTS_DIR / "cs_equity.png"
    fig.savefig(path, dpi=150); plt.close(fig)
    return path


def run_cs_pipeline(capital: float | None = None, core_holdings: int | None = None, ai_weight: float | None = None) -> dict[str, object]:
    cap = capital if capital is not None else FACTOR_CAPITAL
    kc = core_holdings or CS_CORE_HOLDINGS
    aw = ai_weight if ai_weight is not None else AI_SATELLITE_WEIGHT

    if not HS300_PATH.exists():
        raise RuntimeError("缺少 data/hs300_mainboard.csv，请先生成沪深300主板清单并抓数")
    hs = pd.read_csv(HS300_PATH, dtype=str)
    hs["symbol"] = hs["symbol"].str.zfill(6)
    names = dict(zip(hs["symbol"], hs["name"].astype(str)))
    names.update(AI_NAMES)
    core_universe = {s for s in hs["symbol"] if cache_exists(s)}
    all_syms = sorted(core_universe | {c for c in ai_symbols() if cache_exists(c)})

    price = load_aligned_ohlcv(all_syms)
    close_m, high_m, low_m, vol_m = price["close"], price["high"], price["low"], price["volume"]
    candidate = build_trade_eligibility(
        close_matrix=close_m, high_matrix=high_m, low_matrix=low_m, volume_matrix=vol_m, stock_metadata=pd.DataFrame()
    )["candidate_mask"] & (close_m < 500.0)
    panel = compute_factor_panel(close_m, fundamentals=load_fundamental_factors(close_m))
    panel["holders"] = load_holder_factor(close_m)  # 第5因子:股东人数(筹码集中)
    industry_map = _load_industry_map()

    backtest = run_core_satellite_backtest(
        close_m, candidate, core_universe, names, panel=panel, capital=cap,
        core_holdings=kc, ai_weight=aw, industry_map=industry_map,
    )
    metrics = calculate_metrics(backtest["returns"], backtest["equity_curve"])

    # 基准：沪深300主板核心池 月度等权全合格股
    from quant_a.factor_backtest import rebalance_dates
    # 个别脏价格(0→正)会让 pct_change 出 inf、cumprod 炸成无穷，先把 inf 收益清成 0。
    daily = close_m.pct_change(fill_method=None).replace([float("inf"), float("-inf")], 0.0)
    reb = rebalance_dates(close_m.index)
    weights = pd.DataFrame(0.0, index=close_m.index, columns=close_m.columns)
    for d in reb:
        eligible = candidate.loc[d] & pd.Series([c in core_universe for c in close_m.columns], index=close_m.columns)
        held = eligible[eligible].index
        if len(held) > 0:
            weights.loc[d, held] = 1.0 / len(held)
    bench_ret = (weights.loc[reb].reindex(close_m.index).ffill().fillna(0.0).shift(1) * daily).sum(axis=1).fillna(0.0)
    bench_curve = (1.0 + bench_ret).cumprod()
    bench_metrics = calculate_metrics(bench_ret, bench_curve)

    # 下单清单：用【最新一个"核心数据齐全"的交易日】（候选≥100只，避开各股结尾日期参差的尾部）。
    # AI 子链有几条算几条，不强求全覆盖——强求会把日期拖回很久以前；缺的子链当月就不配卫星仓。
    n_themes = len(__import__("quant_a.portfolio", fromlist=["AI_CHAIN"]).AI_CHAIN)
    ai_budget = aw * cap / n_themes if aw > 0 else 0.0
    good = candidate.sum(axis=1)
    latest = good[good >= 100].index[-1]
    ai = select_ai_leaders(latest, panel, candidate, price_row=close_m.loc[latest], budget_per_name=ai_budget)
    core = select_core(latest, panel, candidate, core_universe, kc, names, exclude=set(ai.values()), industry_map=industry_map)
    buy_list = build_cs_buy_list(latest, core, ai, close_m.loc[latest], cap, aw, names, LOT_SIZE)
    ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    order_path = ORDERS_DIR / "cs_holdings.csv"
    buy_list.to_csv(order_path, index=False)
    snap_dir = ORDERS_DIR / "snapshots"; snap_dir.mkdir(parents=True, exist_ok=True)
    buy_list.to_csv(snap_dir / f"{latest:%Y-%m-%d}_cs.csv", index=False)  # 留档：事后给执行打分要对照"当时该买什么"
    chart = _save_equity_chart(backtest["equity_curve"], bench_curve)

    from collections import Counter
    core_sectors = Counter(industry_label(s, names, industry_map) for s in core)
    return {
        "capital": cap, "core_holdings": kc, "ai_weight": aw,
        "date_range": (close_m.index.min(), latest),
        "metrics": metrics, "benchmark_metrics": bench_metrics,
        "buy_list": buy_list, "order_path": order_path, "chart": chart,
        "core_sectors": {k: v for k, v in core_sectors.items() if not k.startswith("X")},
        "avg_cash_pct": float((backtest["cash"] / backtest["equity_value"]).mean()),
        "rolling12m": rolling_return_summary(backtest["returns"]),
        "equity_curve": backtest["equity_curve"],
        "benchmark_curve": bench_curve,
    }


def main() -> None:
    r = run_cs_pipeline()
    start, end = r["date_range"]
    print(f"核心-卫星组合 | 沪深300主板核心 + AI产业链卫星 | {start:%Y-%m-%d} ~ {end:%Y-%m-%d}")
    print(f"本金 {r['capital']:,.0f} | 核心 {r['core_holdings']} 只 + AI卫星 {r['ai_weight']:.0%} | 平均闲置现金 {r['avg_cash_pct']:.0%}")
    m, b = r["metrics"], r["benchmark_metrics"]
    print(f"  本组合   总收益 {m['total_return']:+.1%} | 年化 {m['annualized_return']:+.1%} | 回撤 {m['max_drawdown']:.1%} | 夏普 {m['sharpe']:.2f}")
    print(f"  等权基准 总收益 {b['total_return']:+.1%} | 年化 {b['annualized_return']:+.1%} | 回撤 {b['max_drawdown']:.1%} | 夏普 {b['sharpe']:.2f}")
    print(f"  核心行业分布(金融已限): {r['core_sectors']}")
    rs = r["rolling12m"]
    print(f"  滚动12月收益: 中位 {rs['median']:+.1%} | 最好 {rs['best']:+.1%} | 最差 {rs['worst']:+.1%} | 为正占比 {rs['pct_positive']:.0%}")
    bl = r["buy_list"]
    print(f"\n📋 本月下单清单（投入 {bl.attrs['invested']:,.0f} / 剩 {bl.attrs['cash_left']:,.0f}）：")
    print(bl.to_string(index=False))
    print(f"\n清单已存：{r['order_path']} | 净值图：{r['chart']}")


if __name__ == "__main__":
    main()
