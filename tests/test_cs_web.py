import json

import pandas as pd

import quant_a.cs_web as cs_web


def _fake_result():
    idx = pd.bdate_range("2024-01-02", periods=300)
    equity = pd.Series(1.0, index=idx)
    bench = pd.Series(1.0, index=idx)
    buy = pd.DataFrame(
        [{"code": "600000", "name": "X", "sleeve": "core", "shares": 100, "amount": 1000.0, "weight": 0.5}]
    )
    buy.attrs["invested"] = 1000.0
    buy.attrs["cash_left"] = 0.0
    return {
        "date_range": (idx[0], idx[-1]),
        "buy_list": buy,
        "equity_curve": equity,
        "benchmark_curve": bench,
        "metrics": {"total_return": float("nan"), "sharpe": float("inf"), "max_drawdown": -0.1},
        "benchmark_metrics": {"total_return": 0.2},
        "rolling12m": {"median": float("nan")},
        "core_sectors": {"银行": 2},
        "avg_cash_pct": float("nan"),
    }


def test_num_sanitizes_nan_inf():
    assert cs_web._num(1.23456) == 1.2346
    assert cs_web._num(float("nan")) is None
    assert cs_web._num(float("inf")) is None
    assert cs_web._num(float("-inf")) is None
    assert cs_web._num("x") is None


def test_build_payload_is_json_safe(monkeypatch):
    monkeypatch.setattr(cs_web, "run_cs_pipeline", lambda **kw: _fake_result())
    payload = cs_web.build_payload(200000, 17, 0.15)
    # allow_nan=False 会在残留 NaN/Inf 时抛错；不抛 = 已清洗干净。
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, default=str)
    assert "NaN" not in text and "Infinity" not in text
    assert payload["metrics"]["total_return"] is None  # NaN -> None
    assert payload["metrics"]["sharpe"] is None         # Inf -> None
    assert payload["avg_cash_pct"] is None              # NaN -> None
    assert payload["rolling12m"]["median"] is None      # NaN -> None
