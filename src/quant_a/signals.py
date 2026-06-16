"""5/20 日线金叉择时的信号层（单股事件驱动）。

只产出"进场计划"：哪只股票、哪天用什么价格买入。卖出由 event_backtest.py 负责，
因为卖出依赖买入后逐日的持仓状态，属于回测执行范畴。

进场规则（与用户口述一致）：
  T   日：5 日线上穿 20 日线（金叉），且 20 日线"走上"，且当日收盘价 < GC_MAX_PRICE，
          且通过基础选股过滤（板块/流动性/停牌）。仅记录，不操作。
  T+1 日：只有"收盘价 > T 日最高价"才确认；否则放弃
          （次日下跌、或低开上涨但收盘没超过 T 日最高价，都算放弃）。
  T+2 日：买入点，按当日最低价成交。
"""

from __future__ import annotations

import pandas as pd

from quant_a.config import (
    GC_FAST_MA,
    GC_MAX_PRICE,
    GC_SLOPE_LOOKBACK,
    GC_SLOPE_UP_MIN,
    GC_SLOW_MA,
)


def compute_moving_averages(
    close_matrix: pd.DataFrame,
    fast: int | None = None,
    slow: int | None = None,
) -> dict[str, pd.DataFrame]:
    selected_fast = fast or GC_FAST_MA
    selected_slow = slow or GC_SLOW_MA
    ma_fast = close_matrix.rolling(selected_fast, min_periods=selected_fast).mean()
    ma_slow = close_matrix.rolling(selected_slow, min_periods=selected_slow).mean()
    return {"ma_fast": ma_fast, "ma_slow": ma_slow}


def _slow_ma_is_rising(
    ma_slow: pd.DataFrame,
    lookback: int | None = None,
    up_min: float | None = None,
) -> pd.DataFrame:
    selected_lookback = lookback or GC_SLOPE_LOOKBACK
    selected_up_min = up_min if up_min is not None else GC_SLOPE_UP_MIN
    change = ma_slow / ma_slow.shift(selected_lookback) - 1.0
    return change > selected_up_min


def detect_entry_trades(
    open_matrix: pd.DataFrame,
    high_matrix: pd.DataFrame,
    low_matrix: pd.DataFrame,
    close_matrix: pd.DataFrame,
    candidate_mask: pd.DataFrame | None = None,
    fast: int | None = None,
    slow: int | None = None,
    slope_lookback: int | None = None,
    slope_up_min: float | None = None,
    max_price: float | None = None,
    entry_fill: str = "low",
) -> pd.DataFrame:
    """返回进场计划表，每行一笔确认后的买入。

    columns: symbol, cross_date(T), confirm_date(T+1), entry_date(T+2), entry_price

    entry_fill 决定 T+2 的成交价口径：
      "low"   = 当日最低价（用户口述"选当天低价"，但这是事后才知道的价，结果偏乐观）
      "open"  = 当日开盘价（更现实：开盘即可成交，无事后信息）
      "mid"   = (开盘+最低)/2（折中）
      "limit" = "选当天低价"的可执行版：在 T+2 挂 T+1 收盘价的限价单。
                若开盘已低于限价 → 按开盘成交；否则当日最低触及限价 → 按限价成交；
                若全天没回落到限价（高开不回） → 这笔放弃（不追高）。
    """
    if entry_fill not in {"low", "open", "mid", "limit"}:
        raise ValueError(f"Unsupported entry_fill: {entry_fill}")
    selected_max_price = max_price if max_price is not None else GC_MAX_PRICE
    mas = compute_moving_averages(close_matrix, fast=fast, slow=slow)
    ma_fast, ma_slow = mas["ma_fast"], mas["ma_slow"]

    above = ma_fast > ma_slow
    golden_cross = above & (~above.shift(1, fill_value=False))
    rising = _slow_ma_is_rising(ma_slow, lookback=slope_lookback, up_min=slope_up_min)
    price_ok = close_matrix < selected_max_price

    if candidate_mask is not None:
        candidate_mask = candidate_mask.reindex(
            index=close_matrix.index, columns=close_matrix.columns
        ).fillna(False)
    else:
        candidate_mask = pd.DataFrame(True, index=close_matrix.index, columns=close_matrix.columns)

    # T 日：合格的"上"金叉
    cross_signal = golden_cross & rising & price_ok & candidate_mask

    index = close_matrix.index
    rows: list[dict[str, object]] = []
    for symbol in close_matrix.columns:
        cross_days = cross_signal.index[cross_signal[symbol].fillna(False).to_numpy()]
        sym_high = high_matrix[symbol]
        sym_low = low_matrix[symbol]
        sym_open = open_matrix[symbol]
        sym_close = close_matrix[symbol]
        for cross_date in cross_days:
            pos = index.get_loc(cross_date)
            if pos + 2 >= len(index):
                continue  # 没有 T+1 / T+2，无法确认或买入
            t1 = index[pos + 1]
            t2 = index[pos + 2]
            high_t = sym_high.iloc[pos]
            close_t1 = sym_close.loc[t1]
            low_t2 = sym_low.loc[t2]
            open_t2 = sym_open.loc[t2]
            if entry_fill == "low":
                entry_price = low_t2
            elif entry_fill == "open":
                entry_price = open_t2
            elif entry_fill == "mid":
                entry_price = (open_t2 + low_t2) / 2.0
            else:  # limit：挂 T+1 收盘价的限价单
                limit_price = close_t1
                if pd.isna(open_t2) or pd.isna(low_t2):
                    continue
                if open_t2 <= limit_price:
                    entry_price = open_t2          # 低开，直接按开盘成交（更优）
                elif low_t2 <= limit_price:
                    entry_price = limit_price      # 盘中回落触及限价
                else:
                    continue                       # 高开不回，放弃这笔
            if pd.isna(high_t) or pd.isna(close_t1) or pd.isna(entry_price) or entry_price <= 0:
                continue
            # T+1 确认：收盘价必须超过 T 日最高价
            if close_t1 <= high_t:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "cross_date": cross_date,
                    "confirm_date": t1,
                    "entry_date": t2,
                    "entry_price": float(entry_price),
                }
            )

    trades = pd.DataFrame(rows, columns=["symbol", "cross_date", "confirm_date", "entry_date", "entry_price"])
    if not trades.empty:
        trades = trades.sort_values(["entry_date", "symbol"]).reset_index(drop=True)
    return trades
