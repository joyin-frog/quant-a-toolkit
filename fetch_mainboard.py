"""抓取全部主板个股日线（消除幸存者偏差用）。复用已有缓存，断点续抓。"""

import sys
import time

from quant_a.cache import cache_exists, save_cached_bars
from quant_a.data_fetch import fetch_bars
from quant_a.universe import load_mainboard_universe


def main() -> None:
    force = "--force" in sys.argv
    universe = load_mainboard_universe(refresh=True)
    symbols = universe["symbol"].astype(str).str.zfill(6).tolist()
    total = len(symbols)
    print(f"全主板个股: {total} 只（已缓存的会跳过）", flush=True)

    ok = skipped = failed = 0
    for i, symbol in enumerate(symbols, 1):
        if not force and cache_exists(symbol):
            skipped += 1
            continue
        try:
            save_cached_bars(symbol, fetch_bars(symbol, "stock"))
            ok += 1
        except Exception as error:  # noqa: BLE001
            failed += 1
            if failed <= 50:
                print(f"[{i}/{total}] {symbol} FAIL: {str(error)[:100]}", flush=True)
            continue
        if ok % 50 == 0:
            print(f"[{i}/{total}] fetched={ok} skipped={skipped} failed={failed}", flush=True)
        time.sleep(0.05)

    print(f"DONE fetched={ok} skipped(cached)={skipped} failed={failed} total={total}", flush=True)


if __name__ == "__main__":
    main()
