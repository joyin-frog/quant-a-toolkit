import numpy as np
import pandas as pd

from quant_a.factor_pipeline import _benchmark_returns


def test_benchmark_is_finite_with_dirty_zero_price():
    idx = pd.bdate_range("2024-01-02", "2024-03-29")  # 跨 3 个月 -> 必含调仓日(每月约 15 号)
    close = pd.DataFrame({"AAA": 20.0, "BBB": 10.0}, index=idx)
    # BBB 出现一次脏价：2024-02-20 为 0，次日恢复 10 -> 恢复日 pct_change = inf
    close.loc["2024-02-20", "BBB"] = 0.0
    mask = pd.DataFrame(True, index=idx, columns=close.columns)

    ret = _benchmark_returns(close, mask)
    assert np.isfinite(ret).all(), "脏价(0→正)让 benchmark 收益出现了 inf/NaN"

    curve = (1.0 + ret).cumprod()
    assert np.isfinite(curve).all(), "benchmark 净值被 inf 污染（cumprod 炸成无穷）"
