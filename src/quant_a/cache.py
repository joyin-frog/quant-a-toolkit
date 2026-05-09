from pathlib import Path

import pandas as pd

from quant_a.config import DATA_DIR


STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


# 每个标的一份 CSV 是这个项目的持久化边界；只要 schema 不变，下游模块就不用关心抓数来源。
def cache_path(symbol: str) -> Path:
    return DATA_DIR / f"{symbol}.csv"


def cache_exists(symbol: str) -> bool:
    return cache_path(symbol).exists()


# 落盘前只保留标准列，避免不同数据源的额外字段污染缓存格式。
def save_cached_bars(symbol: str, bars: pd.DataFrame) -> Path:
    path = cache_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    bars.loc[:, STANDARD_COLUMNS].to_csv(path, index=False)
    return path


def load_cached_bars(symbol: str) -> pd.DataFrame:
    path = cache_path(symbol)
    bars = pd.read_csv(path, parse_dates=["date"])
    bars = bars.sort_values("date").drop_duplicates(subset="date", keep="last")
    return bars.loc[:, STANDARD_COLUMNS]
