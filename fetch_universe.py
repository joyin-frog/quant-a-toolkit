"""抓取过滤后的中证1000主板个股日线，存入本地缓存。支持断点续抓。"""

import sys
import time

from quant_a.cache import cache_exists, save_cached_bars
from quant_a.data_fetch import fetch_bars
from quant_a.universe import load_stock_universe


def main() -> None:
    force = "--force" in sys.argv
    universe = load_stock_universe(refresh=True)
    symbols = universe["symbol"].astype(str).str.zfill(6).tolist()
    total = len(symbols)
    print(f"过滤后主板个股: {total} 只", flush=True)

    ok, skipped, failed = 0, 0, 0
    for i, symbol in enumerate(symbols, 1):
        if not force and cache_exists(symbol):
            skipped += 1
            continue
        try:
            bars = fetch_bars(symbol, "stock")
            save_cached_bars(symbol, bars)
            ok += 1
        except Exception as error:  # noqa: BLE001
            failed += 1
            print(f"[{i}/{total}] {symbol} FAILED: {error}", flush=True)
            continue
        if ok % 25 == 0:
            print(f"[{i}/{total}] fetched={ok} skipped={skipped} failed={failed}", flush=True)
        time.sleep(0.05)

    print(f"DONE fetched={ok} skipped(cached)={skipped} failed={failed} total={total}", flush=True)


if __name__ == "__main__":
    main()
