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


def _kind(symbol: str) -> str:
    """按代码段路由抓数通道：5/1 开头是场内基金（ETF），其余按股票（实盘账户里有 ETF 持仓）。"""
    return "etf" if symbol and symbol[0] in "15" else "stock"


def _refresh_one(symbol: str) -> str:
    if not cache_exists(symbol):
        save_cached_bars(symbol, fetch_bars(symbol, _kind(symbol)))
        return "full"
    cached = load_cached_bars(symbol).sort_values("date")
    if cached.empty:
        save_cached_bars(symbol, fetch_bars(symbol, _kind(symbol)))
        return "full"

    last = cached["date"].max()
    new = fetch_bars(symbol, _kind(symbol), start=last.strftime("%Y%m%d"))
    if new.empty:
        return "current"
    new = new.sort_values("date")

    # 前复权基准校验：重叠日(last)价格变了 → 发生分红/拆股、整段被重算 → 重下完整历史。
    overlap = new[new["date"] == last]
    cached_close = cached.loc[cached["date"] == last, "close"]
    if not overlap.empty and not cached_close.empty:
        base = float(cached_close.iloc[0])
        if abs(float(overlap["close"].iloc[0]) - base) > max(0.01, 0.003 * base):
            save_cached_bars(symbol, fetch_bars(symbol, _kind(symbol)))
            return "rebased"

    add = new[new["date"] > last]
    if add.empty:
        return "current"
    merged = pd.concat([cached, add]).drop_duplicates("date", keep="last").sort_values("date")
    save_cached_bars(symbol, merged)
    return "incr"


def _refresh_full(symbol: str) -> str:
    save_cached_bars(symbol, fetch_bars(symbol, _kind(symbol)))
    return "full"


def _log(msg: str) -> None:
    """进度打到 stderr（stdout 留给最后那行 JSON）；网页端 runPython 会把 stderr 实时转到 dev 终端。"""
    print(msg, file=sys.stderr, flush=True)


def _progress(done: int, total: int, fail: int, phase: str) -> None:
    """机器可读进度行（网页进度条解析这行）；与上面的人类日志并存。"""
    print(f'PROGRESS:{{"done": {done}, "total": {total}, "fail": {fail}, "phase": "{phase}"}}', file=sys.stderr, flush=True)


def _pass(work, syms: list[str], workers: int, phase: str = "pull") -> tuple[Counter, list[str]]:
    """并行刷一批,返回(模式计数, 失败的代码)。每只各写自己的缓存文件,线程安全。"""
    modes: Counter[str] = Counter()
    failed: list[str] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, s): s for s in syms}
        for fut in as_completed(futures):
            done += 1
            try:
                modes[fut.result()] += 1
            except Exception:  # noqa: BLE001
                failed.append(futures[fut])
            if done % 10 == 0 or done == len(syms):
                _progress(done, len(syms), len(failed), phase)
                _log(f"[refresh]   进度 {done}/{len(syms)}（失败 {len(failed)}）")
    return modes, failed


def refresh(full: bool = False, workers: int = 8) -> dict[str, object]:
    """刷新范围 = 沪深300主板 ∪ 旧AI卫星池 ∪ AI+机器人策略池 ∪ 各记账账户当前持仓（含ETF）。"""
    hs = pd.read_csv(DATA_DIR / "hs300_mainboard.csv", dtype=str)["symbol"].str.zfill(6).tolist()
    symbols = set(hs) | set(ai_symbols())
    try:
        from quant_a.strategies.ai_leader.pool import mainboard_chains

        chains, _, _ = mainboard_chains()
        symbols |= {code for codes in chains.values() for code in codes}
    except Exception:  # noqa: BLE001
        pass
    try:  # 记账账户持仓（manual/纸面等）也要有最新价，否则持仓盈亏/净值失真
        import sqlite3

        from quant_a.portfolio_db import DB_PATH

        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as conn:
                held = {str(r[0]).zfill(6) for r in conn.execute("SELECT DISTINCT code FROM trades")}
            symbols |= held
    except Exception:  # noqa: BLE001
        pass
    symbols = sorted(symbols)
    work = _refresh_full if full else _refresh_one
    _log(f"[refresh] 开始：{len(symbols)} 只 | workers={workers} | full={full}")
    # 纯网络 I/O -> 并行拉。第一遍高并发抢速度;失败的(多为 eastmoney 限流抖动)第二遍降并发补刷。
    modes, failed = _pass(work, symbols, workers, phase="pull")
    _log(f"[refresh] 第一遍完成：ok={len(symbols) - len(failed)} fail={len(failed)}")
    if failed:
        w2 = max(2, workers // 3)
        _log(f"[refresh] 第二遍补刷 {len(failed)} 只（workers={w2}）…")
        modes2, failed = _pass(work, failed, w2, phase="retry")
        modes += modes2
    result = {"ok": len(symbols) - len(failed), "fail": len(failed), "modes": dict(modes), "total": len(symbols)}
    _log(f"[refresh] 完成：{result}")
    return result


def main() -> None:
    print(json.dumps(refresh(full="--full" in sys.argv)))


if __name__ == "__main__":
    main()
