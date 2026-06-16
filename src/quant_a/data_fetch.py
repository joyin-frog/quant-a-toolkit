import os
import time
from datetime import date
from functools import lru_cache

import akshare as ak
import pandas as pd
import requests

from quant_a.config import ADJUST, END_DATE, START_DATE


COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
}
STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
YFINANCE_COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
}


EASTMONEY_NO_PROXY = [".eastmoney.com", "push2his.eastmoney.com"]


# 这里是环境兼容性补丁：AkShare 走 Eastmoney 时，系统代理可能导致请求异常，所以强制补 no_proxy。
def _ensure_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        existing = [item.strip() for item in os.environ.get(key, "").split(",") if item.strip()]
        merged = existing[:]
        for host in EASTMONEY_NO_PROXY:
            if host not in merged:
                merged.append(host)
        os.environ[key] = ",".join(merged)


# 抓数层统一复用这段重试逻辑，并临时替换 requests.get，避免继承到本机有问题的代理设置。
def _fetch_with_retry(loader) -> pd.DataFrame:
    _ensure_no_proxy()
    session = requests.Session()
    session.trust_env = False
    original_get = requests.get
    requests.get = session.get
    try:
        last_error = None
        for attempt in range(3):
            try:
                return loader()
            except requests.RequestException as error:
                last_error = error
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        raise last_error
    finally:
        requests.get = original_get


# 无论来源是 AkShare 还是 yfinance，最终都归一化成统一的 OHLCV schema，保证缓存层和回测层完全解耦。
def _normalize_bars(bars: pd.DataFrame) -> pd.DataFrame:
    bars = bars.rename(columns=COLUMN_MAP)
    bars = bars.loc[:, STANDARD_COLUMNS].copy()
    bars["date"] = pd.to_datetime(bars["date"])
    for column in STANDARD_COLUMNS[1:]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    bars = bars.sort_values("date").drop_duplicates(subset="date", keep="last")
    return bars.reset_index(drop=True)


def _normalize_yfinance_bars(bars: pd.DataFrame) -> pd.DataFrame:
    normalized = bars.rename(columns=YFINANCE_COLUMN_MAP).copy()
    normalized.index = pd.to_datetime(normalized.index)
    normalized.index.name = "date"
    normalized = normalized.reset_index()
    normalized = normalized.loc[:, STANDARD_COLUMNS].copy()
    normalized["date"] = pd.to_datetime(normalized["date"]).dt.tz_localize(None)
    for column in STANDARD_COLUMNS[1:]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.dropna(subset=["open", "high", "low", "close"])
    normalized = normalized.sort_values("date").drop_duplicates(subset="date", keep="last")
    return normalized.reset_index(drop=True)


def _to_yfinance_symbol(symbol: str, kind: str) -> str:
    if kind != "stock":
        raise ValueError(f"Unsupported instrument type for {symbol}: {kind}")
    suffix = ".SS" if symbol.startswith(("5", "6", "9")) else ".SZ"
    return f"{symbol}{suffix}"


def _download_with_yfinance(symbol: str, kind: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as error:
        raise RuntimeError("yfinance is not installed") from error

    end_date = END_DATE or date.today().strftime("%Y-%m-%d")
    yahoo_symbol = _to_yfinance_symbol(symbol, kind)
    bars = yf.download(
        yahoo_symbol,
        start=START_DATE,
        end=end_date,
        auto_adjust=True,
        progress=False,
        actions=False,
        multi_level_index=False,
    )
    if bars.empty:
        raise RuntimeError(f"yfinance returned no rows for {symbol} ({yahoo_symbol})")
    return bars


@lru_cache(maxsize=1)
def fetch_current_st_symbols() -> set[str]:
    try:
        st_board = _fetch_with_retry(lambda: ak.stock_zh_a_st_em())
    except Exception:
        return set()

    if "代码" not in st_board.columns:
        return set()
    return {str(symbol).zfill(6) for symbol in st_board["代码"].dropna().astype(str)}


def fetch_stock_bars(symbol: str, start: str | None = None) -> pd.DataFrame:
    end_date = END_DATE or date.today().strftime("%Y-%m-%d")
    start_date = (start or START_DATE).replace("-", "")
    try:
        bars = _fetch_with_retry(
            lambda: ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date.replace("-", ""),
                adjust=ADJUST,
            )
        )
        return _normalize_bars(bars)
    except requests.RequestException:
        return _normalize_yfinance_bars(_download_with_yfinance(symbol, "stock"))


def fetch_stock_metadata(symbol: str) -> dict[str, object]:
    try:
        info = _fetch_with_retry(lambda: ak.stock_individual_info_em(symbol=symbol))
    except requests.RequestException as error:
        raise RuntimeError(f"Failed to fetch metadata for {symbol}") from error

    if "item" not in info.columns or "value" not in info.columns:
        raise RuntimeError(f"Unexpected metadata schema for {symbol}")

    info_map = dict(zip(info["item"].astype(str), info["value"]))
    listing_date_raw = str(info_map.get("上市时间", ""))
    listing_date = pd.to_datetime(listing_date_raw, format="%Y%m%d", errors="coerce")
    stock_name = str(info_map.get("股票简称", "")).strip().replace(" ", "")
    is_st = symbol in fetch_current_st_symbols() or "ST" in stock_name.upper()

    return {
        "symbol": str(symbol).zfill(6),
        "name": stock_name,
        "listing_date": listing_date,
        "is_st": bool(is_st),
    }


# 统一抓数入口；当前版本只保留 A 股个股。start 给定时只抓该日期起的增量。
def fetch_bars(symbol: str, kind: str, start: str | None = None) -> pd.DataFrame:
    if kind == "stock":
        return fetch_stock_bars(symbol, start=start)
    raise ValueError(f"Unsupported instrument type for {symbol}: {kind}")
