import numpy as np
import pandas as pd

from quant_a.metrics import calculate_metrics


def _series(vals):
    idx = pd.bdate_range("2024-01-02", periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)


def test_total_return_matches_compounded_product():
    r = _series([0.01, -0.02, 0.03, 0.0, 0.015])
    m = calculate_metrics(r, (1 + r).cumprod())
    expected = float((1 + r).prod() - 1)
    assert abs(m["total_return"] - expected) < 1e-9


def test_metric_ranges_are_sane():
    r = _series([0.02, -0.05, 0.03, -0.01, 0.04])
    m = calculate_metrics(r, (1 + r).cumprod())
    assert -1.0 <= m["max_drawdown"] <= 0.0
    assert 0.0 <= m["win_rate"] <= 1.0
    assert {"total_return", "annualized_return", "max_drawdown", "sharpe", "win_rate"} <= set(m)


def test_all_zero_returns_total_is_zero():
    r = _series([0.0, 0.0, 0.0])
    m = calculate_metrics(r, (1 + r).cumprod())
    assert m["total_return"] == 0.0
