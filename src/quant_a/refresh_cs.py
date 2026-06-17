"""把核心-卫星用到的行情（沪深300主板 + AI龙头）刷新到最新交易日——【增量】。

每只只拉"上次缓存之后的新K线"追加进去，比每次重下 2018 至今的完整历史快得多
（月中刷新约 1-2 分钟）。前复权基准会因分红/拆股整体重算，所以校验重叠日价格：
变了就对那一只自动重下完整历史，保证不出错。

  python -m quant_a.refresh_cs           # 增量刷新
  python -m quant_a.refresh_cs --full    # 强制全量重下（偶尔做一次，纠正复权漂移）
结束把 {"ok","fail","modes","total"} 以 JSON 打到 stdout。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from quant_a.cache import cache_exists, load_cached_bars, save_cached_bars
from quant_a.config import DATA_DIR
from quant_a.data_fetch import fetch_bars
from quant_a.portfolio import ai_symbols


def _refresh_one(symbol: str) -> str:
    if not cache_exists(symbol):
        save_cached_bars(symbol, fetch_bars(symbol, "stock"))
        return "full"
    cached = load_cached_bars(symbol).sort_values("date")
    if cached.empty:
        save_cached_bars(symbol, fetch_bars(symbol, "stock"))
        return "full"

    last = cached["date"].max()
    new = fetch_bars(symbol, "stock", start=last.strftime("%Y%m%d"))
    if new.empty:
        return "current"
    new = new.sort_values("date")

    # 前复权基准校验：重叠日(last)价格变了 → 发生分红/拆股、整段被重算 → 重下完整历史。
    overlap = new[new["date"] == last]
    cached_close = cached.loc[cached["date"] == last, "close"]
    if not overlap.empty and not cached_close.empty:
        base = float(cached_close.iloc[0])
        if abs(float(overlap["close"].iloc[0]) - base) > max(0.01, 0.003 * base):
            save_cached_bars(symbol, fetch_bars(symbol, "stock"))
            return "rebased"

    add = new[new["date"] > last]
    if add.empty:
        return "current"
    merged = pd.concat([cached, add]).drop_duplicates("date", keep="last").sort_values("date")
    save_cached_bars(symbol, merged)
    return "incr"


def _refresh_full(symbol: str) -> str:
    save_cached_bars(symbol, fetch_bars(symbol, "stock"))
    return "full"


def _pass(work, syms: list[str], workers: int) -> tuple[Counter, list[str]]:
    """并行刷一批,返回(模式计数, 失败的代码)。每只各写自己的缓存文件,线程安全。"""
    modes: Counter[str] = Counter()
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, s): s for s in syms}
        for fut in as_completed(futures):
            try:
                modes[fut.result()] += 1
            except Exception:  # noqa: BLE001
                failed.append(futures[fut])
    return modes, failed


def refresh(full: bool = False, workers: int = 8) -> dict[str, object]:
    hs = pd.read_csv(DATA_DIR / "hs300_mainboard.csv", dtype=str)["symbol"].str.zfill(6).tolist()
    symbols = sorted(set(hs) | set(ai_symbols()))
    work = _refresh_full if full else _refresh_one
    # 纯网络 I/O -> 并行拉。第一遍高并发抢速度;失败的(多为 eastmoney 限流抖动)第二遍降并发补刷。
    modes, failed = _pass(work, symbols, workers)
    if failed:
        modes2, failed = _pass(work, failed, max(2, workers // 3))
        modes += modes2
    return {"ok": len(symbols) - len(failed), "fail": len(failed), "modes": dict(modes), "total": len(symbols)}


def main() -> None:
    print(json.dumps(refresh(full="--full" in sys.argv)))


if __name__ == "__main__":
    main()
