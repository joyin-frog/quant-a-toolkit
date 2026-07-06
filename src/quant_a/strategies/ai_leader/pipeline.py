"""主板 AI 产业链龙头策略：每条子链选 1 只买得起的动量龙头，月度调仓、整手交易。

复用核心-卫星的选股与回测机制（ai_weight=1.0、无核心仓），只换股票池：
图片整理的 AI 算力全产业链 20 条子链，过滤到主板后约 18 条链 40+ 只。

⚠️ 信仰仓口径：池子按当下认知人工圈定，回测含幸存者偏差，实盘表现会打折。
"""

from __future__ import annotations

import pandas as pd

from quant_a.benchmarks import monthly_equal_weight_returns
from quant_a.cache import cache_exists
from quant_a.cleaning import load_aligned_ohlcv
from quant_a.config import ORDERS_DIR, REPORTS_DIR
from quant_a.factor_strategy import compute_factor_panel
from quant_a.metrics import calculate_metrics
from quant_a.platform.contracts import StrategyResult
from quant_a.plotting import save_equity_vs_benchmark
from quant_a.portfolio import build_cs_buy_list, run_core_satellite_backtest, select_ai_leaders
from quant_a.strategies.ai_leader.pool import mainboard_chains
from quant_a.trade_rules import build_trade_eligibility


def run_ai_leader(capital: float = 200_000, account: str = "", locked: str = "") -> StrategyResult:
    if capital <= 0:
        raise ValueError("capital must be positive")
    chains, names, dropped = mainboard_chains()
    warnings: list[str] = [
        "AI产业链+机器人池按当下认知人工圈定（2026-07），回测含幸存者偏差，属信仰仓口径。",
        f"账户无创业板/科创板权限：剔除 {len(dropped)} 只非主板/存疑标的：{'、'.join(dropped)}。",
    ]

    available: dict[str, list[str]] = {}
    missing: list[str] = []
    for chain, codes in chains.items():
        cached = [code for code in codes if cache_exists(code)]
        missing.extend(f"{chain}/{names[code]}({code})" for code in codes if code not in cached)
        if cached:
            available[chain] = cached
    if not available:
        raise RuntimeError("AI池主板标的本地都无行情缓存，请先抓数（可用 refresh_cs.py 的抓数机制或 fetch_universe.py）")
    if missing:
        warnings.append(f"以下标的无本地行情缓存、本次未参与：{'、'.join(missing)}。建议抓数后重跑。")
    empty_chains = [chain for chain in chains if chain not in available]
    no_mainboard = [chain for chain in ("AI芯片",) if chain not in chains]
    if no_mainboard:
        warnings.append(f"子链 {'、'.join(no_mainboard)} 在主板没有任何标的（全为科创板），该链无法覆盖。")
    if empty_chains:
        warnings.append(f"子链 {'、'.join(empty_chains)} 的主板标的均无缓存，本次未覆盖。")

    symbols = sorted({code for codes in available.values() for code in codes})
    ohlcv = load_aligned_ohlcv(symbols)
    close = ohlcv["close"]
    # 各股缓存结尾日期参差（含盘中半根K线）时，矩阵尾部大面积 NaN 会让最新调仓日选股塌掉；
    # 截断到最后一个"≥80% 股票有收盘价"的交易日。
    coverage = close.notna().mean(axis=1)
    solid = coverage[coverage >= 0.8]
    if solid.empty:
        raise RuntimeError("AI池对齐后没有覆盖率≥80%的交易日，缓存质量异常")
    end = solid.index[-1]
    if end < close.index[-1]:
        warnings.append(f"各股数据结尾参差：清单基准日截到 {end:%Y-%m-%d}（此后覆盖率不足80%）。建议刷新全部缓存到同一天。")
    ohlcv = {key: frame.loc[:end] for key, frame in ohlcv.items()}
    close = ohlcv["close"]
    eligibility = build_trade_eligibility(
        close_matrix=close,
        high_matrix=ohlcv["high"],
        low_matrix=ohlcv["low"],
        volume_matrix=ohlcv["volume"],
        stock_metadata=pd.DataFrame(),
    )
    candidate = eligibility["candidate_mask"]
    panel = compute_factor_panel(close)

    backtest = run_core_satellite_backtest(
        close_matrix=close,
        candidate_mask=candidate,
        core_universe=set(),  # 无核心仓
        names=names,
        panel=panel,
        capital=capital,
        core_holdings=0,
        ai_weight=1.0,
        chains=available,
    )
    metrics = calculate_metrics(backtest["returns"], backtest["equity_curve"])

    benchmark_returns = monthly_equal_weight_returns(close, candidate)
    benchmark_curve = (1.0 + benchmark_returns).cumprod()
    benchmark_metrics = calculate_metrics(benchmark_returns, benchmark_curve)

    latest = close.index[-1]
    price_row = close.ffill().loc[latest]
    budget = capital / len(available)
    leaders = select_ai_leaders(latest, panel, candidate, price_row=price_row, budget_per_name=budget, chains=available)
    buy_list = build_cs_buy_list(latest, [], leaders, price_row, capital, 1.0, names, ai_sleeve="AI", n_chains=len(available))

    ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    order_path = ORDERS_DIR / "ai_leader_holdings.csv"
    buy_list.to_csv(order_path, index=False)
    chart = save_equity_vs_benchmark(
        backtest["equity_curve"],
        benchmark_curve,
        REPORTS_DIR / "ai_leader" / "equity.png",
        "AI+机器人主板龙头 vs 股票池等权基准",
        strategy_label="AI+机器人龙头",
        benchmark_label="股票池等权基准",
    )

    uncovered = sorted(set(available) - {chain for chain in leaders})
    if uncovered:
        warnings.append(f"最新调仓日子链 {'、'.join(uncovered)} 无合格/买得起的标的，留现金。")

    diagnostics_extra: dict[str, object] = {}
    if account:
        from quant_a.transition import build_transition

        locked_codes = [c.strip().zfill(6) for c in locked.split(",") if c.strip()]
        target = list(leaders.values()) + [c for c in locked_codes if c not in leaders.values()]
        transition = build_transition(account, target, names, locked=locked_codes)
        transition["summary"]["as_of"] = f"{latest:%Y-%m-%d}"
        diagnostics_extra["transition"] = transition["summary"]
        diagnostics_extra["transition_orders"] = transition["orders"].to_dict(orient="records")
        warnings.extend(transition["summary"]["warnings"])

    return StrategyResult(
        strategy_id="ai_leader",
        name="AI+机器人主板龙头",
        params={"capital": capital, **({"account": account} if account else {}), **({"locked": locked} if locked else {})},
        date_range=(close.index.min(), latest),
        metrics=metrics,
        benchmark_metrics=benchmark_metrics,
        equity_curve=backtest["equity_curve"],
        benchmark_curve=benchmark_curve,
        holdings=buy_list,
        artifacts={"orders": order_path, "chart": chart},
        warnings=warnings,
        diagnostics={
            "n_symbols": len(symbols),
            "n_chains": len(available),
            "chains_covered_latest": len(leaders),
            "leaders_latest": {chain: f"{names[code]}({code})" for chain, code in leaders.items()},
            "avg_cash_pct": float((backtest["cash"] / backtest["equity_value"]).mean()),
            **diagnostics_extra,
        },
    )
