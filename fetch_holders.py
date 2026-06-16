"""抓沪深300主板 + AI龙头的【股东户数】历史，存 data/holders/。用于"筹码集中"因子。断点续抓。"""
import time, requests
import akshare as ak
import pandas as pd
from quant_a.config import DATA_DIR
from quant_a.portfolio import ai_symbols

OUT = DATA_DIR / "holders"
COLS = {"股东户数统计截止日": "report_date", "股东户数公告日期": "announce_date",
        "股东户数-本次": "holders", "股东户数-增减比例": "change_pct"}


def fetch_one(symbol: str) -> pd.DataFrame:
    last = None
    for a in range(3):
        try:
            d = ak.stock_zh_a_gdhs_detail_em(symbol=symbol)
            if d is not None and len(d) > 0:
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5)
    else:
        raise last or RuntimeError("empty")
    keep = {k: v for k, v in COLS.items() if k in d.columns}
    out = d[list(keep)].rename(columns=keep)
    out["report_date"] = pd.to_datetime(out["report_date"], errors="coerce")
    out["announce_date"] = pd.to_datetime(out.get("announce_date"), errors="coerce")
    for c in ("holders", "change_pct"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.dropna(subset=["report_date"]).sort_values("report_date")


def main() -> None:
    s = requests.Session(); s.trust_env = False; requests.get = s.get
    OUT.mkdir(parents=True, exist_ok=True)
    hs = pd.read_csv(DATA_DIR / "hs300_mainboard.csv", dtype=str)["symbol"].str.zfill(6).tolist()
    syms = sorted(set(hs) | set(ai_symbols()))
    ok = skip = fail = 0
    for i, sym in enumerate(syms, 1):
        p = OUT / f"{sym}.csv"
        if p.exists():
            skip += 1; continue
        try:
            fetch_one(sym).to_csv(p, index=False); ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1; print(f"{sym} FAIL {str(e)[:50]}", flush=True); continue
        if ok % 25 == 0:
            print(f"[{i}/{len(syms)}] ok={ok} skip={skip} fail={fail}", flush=True)
        time.sleep(0.05)
    print(f"DONE ok={ok} skip={skip} fail={fail} total={len(syms)}", flush=True)


if __name__ == "__main__":
    main()
