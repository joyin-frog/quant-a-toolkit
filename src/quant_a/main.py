from pathlib import Path

import pandas as pd

from quant_a.backtest import run_backtest
from quant_a.cache import (
    DATA_DIR,
    cache_exists,
    load_stock_metadata_cache,
    save_cached_bars,
    save_stock_metadata_cache,
)
from quant_a.cleaning import load_aligned_ohlcv
from quant_a.config import BACKTEST_ENGINE, ORDERS_DIR
from quant_a.data_fetch import fetch_bars, fetch_stock_metadata
from quant_a.factor_analysis import run_factor_analysis
from quant_a.metrics import calculate_metrics
from quant_a.orders import generate_order_table, save_order_table
from quant_a.plotting import save_report_charts
from quant_a.strategy import build_target_weights
from quant_a.trade_rules import build_trade_eligibility
from quant_a.universe import load_stock_universe


def _discover_cached_stock_symbols() -> list[str]:
    symbols = []
    for path in DATA_DIR.glob("[0-9][0-9][0-9][0-9][0-9][0-9].csv"):
        symbol = path.stem
        if len(symbol) == 6 and symbol.isdigit() and symbol[0] in {"0", "2", "3", "6", "8"}:
            symbols.append(symbol)
    return sorted(set(symbols))


# 刷新所有标的的本地缓存；如果 live 抓数失败但本地已有缓存，则记录 warning 并继续跑后续流程。
def refresh_data(universe: pd.DataFrame) -> tuple[list[Path], list[str]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    warnings: list[str] = []
    existing_metadata = pd.DataFrame()
    try:
        existing_metadata = load_stock_metadata_cache()
    except Exception:
        existing_metadata = pd.DataFrame()
    existing_symbols = set(existing_metadata["symbol"].astype(str).str.zfill(6)) if not existing_metadata.empty else set()
    fetched_metadata_rows: list[dict[str, object]] = []

    for symbol in universe["symbol"].astype(str).str.zfill(6):
        try:
            bars = fetch_bars(symbol, "stock")
            saved_paths.append(save_cached_bars(symbol, bars))
        except Exception as error:
            if not cache_exists(symbol):
                warnings.append(f"{symbol}: skipped because refresh failed and no cache is available ({error})")
            else:
                warnings.append(f"{symbol}: using cached data because refresh failed ({error})")

        try:
            fetched_metadata_rows.append(fetch_stock_metadata(symbol))
        except Exception as error:
            if symbol not in existing_symbols:
                warnings.append(f"{symbol}: skipped metadata because refresh failed and no cache is available ({error})")
            else:
                warnings.append(f"{symbol}: using cached metadata because refresh failed ({error})")

    if fetched_metadata_rows:
        fetched_metadata = pd.DataFrame(fetched_metadata_rows)
        if not existing_metadata.empty:
            merged_metadata = pd.concat([existing_metadata, fetched_metadata], ignore_index=True)
        else:
            merged_metadata = fetched_metadata
        merged_metadata = merged_metadata.drop_duplicates(subset="symbol", keep="last")
        save_stock_metadata_cache(merged_metadata)

    if not saved_paths and not warnings:
        raise RuntimeError("No stock data could be refreshed")

    return saved_paths, warnings


# 这是整条研究流水线的总控入口：抓数/读缓存/生成权重/回测/指标/订单/图表都在这里串起来。
# 返回值保持统一 schema，方便 CLI、Notebook 或脚本复用。
def run_pipeline(
    current_holdings: dict[str, float] | None = None,
    engine: str | None = None,
    momentum_window: int | None = None,
    max_holdings: int | None = None,
    initial_cash: float | None = None,
) -> dict[str, object]:
    selected_engine = engine or BACKTEST_ENGINE
    if momentum_window is not None and momentum_window < 1:
        raise ValueError("momentum_window must be at least 1")
    if max_holdings is not None and not 1 <= max_holdings <= 300:
        raise ValueError("max_holdings must be between 1 and 300")
    if initial_cash is not None and initial_cash <= 0:
        raise ValueError("initial_cash must be greater than 0")

    ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    stock_universe = load_stock_universe()
    universe_symbols = stock_universe["symbol"].astype(str).str.zfill(6).tolist()
    cached_universe_symbols = [symbol for symbol in universe_symbols if cache_exists(symbol)]
    warnings: list[str] = []
    if cached_universe_symbols:
        _, refresh_warnings = refresh_data(stock_universe)
        warnings.extend(refresh_warnings)

    stock_symbols = cached_universe_symbols
    if not stock_symbols:
        cached_symbols = _discover_cached_stock_symbols()
        if cached_symbols:
            warnings.append(
                "No current CSI 300 constituents had local cache; falling back to existing cached stock CSVs"
            )
            stock_symbols = cached_symbols
    if not stock_symbols:
        raise RuntimeError("No cached stock data is available after refresh")
    price_frames = load_aligned_ohlcv(stock_symbols)
    close_matrix = price_frames["close"]
    try:
        trade_metadata = load_stock_metadata_cache()
    except Exception:
        trade_metadata = pd.DataFrame()
    eligibility = build_trade_eligibility(
        close_matrix=price_frames["close"],
        high_matrix=price_frames["high"],
        low_matrix=price_frames["low"],
        volume_matrix=price_frames["volume"],
        stock_metadata=trade_metadata,
    )
    factor_analysis = run_factor_analysis(
        close_matrix,
        momentum_window=momentum_window,
        candidate_mask=eligibility["candidate_mask"],
    )
    target_weights = build_target_weights(
        close_matrix,
        momentum_window=momentum_window,
        max_holdings=max_holdings,
        candidate_mask=eligibility["candidate_mask"],
    )
    backtest_result = run_backtest(
        close_matrix,
        target_weights,
        engine=selected_engine,
        initial_cash=initial_cash,
        can_buy=eligibility["can_buy"],
        can_sell=eligibility["can_sell"],
    )
    metrics = calculate_metrics(backtest_result["returns"], backtest_result["equity_curve"])
    order_table = generate_order_table(backtest_result["target_weights"], current_holdings=current_holdings)
    order_path = save_order_table(order_table)
    report_paths = save_report_charts(backtest_result)

    return {
        "engine": selected_engine,
        "close_matrix": close_matrix,
        "target_weights": target_weights,
        "factor_analysis": factor_analysis,
        "backtest": backtest_result,
        "metrics": metrics,
        "orders": order_table,
        "order_path": order_path,
        "report_paths": report_paths,
        "warnings": warnings,
    }


def print_metrics(metrics: dict[str, float]) -> None:
    printable = pd.Series(metrics).map(lambda value: round(value, 6))
    print(printable.to_string())


# CLI 入口只负责展示结果，不承担策略或回测逻辑。
def main() -> None:
    result = run_pipeline()
    if result["warnings"]:
        print("Warnings:")
        for warning in result["warnings"]:
            print(f"- {warning}")
        print()
    factor_warnings = result["factor_analysis"].get("warnings", [])
    if factor_warnings:
        print("Factor analysis warnings:")
        for warning in factor_warnings:
            print(f"- {warning}")
        print()
    print(f"Backtest engine: {result['engine']}")
    print_metrics(result["metrics"])
    print("\nReports:")
    for name, path in result["report_paths"].items():
        print(f"- {name}: {path}")
    print(f"\nLatest orders saved to {result['order_path']}")
    print(result["orders"].to_string(index=False))


if __name__ == "__main__":
    main()
