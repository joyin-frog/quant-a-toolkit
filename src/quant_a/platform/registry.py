from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from quant_a.platform.contracts import ParamSpec, SleeveSpec, StrategyResult

StrategyRunner = Callable[..., StrategyResult]


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    name: str
    description: str
    runner: StrategyRunner
    params: tuple[ParamSpec, ...] = ()
    sleeves: tuple[SleeveSpec, ...] = ()

    def param_names(self) -> set[str]:
        return {spec.name for spec in self.params}

    def metadata(self) -> dict[str, Any]:
        """给 --list / 网页 /api/strategies 消费的 JSON 元数据。"""
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "params": [spec.to_dict() for spec in self.params],
            "sleeves": [spec.to_dict() for spec in self.sleeves],
        }


class StrategyRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, StrategyDefinition] = {}

    def register(self, definition: StrategyDefinition) -> None:
        if definition.strategy_id in self._definitions:
            raise ValueError(f"Duplicate strategy id: {definition.strategy_id}")
        self._definitions[definition.strategy_id] = definition

    def get(self, strategy_id: str) -> StrategyDefinition:
        try:
            return self._definitions[strategy_id]
        except KeyError as exc:
            choices = ", ".join(sorted(self._definitions))
            raise ValueError(f"Unknown strategy '{strategy_id}'. Available: {choices}") from exc

    def list(self) -> list[StrategyDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions)]

    def build_params(self, strategy_id: str, candidates: dict[str, Any], strict: bool = False) -> dict[str, Any]:
        """按策略声明筛选参数。strict=True 时未声明的参数报错，否则静默丢弃（CLI 共享旗标场景）。"""
        definition = self.get(strategy_id)
        supported = definition.param_names()
        unknown = {key for key, value in candidates.items() if value is not None} - supported
        if strict and unknown:
            raise ValueError(
                f"策略 '{strategy_id}' 不支持参数 {sorted(unknown)}；支持的参数: {sorted(supported)}"
            )
        return {key: value for key, value in candidates.items() if key in supported and value is not None}

    def run(self, strategy_id: str, **params: Any) -> StrategyResult:
        definition = self.get(strategy_id)
        unknown = set(params) - definition.param_names()
        if unknown:
            raise ValueError(
                f"策略 '{strategy_id}' 不支持参数 {sorted(unknown)}；支持的参数: {sorted(definition.param_names())}"
            )
        return definition.runner(**params)
