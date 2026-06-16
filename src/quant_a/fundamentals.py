"""把季度财报对齐成逐日因子矩阵，做多因子选股用。

防未来函数的关键：财报 CSV 里的 report_date 是【报告期末】，不是公告日。
年报要到次年 4 月底才公告。所以统一把每条财报的"可用起始日"设为
report_date + LAG_DAYS（默认 120 天，保守覆盖年报公告延迟），再前向填充到逐日。
这样任何一天用到的财务值都至少是 120 天前报告期的、当时一定已公告的数据。
"""

from __future__ import annotations

import pandas as pd

from quant_a.config import DATA_DIR

FUND_DIR = DATA_DIR / "fundamentals"
RAW_COLS = ["roe", "roe_w", "debt", "bvps", "net_margin", "profit_growth"]
DEFAULT_LAG_DAYS = 120


def load_fundamental_factors(close_matrix: pd.DataFrame, lag_days: int = DEFAULT_LAG_DAYS) -> dict[str, pd.DataFrame]:
    raw: dict[str, dict[str, pd.Series]] = {c: {} for c in RAW_COLS}
    for symbol in close_matrix.columns:
        path = FUND_DIR / f"{symbol}.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path, parse_dates=["report_date"]).sort_values("report_date")
        effective = frame["report_date"] + pd.Timedelta(days=lag_days)
        for col in RAW_COLS:
            if col in frame.columns:
                series = pd.Series(frame[col].to_numpy(), index=effective)
                series = series[~series.index.duplicated(keep="last")]
                raw[col][symbol] = series

    out: dict[str, pd.DataFrame] = {}
    for col in RAW_COLS:
        if not raw[col]:
            out[col] = pd.DataFrame(index=close_matrix.index, columns=close_matrix.columns, dtype=float)
            continue
        matrix = pd.DataFrame(raw[col]).sort_index()
        # 用 公告可用日 这套时间轴前向填充，再对齐到收盘价的交易日索引。
        matrix = matrix.reindex(matrix.index.union(close_matrix.index)).ffill().reindex(close_matrix.index)
        out[col] = matrix.reindex(columns=close_matrix.columns)

    # 账面市值比 B/M = 每股净资产 / 收盘价；越大越"便宜"（价值因子，越大越好）。
    out["book_to_market"] = out["bvps"] / close_matrix
    return out


HOLDERS_DIR = DATA_DIR / "holders"


def load_holder_factor(close_matrix: pd.DataFrame) -> pd.DataFrame:
    """筹码集中因子 = 股东户数增减比例取负（户数减少→筹码集中→看涨）。

    用【公告日】对齐防未来函数（增减比例在公告后才知道）。A 股散户市里这是个真信号。
    """
    series: dict[str, pd.Series] = {}
    for symbol in close_matrix.columns:
        path = HOLDERS_DIR / f"{symbol}.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path, parse_dates=["report_date", "announce_date"])
        if "change_pct" not in frame.columns:
            continue
        effective = frame["announce_date"].fillna(frame["report_date"] + pd.Timedelta(days=30))
        values = pd.Series(-frame["change_pct"].to_numpy(), index=effective)  # 减少→正分
        values = values[~values.index.isna()]
        values = values[~values.index.duplicated(keep="last")].sort_index()
        if not values.empty:
            series[symbol] = values
    if not series:
        return pd.DataFrame(index=close_matrix.index, columns=close_matrix.columns, dtype=float)
    matrix = pd.DataFrame(series).sort_index()
    matrix = matrix.reindex(matrix.index.union(close_matrix.index)).ffill().reindex(close_matrix.index)
    return matrix.reindex(columns=close_matrix.columns)
