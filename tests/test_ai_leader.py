"""ai_leader 股票池过滤与选股预算的离线单测。"""

import pandas as pd

from quant_a.portfolio import build_cs_buy_list, select_ai_leaders
from quant_a.strategies.ai_leader.pool import CHAIN_POOL, is_mainboard_code, mainboard_chains


def test_mainboard_pool_excludes_gem_star_and_unknown():
    chains, names, dropped = mainboard_chains()
    codes = {code for codes in chains.values() for code in codes}
    # 用户账户无创业板/科创板权限：绝不允许 300/301/688/689 混进可交易池
    assert all(is_mainboard_code(code) for code in codes)
    assert not any(code.startswith(("30", "68", "8", "4")) for code in codes)
    # AI芯片整链都在科创板，主板池里不该有这条链
    assert "AI芯片" not in chains
    # 图片里的非主板龙头都该出现在剔除清单里
    dropped_text = "；".join(dropped)
    assert "中际旭创" in dropped_text and "寒武纪" in dropped_text
    # 每个保留代码都有名字
    assert all(names[code] for code in codes)


def test_pool_covers_all_image_chains():
    # 图片 20 条子链 + 用户新增机器人链 = 21（过滤前全收录）
    assert len(CHAIN_POOL) == 21
    assert all(len(entries) >= 4 for entries in CHAIN_POOL.values())


def test_select_leaders_per_chain_and_budget_per_chain():
    idx = pd.bdate_range("2024-01-01", periods=3)
    chains = {"链A": ["600001", "600002"], "链B": ["600003"], "链C": ["600004"]}
    close = pd.DataFrame(
        {"600001": 10.0, "600002": 20.0, "600003": 500.0, "600004": 30.0}, index=idx
    )
    mom = pd.DataFrame({"600001": 0.1, "600002": 0.9, "600003": 0.5, "600004": 0.2}, index=idx)
    mask = pd.DataFrame(True, index=idx, columns=close.columns)
    date = idx[-1]
    # 每链预算 1万：链A 选动量更强且买得起的 600002；链B 的 600003 一手 5 万买不起 → 缺席
    leaders = select_ai_leaders(date, {"mom": mom}, mask, price_row=close.loc[date], budget_per_name=10_000, chains=chains)
    assert leaders == {"链A": "600002", "链C": "600004"}

    # 预算按【子链总数】分母：缺席的链 B 份额留现金，而不是加倍押注其余两链
    table = build_cs_buy_list(date, [], leaders, close.loc[date], 30_000, 1.0, {}, ai_sleeve="AI", n_chains=len(chains))
    assert set(table["code"]) == {"600002", "600004"}
    assert table["cost"].sum() <= 20_000  # 每链 1 万上限，链B 的 1 万留现金
    assert (table["sleeve"] == "AI").all()
