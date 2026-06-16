"""实盘记账的 JSON CLI：记成交 / 记资金 / 列流水 / 出绩效报告。供网页 API 与命令行调用。

子命令：
  add-trade  --date --code --name --action --shares --price --fee --sleeve
  add-cash   --date --amount --type
  list       列出全部成交（JSON）
  report     实盘绩效报告（实盘净值 + 对比回测/基准 + 跟踪误差，JSON）
"""

from __future__ import annotations

import argparse
import calendar
import json
from datetime import date

import numpy as np
import pandas as pd

from quant_a.cache import cache_exists, load_cached_bars
from quant_a.config import REBALANCE_DAY
from quant_a.metrics import calculate_metrics
from quant_a.portfolio_db import add_cash_flow, add_trade, current_positions, get_trades, reconstruct


def _next_rebalance(rebalance_day: int = REBALANCE_DAY or 15) -> dict[str, object]:
    today = date.today()
    if today.day < rebalance_day:
        target = today.replace(day=rebalance_day)
    else:
        if today.month == 12:
            ny, nm = today.year + 1, 1
        else:
            ny, nm = today.year, today.month + 1
        day = min(rebalance_day, calendar.monthrange(ny, nm)[1])
        target = date(ny, nm, day)
    return {
        "rebalance_day": rebalance_day,
        "next_date": target.strftime("%Y-%m-%d"),
        "days_until": (target - today).days,
        "is_rebalance_window": abs((target - today).days) <= 1 or today.day == rebalance_day,
    }


def _holdings(refresh: bool = False) -> dict[str, object]:
    positions = current_positions()
    if positions.empty:
        return {"empty": True, "next_rebalance": _next_rebalance()}
    if refresh:
        from quant_a.refresh_cs import _refresh_one

        for code in positions["code"]:
            try:
                _refresh_one(code)
            except Exception:  # noqa: BLE001
                pass

    rows: list[dict[str, object]] = []
    total_value = total_cost = 0.0
    as_of = ""
    for _, p in positions.iterrows():
        if not cache_exists(p["code"]):
            continue
        bars = load_cached_bars(p["code"]).sort_values("date")
        if bars.empty:
            continue
        cur = float(bars["close"].iloc[-1])
        prev = float(bars["close"].iloc[-2]) if len(bars) >= 2 else cur
        as_of = bars["date"].iloc[-1].strftime("%Y-%m-%d")
        mv = p["shares"] * cur
        cost = p["shares"] * p["avg_cost"]
        total_value += mv
        total_cost += cost
        rows.append(
            {
                "code": p["code"],
                "name": p["name"],
                "sleeve": p["sleeve"],
                "shares": int(p["shares"]),
                "avg_cost": round(float(p["avg_cost"]), 3),
                "price": round(cur, 2),
                "value": round(mv, 0),
                "pnl": round(mv - cost, 0),
                "pnl_pct": _num((mv - cost) / cost if cost else 0.0),
                "today_pct": _num((cur - prev) / prev if prev else 0.0),
            }
        )
    rows.sort(key=lambda r: r["pnl_pct"] if r["pnl_pct"] is not None else 0, reverse=True)
    return {
        "empty": False,
        "as_of": as_of,
        "positions": rows,
        "total_value": round(total_value, 0),
        "total_cost": round(total_cost, 0),
        "total_pnl": round(total_value - total_cost, 0),
        "total_pnl_pct": _num((total_value - total_cost) / total_cost if total_cost else 0.0),
        "next_rebalance": _next_rebalance(),
    }


def _num(x) -> float | None:
    """NaN/Inf → None（JS 的 JSON.parse 不认 NaN，必须清洗）。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, 4) if np.isfinite(v) else None


def _round_metrics(returns: pd.Series, equity: pd.Series) -> dict[str, float | None]:
    return {k: _num(v) for k, v in calculate_metrics(returns, equity).items()}


def _report() -> dict[str, object]:
    rc = reconstruct()
    if rc is None:
        return {"empty": True}
    equity = rc["equity"]
    positive = equity[equity > 0]
    if positive.empty:
        return {"empty": True}
    base = float(positive.iloc[0])
    nav = equity / base
    nav = nav.loc[positive.index[0]:]
    real_ret = nav.pct_change(fill_method=None).fillna(0.0)
    window = nav.index

    out: dict[str, object] = {
        "empty": False,
        "since": window[0].strftime("%Y-%m-%d"),
        "as_of": window[-1].strftime("%Y-%m-%d"),
        "days": int(len(window)),
        "equity_yuan": round(float(equity.loc[window[-1]]), 0),
        "real_metrics": _round_metrics(real_ret, nav),
        "current_holdings": rc["current_holdings"],
        "n_trades": int(len(get_trades())),
    }

    # 对比：把策略回测 + 基准对齐到实盘同一窗口、各自基1，算跟踪误差和损耗。
    try:
        from quant_a.cs_pipeline import run_cs_pipeline

        res = run_cs_pipeline()
        strat = res["equity_curve"].reindex(window).ffill().bfill()
        bench = res["benchmark_curve"].reindex(window).ffill().bfill()
        strat_nav = strat / float(strat.iloc[0])
        bench_nav = bench / float(bench.iloc[0])
        strat_ret = strat_nav.pct_change(fill_method=None).fillna(0.0)
        out["tracking_error"] = _num((real_ret - strat_ret).std() * np.sqrt(252))
        out["drag_vs_backtest"] = _num(nav.iloc[-1] - strat_nav.iloc[-1])
        out["excess_vs_benchmark"] = _num(nav.iloc[-1] - bench_nav.iloc[-1])
        step = max(1, len(window) // 180)
        out["curve"] = [
            {
                "date": d.strftime("%Y-%m-%d"),
                "real": _num(nav.loc[d]),
                "strategy": _num(strat_nav.loc[d]),
                "benchmark": _num(bench_nav.loc[d]),
            }
            for d in window[::step]
        ]
    except Exception as error:  # noqa: BLE001
        out["compare_error"] = str(error)
        out["curve"] = [
            {"date": d.strftime("%Y-%m-%d"), "real": round(float(nav.loc[d]), 4)} for d in window
        ]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("add-trade")
    t.add_argument("--date", required=True)
    t.add_argument("--code", required=True)
    t.add_argument("--name", default="")
    t.add_argument("--action", required=True, choices=["buy", "sell"])
    t.add_argument("--shares", type=int, required=True)
    t.add_argument("--price", type=float, required=True)
    t.add_argument("--fee", type=float, default=0.0)
    t.add_argument("--sleeve", default="")

    c = sub.add_parser("add-cash")
    c.add_argument("--date", required=True)
    c.add_argument("--amount", type=float, required=True)
    c.add_argument("--type", default="deposit")

    sub.add_parser("list")
    sub.add_parser("report")
    h = sub.add_parser("holdings")
    h.add_argument("--refresh", action="store_true")
    sub.add_parser("next-rebalance")

    args = parser.parse_args()
    if args.cmd == "add-trade":
        tid = add_trade(args.date, args.code, args.name, args.action, args.shares, args.price, args.fee, args.sleeve)
        print(json.dumps({"ok": True, "id": tid}))
    elif args.cmd == "add-cash":
        cid = add_cash_flow(args.date, args.amount, args.type)
        print(json.dumps({"ok": True, "id": cid}))
    elif args.cmd == "list":
        df = get_trades()
        print(json.dumps(df.to_dict(orient="records"), ensure_ascii=False, default=str))
    elif args.cmd == "report":
        print(json.dumps(_report(), ensure_ascii=False, default=str))
    elif args.cmd == "holdings":
        print(json.dumps(_holdings(refresh=args.refresh), ensure_ascii=False, default=str))
    elif args.cmd == "next-rebalance":
        print(json.dumps(_next_rebalance(), ensure_ascii=False))


if __name__ == "__main__":
    main()
