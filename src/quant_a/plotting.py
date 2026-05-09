from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from quant_a.config import REPORTS_DIR


# 图表层只消费回测结果，不参与策略或回测逻辑；未来切到 notebook/html report 时优先替换这里。
def _save_equity_curve(equity_curve: pd.Series, output_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12, 5))
    equity_curve.plot(ax=ax, color="navy", linewidth=1.8)
    ax.set_title("Strategy Equity Curve")
    ax.set_xlabel("Date")
    ax.set_ylabel("Net Asset Value")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def _save_drawdown_curve(equity_curve: pd.Series, output_path: Path) -> Path:
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    fig, ax = plt.subplots(figsize=(12, 5))
    drawdown.plot(ax=ax, color="firebrick", linewidth=1.5)
    ax.fill_between(drawdown.index, drawdown.values, 0, color="salmon", alpha=0.3)
    ax.set_title("Strategy Drawdown")
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def _save_holdings_weights(weights: pd.DataFrame, output_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12, 6))
    weights.plot.area(ax=ax, stacked=True, alpha=0.75)
    ax.set_title("Holdings Weight Over Time")
    ax.set_xlabel("Date")
    ax.set_ylabel("Weight")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", ncol=2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


# backtest_result 的 key 约定来自 backtest.py；只要那个返回 schema 不变，这里的报表层就能继续复用。
def save_report_charts(backtest_result: dict[str, pd.DataFrame | pd.Series]) -> dict[str, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    equity_curve = backtest_result["equity_curve"]
    actual_weights = backtest_result["actual_weights"]

    return {
        "equity_curve": _save_equity_curve(equity_curve, REPORTS_DIR / "equity_curve.png"),
        "drawdown": _save_drawdown_curve(equity_curve, REPORTS_DIR / "drawdown.png"),
        "holdings": _save_holdings_weights(actual_weights, REPORTS_DIR / "holdings_weights.png"),
    }
