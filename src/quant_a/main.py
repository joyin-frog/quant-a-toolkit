from pathlib import Path

import pandas as pd

from quant_a.backtest import run_backtest
from quant_a.cache import cache_exists, save_cached_bars
from quant_a.cleaning import load_aligned_closes
from quant_a.config import BACKTEST_ENGINE, DATA_DIR, ORDERS_DIR, SYMBOLS, UNIVERSE
from quant_a.data_fetch import fetch_bars
from quant_a.factor_analysis import run_factor_analysis
from quant_a.metrics import calculate_metrics
from quant_a.orders import generate_order_table, save_order_table
from quant_a.plotting import save_report_charts
from quant_a.strategy import build_target_weights


# 刷新所有标的的本地缓存；如果 live 抓数失败但本地已有缓存，则记录 warning 并继续跑后续流程。
def refresh_data(universe: dict[str, str]) -> tuple[list[Path], list[str]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    warnings = []
    for symbol, kind in universe.items():
        try:
            bars = fetch_bars(symbol, kind)
            saved_paths.append(save_cached_bars(symbol, bars))
        except Exception as error:
            if not cache_exists(symbol):
                raise RuntimeError(f"Failed to fetch {symbol} and no cache is available") from error
            warnings.append(f"{symbol}: using cached data because refresh failed ({error})")
    return saved_paths, warnings


# 这是整条研究流水线的总控入口：抓数/读缓存/生成权重/回测/指标/订单/图表都在这里串起来。
# 返回值是下游 CLI、Notebook 或未来接 Web 界面时可以复用的统一结果契约。
def run_pipeline(current_holdings: dict[str, float] | None = None, engine: str | None = None) -> dict[str, object]:
    selected_engine = engine or BACKTEST_ENGINE
    ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    _, warnings = refresh_data(UNIVERSE)
    close_matrix = load_aligned_closes(SYMBOLS)
    factor_analysis = run_factor_analysis(close_matrix)
    target_weights = build_target_weights(close_matrix)
    backtest_result = run_backtest(close_matrix, target_weights, engine=selected_engine)
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
