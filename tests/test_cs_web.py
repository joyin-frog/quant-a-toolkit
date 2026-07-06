"""网页 JSON 层的 NaN/Inf 清洗测试（cs_web 已委托 strategy_web，这里直接测统一入口）。"""

import json

import pandas as pd

import quant_a.cs_web as cs_web
import quant_a.strategy_web as strategy_web
from quant_a.platform.contracts import StrategyResult


def _fake_result(params):
    idx = pd.bdate_range("2024-01-02", periods=300)
    equity = pd.Series(1.0, index=idx)
    bench = pd.Series(1.0, index=idx)
    buy = pd.DataFrame(
        [{"code": "600000", "name": "X", "sleeve": "核心", "shares": 100, "cost": 1000.0, "price": 10.0, "lots": 1, "weight": 0.5}]
    )
    return StrategyResult(
        strategy_id="core_satellite",
        name="核心-卫星",
        params=params,
        date_range=(idx[0], idx[-1]),
        metrics={"total_return": float("nan"), "sharpe": float("inf"), "max_drawdown": -0.1},
        benchmark_metrics={"total_return": 0.2},
        equity_curve=equity,
        benchmark_curve=bench,
        holdings=buy,
        diagnostics={"rolling12m": {"median": float("nan")}, "core_sectors": {"银行": 2}, "avg_cash_pct": float("nan")},
    )


class _FakeRegistry:
    def build_params(self, strategy_id, candidates, strict=False):
        allowed = {"capital", "holdings", "ai_weight"}
        return {k: v for k, v in candidates.items() if k in allowed and v is not None}

    def run(self, strategy_id, **params):
        return _fake_result(params)


def test_num_sanitizes_nan_inf():
    assert cs_web._num(1.23456) == 1.2346
    assert cs_web._num(float("nan")) is None
    assert cs_web._num(float("inf")) is None
    assert cs_web._num(float("-inf")) is None
    assert cs_web._num("x") is None


def test_build_payload_is_json_safe(monkeypatch):
    monkeypatch.setattr(strategy_web, "build_registry", lambda: _FakeRegistry())
    payload = cs_web.build_payload(200000, 17, 0.15)
    # allow_nan=False 会在残留 NaN/Inf 时抛错；不抛 = 已清洗干净。
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, default=str)
    assert "NaN" not in text and "Infinity" not in text
    assert payload["metrics"]["total_return"] is None  # NaN -> None
    assert payload["metrics"]["sharpe"] is None         # Inf -> None
    assert payload["avg_cash_pct"] is None              # NaN -> None
    assert payload["rolling12m"]["median"] is None      # NaN -> None
    assert payload["strategy_id"] == "core_satellite"
    assert payload["holdings_list"][0]["name"] == "X"
