from __future__ import annotations

import time

import pandas as pd

from quant_a.cache import UNIVERSE_CACHE_PATH
from quant_a.config import DATA_DIR, EXCLUDED_BOARD_PREFIXES, STOCK_INDEX_SYMBOL

# 全主板股票池缓存（用于消除指数成分股的幸存者偏差：不再用"今天的中证1000"，
# 而是用全部主板个股 + trade_rules 的点对点流动性筛选来定每月能买谁）。
MAINBOARD_UNIVERSE_PATH = DATA_DIR / "mainboard_universe.csv"


def _apply_board_filter(universe: pd.DataFrame) -> pd.DataFrame:
    # 排除创业板/科创板/北交所等，只保留沪深主板个股。
    symbols = universe["symbol"].astype(str).str.zfill(6)
    excluded = symbols.str.startswith(EXCLUDED_BOARD_PREFIXES)
    return universe.loc[~excluded].reset_index(drop=True)


def _fetch_csindex_constituents(index_symbol: str) -> pd.DataFrame:
    import akshare as ak

    return ak.index_stock_cons_csindex(symbol=index_symbol)


def _normalize_universe(raw_universe: pd.DataFrame) -> pd.DataFrame:
    universe = raw_universe.copy()
    symbol_column = "成分券代码" if "成分券代码" in universe.columns else "品种代码"
    name_column = "成分券名称" if "成分券名称" in universe.columns else "品种名称"
    date_column = "日期" if "日期" in universe.columns else "纳入日期"

    universe = universe.loc[:, [symbol_column, name_column, date_column]].copy()
    universe.columns = ["symbol", "name", "date"]
    universe["symbol"] = universe["symbol"].astype(str).str.zfill(6)
    universe["name"] = universe["name"].astype(str)
    universe["date"] = pd.to_datetime(universe["date"], errors="coerce")
    universe = universe.dropna(subset=["symbol"]).drop_duplicates(subset="symbol", keep="last")
    return universe.sort_values("symbol").reset_index(drop=True)


def load_stock_universe(index_symbol: str = STOCK_INDEX_SYMBOL, refresh: bool = False) -> pd.DataFrame:
    if not refresh and UNIVERSE_CACHE_PATH.exists():
        universe = pd.read_csv(UNIVERSE_CACHE_PATH)
        universe["symbol"] = universe["symbol"].astype(str).str.zfill(6)
        if "date" in universe.columns:
            universe["date"] = pd.to_datetime(universe["date"], errors="coerce")
        return _apply_board_filter(universe.loc[:, ["symbol", "name", "date"]])

    universe = _normalize_universe(_fetch_csindex_constituents(index_symbol))
    UNIVERSE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    universe.to_csv(UNIVERSE_CACHE_PATH, index=False)
    return _apply_board_filter(universe)


def _fetch_all_a_code_name() -> pd.DataFrame:
    import akshare as ak

    last = None
    for attempt in range(5):
        try:
            return ak.stock_info_a_code_name()
        except Exception as error:  # noqa: BLE001
            last = error
            time.sleep(attempt + 1)
    raise RuntimeError(f"Failed to fetch A-share code list: {last}")


def load_mainboard_universe(refresh: bool = False) -> pd.DataFrame:
    """全部主板个股（排除创业板/科创板/北交所），用于无幸存者偏差的点对点回测。

    这是一个【当前已上市】的全集，已消除"指数成分股选择"这层幸存者偏差；
    残留的只是"2018后已退市个股不在内"，A 股该影响相对小，使用时需声明。
    """
    if not refresh and MAINBOARD_UNIVERSE_PATH.exists():
        universe = pd.read_csv(MAINBOARD_UNIVERSE_PATH)
        universe["symbol"] = universe["symbol"].astype(str).str.zfill(6)
        return universe.loc[:, ["symbol", "name"]]

    raw = _fetch_all_a_code_name()
    code_col = next(c for c in raw.columns if "code" in c.lower() or "代码" in c)
    name_col = next((c for c in raw.columns if "name" in c.lower() or "名称" in c), None)
    universe = pd.DataFrame(
        {
            "symbol": raw[code_col].astype(str).str.extract(r"(\d{6})")[0],
            "name": raw[name_col].astype(str) if name_col else "",
        }
    ).dropna(subset=["symbol"])
    universe = _apply_board_filter(universe).drop_duplicates(subset="symbol").sort_values("symbol")
    MAINBOARD_UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    universe.to_csv(MAINBOARD_UNIVERSE_PATH, index=False)
    return universe.reset_index(drop=True)
