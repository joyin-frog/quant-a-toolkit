import pandas as pd

from quant_a.review import grade_execution, position_contributions, rank_ic


def test_grade_execution_perfect_is_A():
    assert grade_execution(1.0, 0.0, 0, 0) == "A"


def test_grade_execution_half_coverage_is_C():
    # 100 - 0.5*80 = 60 -> C
    assert grade_execution(0.5, 0.0, 0, 0) == "C"


def test_grade_execution_full_miss_is_D():
    assert grade_execution(0.0, 0.0, 0, 0) == "D"


def test_grade_execution_slippage_and_discipline_downgrade():
    assert grade_execution(1.0, 0.02, 0, 0) == "B"   # 滑点 2% -> 100-20=80
    assert grade_execution(1.0, 0.0, 2, 1) == "B"    # 2 笔乱动 + 1 只计划外 -> 100-16-6=78


def test_position_contributions_math():
    pos = pd.DataFrame([
        {"code": "A", "name": "a", "sleeve": "核心", "shares": 100, "avg_cost": 10.0},
        {"code": "B", "name": "b", "sleeve": "AI卫星", "shares": 200, "avg_cost": 5.0},
    ])
    price_now = {"A": 12.0, "B": 4.0}
    c = position_contributions(pos, price_now, capital=10000.0)
    a = c[c["code"] == "A"].iloc[0]
    b = c[c["code"] == "B"].iloc[0]
    # A: 100*(12-10)=+200 -> contrib +0.02, ret +0.2
    assert abs(a["contrib"] - 0.02) < 1e-9 and abs(a["ret"] - 0.2) < 1e-9
    # B: 200*(4-5)=-200 -> contrib -0.02, ret -0.2
    assert abs(b["contrib"] + 0.02) < 1e-9 and abs(b["ret"] + 0.2) < 1e-9


def test_rank_ic_sign_and_degenerate():
    f = pd.Series([1, 2, 3, 4, 5, 6], index=list("abcdef"), dtype=float)
    up = pd.Series([10, 20, 30, 40, 50, 60], index=list("abcdef"), dtype=float)
    dn = pd.Series([60, 50, 40, 30, 20, 10], index=list("abcdef"), dtype=float)
    assert rank_ic(f, up) > 0.99      # 同向 -> IC≈+1
    assert rank_ic(f, dn) < -0.99     # 反向 -> IC≈-1
    short = pd.Series([1, 2, 3], index=list("abc"), dtype=float)
    assert pd.isna(rank_ic(short, short))  # 不足 5 只 -> nan
