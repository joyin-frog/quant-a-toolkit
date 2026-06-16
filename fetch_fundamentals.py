"""抓取 649 只主板个股的季度财务指标，存入 data/fundamentals/。支持断点续抓。

只保留做因子要用的列，并重命名成 ascii。日期是【报告期】，因子对齐时再做公告滞后。
"""

import sys, time
import akshare as ak
import pandas as pd
import requests

from quant_a.config import DATA_DIR
from quant_a.universe import load_stock_universe

FUND_DIR = DATA_DIR / "fundamentals"
COLS = {
    "日期": "report_date",
    "净资产收益率(%)": "roe",
    "加权净资产收益率(%)": "roe_w",
    "资产负债率(%)": "debt",
    "每股净资产_调整后(元)": "bvps",
    "销售净利率(%)": "net_margin",
    "净利润增长率(%)": "profit_growth",
}


def fetch_one(symbol: str) -> pd.DataFrame:
    last = None
    for attempt in range(3):
        try:
            d = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2017")
            break
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(attempt + 1)
    else:
        raise last
    keep = {k: v for k, v in COLS.items() if k in d.columns}
    out = d[list(keep)].rename(columns=keep)
    for c in out.columns:
        if c != "report_date":
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out["report_date"] = pd.to_datetime(out["report_date"], errors="coerce")
    return out.dropna(subset=["report_date"]).sort_values("report_date")


def main() -> None:
    force = "--force" in sys.argv
    s = requests.Session(); s.trust_env = False; requests.get = s.get
    FUND_DIR.mkdir(parents=True, exist_ok=True)
    syms = load_stock_universe()["symbol"].astype(str).str.zfill(6).tolist()
    total = len(syms)
    print(f"待抓财务指标: {total} 只", flush=True)
    ok = skip = fail = 0
    for i, sym in enumerate(syms, 1):
        p = FUND_DIR / f"{sym}.csv"
        if not force and p.exists():
            skip += 1; continue
        try:
            fetch_one(sym).to_csv(p, index=False)
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"[{i}/{total}] {sym} FAIL: {str(e)[:120]}", flush=True)
            continue
        if ok % 25 == 0:
            print(f"[{i}/{total}] ok={ok} skip={skip} fail={fail}", flush=True)
        time.sleep(0.05)
    print(f"DONE ok={ok} skip={skip} fail={fail} total={total}", flush=True)


if __name__ == "__main__":
    main()
