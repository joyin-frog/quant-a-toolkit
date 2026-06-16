import quant_a.portfolio_web as pw


def test_num_sanitizes_nan_inf():
    assert pw._num(1.23456) == 1.2346
    assert pw._num(float("nan")) is None
    assert pw._num(float("inf")) is None
    assert pw._num(float("-inf")) is None
    assert pw._num("not-a-number") is None
    assert pw._num(None) is None


def test_next_rebalance_invariants():
    r = pw._next_rebalance(rebalance_day=15)
    assert r["rebalance_day"] == 15
    assert r["days_until"] >= 0
    # next_date 可被解析为 YYYY-MM-DD
    import datetime

    datetime.date.fromisoformat(r["next_date"])
