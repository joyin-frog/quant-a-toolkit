"""5/20 金叉策略总控：选股 → 金叉信号 → 短线/波段两套回测 → 指标对比。

只读本地缓存（用 fetch_universe.py 先抓数）。不重写旧的组合轮动流水线（main.py），
这是并行的第二套研究入口。
"""

from __future__ import annotations

import pandas as pd

from quant_a.cache import cache_exists, load_stock_metadata_cache
from quant_a.cleaning import load_aligned_ohlcv
from quant_a.event_backtest import run_event_backtest
from quant_a.metrics import calculate_metrics
from quant_a.signals import detect_entry_trades
from quant_a.trade_rules import build_trade_eligibility
from quant_a.universe import load_stock_universe


def _trade_stats(trades: pd.DataFrame) -> dict[str, float]:
    if trades is None or trades.empty:
        return {"n_trades": 0, "trade_win_rate": 0.0, "avg_return": 0.0, "median_hold_days": 0.0}
    rets = trades["return"].astype(float)
    hold = (pd.to_datetime(trades["exit_date"]) - pd.to_datetime(trades["entry_date"])).dt.days
    return {
        "n_trades": int(len(trades)),
        "trade_win_rate": float((rets > 0).mean()),
        "avg_return": float(rets.mean()),
        "median_hold_days": float(hold.median()),
    }


def run_gc_pipeline(
    modes: tuple[str, ...] = ("short", "swing"),
    entry_fill: str = "open",
) -> dict[str, object]:
    universe = load_stock_universe()
    symbols = universe["symbol"].astype(str).str.zfill(6).tolist()
    cached = [s for s in symbols if cache_exists(s)]
    if not cached:
        raise RuntimeError("中证1000 主板个股本地无缓存，请先运行 fetch_universe.py 抓数")

    price = load_aligned_ohlcv(cached)
    close_m, high_m, low_m, open_m, vol_m = (
        price["close"], price["high"], price["low"], price["open"], price["volume"]
    )

    try:
        metadata = load_stock_metadata_cache()
    except Exception:
        metadata = pd.DataFrame()

    eligibility = build_trade_eligibility(
        close_matrix=close_m,
        high_matrix=high_m,
        low_matrix=low_m,
        volume_matrix=vol_m,
        stock_metadata=metadata,
    )

    entries = detect_entry_trades(
        open_matrix=open_m,
        high_matrix=high_m,
        low_matrix=low_m,
        close_matrix=close_m,
        candidate_mask=eligibility["candidate_mask"],
        entry_fill=entry_fill,
    )

    results: dict[str, object] = {
        "n_symbols": len(cached),
        "date_range": (close_m.index.min(), close_m.index.max()),
        "n_entry_signals": int(len(entries)),
        "entry_fill": entry_fill,
        "entries": entries,
        "by_mode": {},
    }

    for mode in modes:
        bt = run_event_backtest(
            open_matrix=open_m,
            high_matrix=high_m,
            low_matrix=low_m,
            close_matrix=close_m,
            entry_trades=entries,
            mode=mode,
        )
        metrics = calculate_metrics(bt["returns"], bt["equity_curve"])
        results["by_mode"][mode] = {
            "metrics": metrics,
            "trade_stats": _trade_stats(bt["trades"]),
            "equity_curve": bt["equity_curve"],
            "trades": bt["trades"],
        }

    return results


def print_report(results: dict[str, object]) -> None:
    start, end = results["date_range"]
    fill_cn = {"low": "当天最低价(乐观/事后价)", "open": "当天开盘价(现实)", "mid": "(开盘+最低)/2"}
    print(f"选股池: {results['n_symbols']} 只主板个股 | 区间: {start:%Y-%m-%d} ~ {end:%Y-%m-%d}")
    print(f"成交口径: {fill_cn.get(results.get('entry_fill', 'low'))}")
    print(f"确认进场信号数: {results['n_entry_signals']}")
    print()
    mode_cn = {"short": "短线 (5日线+8%止盈)", "swing": "波段 (20日线)"}
    for mode, data in results["by_mode"].items():
        m = data["metrics"]
        t = data["trade_stats"]
        print(f"===== {mode_cn.get(mode, mode)} =====")
        print(f"  总收益:     {m['total_return']:+.2%}")
        print(f"  年化收益:   {m['annualized_return']:+.2%}")
        print(f"  最大回撤:   {m['max_drawdown']:.2%}")
        print(f"  年化波动:   {m['volatility']:.2%}")
        print(f"  夏普:       {m['sharpe']:.2f}")
        print(f"  Calmar:     {m['calmar']:.2f}")
        print(f"  完整交易数: {t['n_trades']}  胜率: {t['trade_win_rate']:.1%}  "
              f"单笔均收益: {t['avg_return']:+.2%}  中位持有: {t['median_hold_days']:.0f} 天")
        print()


def main() -> None:
    # 默认同时跑两种成交口径：low=用户口述"买当天低价"（偏乐观），open=现实可执行。
    # 两者差距即"买在最低点"这个事后假设带来的虚假收益，必须摆在一起看。
    for fill in ("low", "open"):
        print("=" * 64)
        results = run_gc_pipeline(entry_fill=fill)
        print_report(results)


if __name__ == "__main__":
    main()
