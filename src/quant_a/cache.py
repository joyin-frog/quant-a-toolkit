from pathlib import Path

import pandas as pd

from quant_a.config import DATA_DIR


STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
UNIVERSE_COLUMNS = ["symbol", "name", "date"]
METADATA_COLUMNS = ["symbol", "name", "listing_date", "is_st"]

UNIVERSE_CACHE_PATH = DATA_DIR / "csi300_universe.csv"
METADATA_CACHE_PATH = DATA_DIR / "stock_metadata.csv"


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


def save_universe_cache(universe: pd.DataFrame) -> Path:
    path = UNIVERSE_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    universe.loc[:, UNIVERSE_COLUMNS].to_csv(path, index=False)
    return path


def load_universe_cache() -> pd.DataFrame:
    universe = pd.read_csv(UNIVERSE_CACHE_PATH)
    universe["symbol"] = universe["symbol"].astype(str).str.zfill(6)
    if "date" in universe.columns:
        universe["date"] = pd.to_datetime(universe["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return universe.loc[:, UNIVERSE_COLUMNS]


def save_stock_metadata_cache(metadata: pd.DataFrame) -> Path:
    path = METADATA_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = metadata.copy()
    normalized["symbol"] = normalized["symbol"].astype(str).str.zfill(6)
    normalized["listing_date"] = pd.to_datetime(normalized["listing_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    normalized["is_st"] = normalized["is_st"].astype(bool)
    normalized.loc[:, METADATA_COLUMNS].to_csv(path, index=False)
    return path


def load_stock_metadata_cache() -> pd.DataFrame:
    metadata = pd.read_csv(METADATA_CACHE_PATH)
    metadata["symbol"] = metadata["symbol"].astype(str).str.zfill(6)
    metadata["listing_date"] = pd.to_datetime(metadata["listing_date"], errors="coerce")
    metadata["is_st"] = metadata["is_st"].astype(bool)
    return metadata.loc[:, METADATA_COLUMNS]
