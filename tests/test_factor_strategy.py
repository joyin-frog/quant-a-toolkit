import pandas as pd

from quant_a.factor_strategy import select_holdings_on


def _panel_and_mask():
    dates = pd.to_datetime(["2024-01-15", "2024-02-15"])
    syms = ["A", "B", "C", "D", "E"]
    vals = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}
    lowvol = pd.DataFrame([[vals[s] for s in syms]] * 2, index=dates, columns=syms)
    mom = lowvol.copy()
    panel = {"lowvol": lowvol, "mom": mom}
    mask = pd.DataFrame(True, index=dates, columns=syms)
    return panel, mask, dates


def test_select_top_holdings_by_score():
    panel, mask, dates = _panel_and_mask()
    picks = select_holdings_on(dates[0], panel, mask, holdings=2)
    assert picks == ["A", "B"]


def test_require_full_returns_empty_when_insufficient():
    panel, mask, dates = _panel_and_mask()
    picks = select_holdings_on(dates[0], panel, mask, holdings=10, require_full=True)
    assert picks == []


def test_buffer_band_keeps_existing_holding():
    panel, mask, dates = _panel_and_mask()
    # 已持有 C（综合排名第 3）。买入门槛是前 2 名，但 sell_rank=4：C 仍在前 4 名内 -> 保留不卖。
    picks = select_holdings_on(
        dates[0], panel, mask, holdings=2, current_holdings=["C"], sell_rank=4
    )
    assert set(picks) == {"C", "A"}
    assert "B" not in picks  # 缓冲带保住了 C，B 这次没顶上来
