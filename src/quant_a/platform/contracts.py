from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ParamSpec:
    """策略公开参数的声明：runner/网页按它组装参数，前端按它渲染控件。"""

    name: str
    kind: str  # "number" | "integer" | "choice"
    default: Any
    label: str = ""
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "kind": self.kind, "default": self.default, "label": self.label}
        if self.choices:
            out["choices"] = list(self.choices)
        for key in ("minimum", "maximum", "step"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


@dataclass(frozen=True)
class SleeveSpec:
    """策略的仓位分层：value 写库（与 holdings/trades 的 sleeve 字段一致），label 给人看。"""

    value: str
    label: str

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value, "label": self.label}


@dataclass
class StrategyResult:
    """所有策略对 CLI / Web / 对比层暴露的稳定结果契约。"""

    strategy_id: str
    name: str
    params: dict[str, Any]
    date_range: tuple[pd.Timestamp, pd.Timestamp]
    metrics: dict[str, float]
    benchmark_metrics: dict[str, float]
    equity_curve: pd.Series
    benchmark_curve: pd.Series
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    holdings: pd.DataFrame = field(default_factory=pd.DataFrame)
    artifacts: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        start, end = self.date_range
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "params": self.params,
            "date_range": [start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")],
            "metrics": self.metrics,
            "benchmark_metrics": self.benchmark_metrics,
            "artifacts": {key: str(path) for key, path in self.artifacts.items()},
            "warnings": self.warnings,
            "diagnostics": self.diagnostics,
        }
