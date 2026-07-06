from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from quant_a.config import REPORTS_DIR
from quant_a.platform.contracts import StrategyResult


def _json_default(value):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def save_strategy_result(result: StrategyResult) -> Path:
    """每个策略独立目录，避免多策略报告互相覆盖。

    带 universe 参数的策略再按股票池分子目录（reports/<strategy_id>/<universe>/），
    不同池子的结果互不覆盖。
    """
    variant = str(result.params.get("universe", "")).strip()
    output = REPORTS_DIR / result.strategy_id / variant if variant else REPORTS_DIR / result.strategy_id
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(result.summary(), ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    result.equity_curve.rename("strategy").to_csv(output / "equity.csv")
    result.benchmark_curve.rename("benchmark").to_csv(output / "benchmark.csv")
    if not result.trades.empty:
        result.trades.to_csv(output / "trades.csv", index=False)
    if not result.holdings.empty:
        result.holdings.to_csv(output / "holdings.csv", index=False)
    result.artifacts["summary"] = summary_path
    return summary_path


def load_cached_curves(strategy_id: str, max_age_hours: float = 24) -> dict[str, object] | None:
    """读取最近一次 save_strategy_result 的净值/基准曲线（含 universe 子目录），过期返回 None。

    行情按日更新，同一天内的绩效对比没必要每次都重跑几十秒的回测。
    """
    base = REPORTS_DIR / strategy_id
    candidates = [base] + [p for p in (base.glob("*/")) if p.is_dir()] if base.exists() else []
    best: Path | None = None
    for folder in candidates:
        summary = folder / "summary.json"
        if summary.exists() and (folder / "equity.csv").exists() and (folder / "benchmark.csv").exists():
            if best is None or summary.stat().st_mtime > (best / "summary.json").stat().st_mtime:
                best = folder
    if best is None:
        return None
    summary_path = best / "summary.json"
    if time.time() - summary_path.stat().st_mtime > max_age_hours * 3600:
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        equity = pd.read_csv(best / "equity.csv", index_col=0, parse_dates=True)["strategy"]
        benchmark = pd.read_csv(best / "benchmark.csv", index_col=0, parse_dates=True)["benchmark"]
    except (OSError, ValueError, KeyError):
        return None
    return {"params": summary.get("params", {}), "equity_curve": equity, "benchmark_curve": benchmark}
