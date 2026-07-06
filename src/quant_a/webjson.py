"""网页 JSON 输出的共享工具：NaN/Inf 清洗与净值曲线下采样。

JS 的 JSON.parse 不认 NaN/Infinity，所有打给前端的数字必须先经 clean_number。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def clean_number(value) -> float | None:
    """NaN/Inf → None，其余四舍五入到 4 位。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if np.isfinite(number) else None


def monthly_curve(strategy: pd.Series, benchmark: pd.Series) -> list[dict[str, object]]:
    """策略/基准净值对齐后按月末取样，控制 JSON 体积。"""
    aligned = pd.concat([strategy.rename("strategy"), benchmark.rename("benchmark")], axis=1).ffill().dropna(how="all")
    monthly = aligned.resample("ME").last()
    return [
        {"date": date.strftime("%Y-%m"), "strategy": clean_number(row["strategy"]), "benchmark": clean_number(row["benchmark"])}
        for date, row in monthly.iterrows()
    ]
