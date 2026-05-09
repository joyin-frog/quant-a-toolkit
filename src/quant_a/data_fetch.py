import os
import time
from datetime import date

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


# 无论来源是 ETF 还是 A 股，最终都归一化成统一的 OHLCV schema，保证缓存层和回测层完全解耦。
def _normalize_bars(bars: pd.DataFrame) -> pd.DataFrame:
    bars = bars.rename(columns=COLUMN_MAP)
    bars = bars.loc[:, STANDARD_COLUMNS].copy()
    bars["date"] = pd.to_datetime(bars["date"])
    for column in STANDARD_COLUMNS[1:]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    bars = bars.sort_values("date").drop_duplicates(subset="date", keep="last")
    return bars.reset_index(drop=True)


def fetch_etf_bars(symbol: str) -> pd.DataFrame:
    end_date = END_DATE or date.today().strftime("%Y-%m-%d")
    bars = _fetch_with_retry(
        lambda: ak.fund_etf_hist_em(
            symbol=symbol,
            period="daily",
            start_date=START_DATE.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust=ADJUST,
        )
    )
    return _normalize_bars(bars)


def fetch_stock_bars(symbol: str) -> pd.DataFrame:
    end_date = END_DATE or date.today().strftime("%Y-%m-%d")
    bars = _fetch_with_retry(
        lambda: ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=START_DATE.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust=ADJUST,
        )
    )
    return _normalize_bars(bars)


# 统一抓数入口；未来如果接别的资产类型，优先在这里扩展分发而不是改下游策略和回测。
def fetch_bars(symbol: str, kind: str) -> pd.DataFrame:
    if kind == "etf":
        return fetch_etf_bars(symbol)
    if kind == "stock":
        return fetch_stock_bars(symbol)
    raise ValueError(f"Unsupported instrument type for {symbol}: {kind}")
