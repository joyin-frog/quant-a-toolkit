"""多因子选股：打分 + 选股（纯函数，不碰回测执行）。

4 因子等权（单一因子会过时，摊开持有更稳健）：
  - lowvol  低波动：过去 N 日收益率标准差取负（越稳越好）—— 价格因子
  - mom     动量：跳过最近 1 月的 6 月涨幅（越强越好）—— 价格因子
  - value   价值：账面市值比（每股净资产/价，越大越便宜）—— 来自财报
  - quality 质量：ROE（越高越好）—— 来自财报

合成：每个调仓日做【横截面排名】(rank pct)，按权重相加。缺某因子的票（如无财报）给中性
0.5 分，不排除也不惩罚——所以没财报的票仍可凭价格因子入选。只在合格票（candidate_mask）里选。
value/quality 需把 fundamentals 传进 compute_factor_panel；不传则退化成纯价格双因子。
"""

from __future__ import annotations

import pandas as pd

from quant_a.config import (
    FACTOR_MOM_LOOKBACK,
    FACTOR_MOM_SKIP,
    FACTOR_VOL_WINDOW,
    FACTOR_WEIGHTS,
)


def compute_factor_panel(
    close_matrix: pd.DataFrame,
    fundamentals: dict[str, pd.DataFrame] | None = None,
    vol_window: int | None = None,
    mom_lookback: int | None = None,
    mom_skip: int | None = None,
) -> dict[str, pd.DataFrame]:
    vw = vol_window or FACTOR_VOL_WINDOW
    ml = mom_lookback or FACTOR_MOM_LOOKBACK
    ms = mom_skip if mom_skip is not None else FACTOR_MOM_SKIP
    returns = close_matrix.pct_change(fill_method=None)
    lowvol = -returns.rolling(vw, min_periods=vw).std()
    momentum = close_matrix.shift(ms) / close_matrix.shift(ml + ms) - 1.0
    panel: dict[str, pd.DataFrame] = {"lowvol": lowvol, "mom": momentum}
    if fundamentals is not None:
        if "book_to_market" in fundamentals:
            panel["value"] = fundamentals["book_to_market"]
        if "roe" in fundamentals:
            panel["quality"] = fundamentals["roe"]
    return panel


def _weights(weights: dict[str, float] | None) -> dict[str, float]:
    return weights or dict(FACTOR_WEIGHTS)


def factor_scores_on(
    date: pd.Timestamp,
    panel: dict[str, pd.DataFrame],
    candidate_mask: pd.DataFrame,
    weights: dict[str, float] | None = None,
    sector_map: dict[str, str] | None = None,
) -> pd.Series:
    """某个调仓日的合成因子分（降序）。只用 panel 里实际存在的因子；缺财报的票按中性分处理。

    sector_map 给定时做【行业中性化】：因子在【行业内部】排名，而不是全市场排名——
    这样选出的是"每个行业里最好的"（如最便宜的银行、最便宜的科技股），自动跨行业分散，
    比事后打补丁的"行业上限"更优雅。需要全行业分类数据（data/industry_map.csv）。
    """
    used = _weights(weights)
    eligible = candidate_mask.loc[date]
    sectors = None
    if sector_map is not None:
        sectors = pd.Series({c: sector_map.get(c, "其他") for c in candidate_mask.columns})
    score = pd.Series(0.0, index=candidate_mask.columns)
    for factor, weight in used.items():
        if factor not in panel or weight == 0:
            continue
        factor_value = panel[factor].loc[date].where(eligible)
        if sectors is not None:
            rank_pct = factor_value.groupby(sectors).rank(pct=True).fillna(0.5)  # 行业内排名
        else:
            rank_pct = factor_value.rank(pct=True).fillna(0.5)
        score = score + weight * rank_pct
    valid = eligible & panel["lowvol"].loc[date].notna() & panel["mom"].loc[date].notna()
    return score.where(valid).dropna().sort_values(ascending=False)


def select_holdings_on(
    date: pd.Timestamp,
    panel: dict[str, pd.DataFrame],
    candidate_mask: pd.DataFrame,
    holdings: int,
    weights: dict[str, float] | None = None,
    require_full: bool = True,
    current_holdings: list[str] | None = None,
    sell_rank: int | None = None,
) -> list[str]:
    """选当日的 holdings 只。

    require_full=True 时，若合格票不足 holdings 只就返回空（宁可空仓也不上一个不够分散的篮子）。

    缓冲带（滞后）：当 current_holdings 与 sell_rank 都给定且 sell_rank > holdings 时，
    已持有的票只要排名仍在前 sell_rank 名内就保留（不卖），空出的位置才从前 holdings 名补新票。
    这样减少在第 holdings 名边界的反复换手、避免卖飞刚要回血的票。不给这两个参数时＝严格选前 holdings。
    """
    scored = factor_scores_on(date, panel, candidate_mask, weights)
    if require_full and len(scored) < holdings:
        return []
    if not current_holdings or not sell_rank or sell_rank <= holdings:
        return scored.head(holdings).index.tolist()

    position = {symbol: rank + 1 for rank, symbol in enumerate(scored.index)}
    survivors = [s for s in current_holdings if position.get(s, 10**9) <= sell_rank]
    survivors = sorted(survivors, key=lambda s: position[s])[:holdings]
    chosen = list(survivors)
    for symbol in scored.index:
        if len(chosen) >= holdings:
            break
        if symbol not in survivors and position[symbol] <= holdings:
            chosen.append(symbol)
    return chosen
