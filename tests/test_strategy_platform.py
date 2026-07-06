import pandas as pd
import pytest

from quant_a.platform.contracts import StrategyResult
from quant_a.platform.registry import StrategyDefinition, StrategyRegistry


def _result(strategy_id="demo"):
    idx = pd.bdate_range("2024-01-01", periods=2)
    curve = pd.Series([1.0, 1.01], index=idx)
    return StrategyResult(
        strategy_id=strategy_id,
        name="Demo",
        params={},
        date_range=(idx[0], idx[-1]),
        metrics={},
        benchmark_metrics={},
        equity_curve=curve,
        benchmark_curve=curve,
    )


def test_registry_lists_and_runs_strategy():
    registry = StrategyRegistry()
    registry.register(StrategyDefinition("demo", "Demo", "test", lambda **_: _result()))
    assert [item.strategy_id for item in registry.list()] == ["demo"]
    assert registry.run("demo").strategy_id == "demo"


def test_registry_rejects_duplicate_and_unknown_strategy():
    registry = StrategyRegistry()
    definition = StrategyDefinition("demo", "Demo", "test", lambda **_: _result())
    registry.register(definition)
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(definition)
    with pytest.raises(ValueError, match="Available: demo"):
        registry.run("missing")


def test_registry_rejects_undeclared_params_and_filters_candidates():
    from quant_a.platform.contracts import ParamSpec

    registry = StrategyRegistry()
    registry.register(StrategyDefinition(
        "demo", "Demo", "test", lambda **kw: _result(),
        params=(ParamSpec("capital", "number", 200_000),),
    ))
    # run() 对未声明参数直接报错（runner --universe 传给不支持的策略时给人话提示）
    with pytest.raises(ValueError, match="不支持参数"):
        registry.run("demo", universe="mainboard")
    # build_params 宽松模式静默丢弃、strict 模式报错
    assert registry.build_params("demo", {"capital": 1000, "universe": "x"}) == {"capital": 1000}
    with pytest.raises(ValueError, match="不支持参数"):
        registry.build_params("demo", {"capital": 1000, "universe": "x"}, strict=True)
    # None 值不算显式传参
    assert registry.build_params("demo", {"capital": None, "universe": None}, strict=True) == {}


def test_real_registry_declares_params_and_sleeves():
    from quant_a.runner import build_registry

    registry = build_registry()
    ids = [item.strategy_id for item in registry.list()]
    assert ids == ["active_leader", "ai_leader", "core_satellite", "multi_factor"]
    meta = registry.get("core_satellite").metadata()
    assert {p["name"] for p in meta["params"]} == {"capital", "holdings", "ai_weight"}
    assert [s.value for s in registry.get("active_leader").sleeves] == ["long", "tactical"]
    assert registry.get("ai_leader").param_names() == {"capital"}
