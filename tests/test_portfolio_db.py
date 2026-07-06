import pandas as pd

import quant_a.portfolio_db as db


def _fake_bars():
    cache_dates = pd.bdate_range("2024-01-02", "2024-01-31")
    return pd.DataFrame(
        {
            "date": cache_dates,
            "open": 10.0,
            "high": 10.0,
            "low": 10.0,
            "close": 10.0,
            "volume": 1,
        }
    )


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "portfolio.db")
    monkeypatch.setattr(db, "cache_exists", lambda code: code == "600000")
    monkeypatch.setattr(db, "load_cached_bars", lambda code: _fake_bars())


def test_reconstruct_keeps_trade_after_last_cached_price(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    db.add_trade("2024-01-05", "600000", "X", "buy", 100, 10.0)   # 缓存范围内
    db.add_trade("2024-02-15", "600000", "X", "buy", 100, 10.0)   # 晚于最后缓存价(01-31)
    rc = db.reconstruct()
    assert rc is not None
    held = {h["code"]: h["shares"] for h in rc["current_holdings"]}
    assert held.get("600000") == 200, "晚于最后缓存价的成交被漏算了"
    # 净值末值 = 200 股 * 10 元 - 现金支出(2000) ... 现金为负，holdings_value=2000
    assert rc["holdings_value"].iloc[-1] == 2000.0


def test_reconstruct_in_range_trade_still_snaps_forward(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    # 周六(01-06，非交易日)买入：应被吸附到下一个交易日，仍计入。
    db.add_trade("2024-01-06", "600000", "X", "buy", 100, 10.0)
    rc = db.reconstruct()
    held = {h["code"]: h["shares"] for h in rc["current_holdings"]}
    assert held.get("600000") == 100


def test_strategy_accounts_isolate_trades_cash_and_positions(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    db.add_cash_flow("2024-01-02", 100_000, strategy_id="core_satellite")
    db.add_cash_flow("2024-01-02", 50_000, strategy_id="active_leader")
    db.add_trade("2024-01-05", "600000", "X", "buy", 100, 10.0, strategy_id="core_satellite")
    db.add_trade("2024-01-05", "600000", "X", "buy", 300, 10.0, strategy_id="active_leader")

    assert len(db.get_trades("core_satellite")) == 1
    assert len(db.get_trades("active_leader")) == 1
    assert db.get_cash_flows("core_satellite")["amount"].sum() == 100_000
    assert db.get_cash_flows("active_leader")["amount"].sum() == 50_000
    assert db.current_positions("core_satellite").iloc[0]["shares"] == 100
    assert db.current_positions("active_leader").iloc[0]["shares"] == 300


def test_report_twr_ignores_mid_period_deposits(monkeypatch, tmp_path):
    """中途入金不能被算成收益：价格不动时 TWR 应恒为 0（缓存价固定 10 元）。"""
    _setup(monkeypatch, tmp_path)
    db.add_cash_flow("2024-01-02", 1000, strategy_id="s")
    db.add_trade("2024-01-02", "600000", "X", "buy", 100, 10.0, strategy_id="s")
    db.add_cash_flow("2024-01-15", 1000, strategy_id="s")  # 中途入金，价格没动

    rc = db.reconstruct("s")
    equity = rc["equity"]
    external = rc["external_flows"].reindex(equity.index).fillna(0.0)
    prev = equity.shift(1)
    real_ret = ((equity - external) / prev - 1.0).where(prev > 0, 0.0).fillna(0.0)
    assert abs(real_ret).max() < 1e-9  # 价格没动 → 收益应为 0，入金不是收益
    assert float(external.sum()) == 2000.0
