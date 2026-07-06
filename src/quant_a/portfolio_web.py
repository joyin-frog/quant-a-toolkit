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
from quant_a.portfolio_db import DEFAULT_STRATEGY_ID, add_cash_flow, add_trade, current_positions, get_trades, reconstruct


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


def _holdings(refresh: bool = False, strategy_id: str = DEFAULT_STRATEGY_ID) -> dict[str, object]:
    positions = current_positions(strategy_id)
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


def _report(strategy_id: str = DEFAULT_STRATEGY_ID) -> dict[str, object]:
    rc = reconstruct(strategy_id)
    if rc is None:
        return {"empty": True}
    equity = rc["equity"]
    positive = equity[equity > 0]
    if positive.empty:
        return {"empty": True}
    # 时间加权收益（TWR）：当日收益 =(当日净资产 - 当日出入金)/前一日净资产 - 1。
    # 中途入金只扩大规模、不算收益；否则多笔入金会被误报成暴涨。
    equity = equity.loc[positive.index[0]:]
    external = rc["external_flows"].reindex(equity.index).fillna(0.0)
    prev = equity.shift(1)
    real_ret = ((equity - external) / prev - 1.0).where(prev > 0, 0.0).fillna(0.0)
    nav = (1.0 + real_ret).cumprod()
    window = nav.index

    out: dict[str, object] = {
        "empty": False,
        "since": window[0].strftime("%Y-%m-%d"),
        "as_of": window[-1].strftime("%Y-%m-%d"),
        "days": int(len(window)),
        "equity_yuan": round(float(equity.loc[window[-1]]), 0),
        "net_deposits": round(float(external.sum()), 0),
        "pnl_yuan": round(float(equity.loc[window[-1]] - external.sum()), 0),
        "real_metrics": _round_metrics(real_ret, nav),
        "current_holdings": rc["current_holdings"],
        "n_trades": int(len(get_trades(strategy_id))),
        "strategy_id": strategy_id,
    }

    # 对比：把策略回测 + 基准对齐到实盘同一窗口、各自基1，算跟踪误差和损耗。
    # 同一天内复用 reports/ 下的回测产物（行情按日更新，没必要每次请求都重跑几十秒回测）。
    try:
        from quant_a.platform.reporting import load_cached_curves, save_strategy_result
        from quant_a.runner import build_registry

        cached = load_cached_curves(strategy_id)
        if cached is not None:
            equity_curve, benchmark_curve = cached["equity_curve"], cached["benchmark_curve"]
            compare_params = cached["params"]
            out["compare_source"] = "cached"
        else:
            res = build_registry().run(strategy_id)
            save_strategy_result(res)
            equity_curve, benchmark_curve = res.equity_curve, res.benchmark_curve
            compare_params = res.params
            out["compare_source"] = "fresh"
        # ⚠️ 对比回测跑的是该策略的参数（通常为默认 20万/默认池），不是你实盘账户的实际本金/池子；
        # 两边各自归一后比较，本金差异基本抵消，但股票池不同时跟踪误差仅供参考。参数如实回显：
        out["compare_params"] = compare_params
        out["benchmark_source"] = "策略统一股票池基准（与 /review 归因页的『合格核心股等权』口径不同）"
        strat = equity_curve.reindex(window).ffill().bfill()
        strat_nav = strat / float(strat.iloc[0])
        bench = benchmark_curve.reindex(window).ffill().bfill()
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


def _add_batch(strategy_id: str, payload: dict) -> dict[str, object]:
    """批量记账（一键按清单入账）。payload = {"trades": [...], "flows": [...]}。"""
    n_trades = 0
    for t in payload.get("trades", []):
        add_trade(
            t["date"], t["code"], t.get("name", ""), t["action"], t["shares"], t["price"],
            fee=float(t.get("fee", 0) or 0), sleeve=t.get("sleeve", ""), note=t.get("note", ""),
            strategy_id=strategy_id,
        )
        n_trades += 1
    n_flows = 0
    for f in payload.get("flows", []):
        add_cash_flow(f["date"], f["amount"], f.get("type", "deposit"), f.get("note", ""), strategy_id=strategy_id)
        n_flows += 1
    return {"ok": True, "trades": n_trades, "flows": n_flows}


# 账户 → 对照策略：复盘"该买什么 vs 实际持有什么"时用哪张目标清单
REVIEW_TARGET = {"core_satellite": "core_satellite", "ai_paper": "ai_leader", "manual": "core_satellite"}


def _review_lite(account: str, target_sid: str | None = None) -> dict[str, object]:
    """通用执行复盘：账户当前持仓 vs 对照策略的目标清单 → 遵从率 + 该买没买 + 计划外持仓。

    比 core_satellite 的完整归因轻：不算收益贡献，只看组合构成的偏离——够回答
    "我是在执行策略，还是在自由发挥"。
    """
    import pandas as pd

    target_sid = target_sid or REVIEW_TARGET.get(account, "core_satellite")
    from quant_a.platform.reporting import load_cached_holdings, save_strategy_result

    holdings_df = load_cached_holdings(target_sid)
    if holdings_df is None:
        from quant_a.runner import build_registry

        res = build_registry().run(target_sid)
        save_strategy_result(res)
        holdings_df = res.holdings
    code_col = "code" if "code" in holdings_df.columns else "symbol"
    target_names = dict(zip(holdings_df[code_col].astype(str).str.zfill(6), holdings_df.get("name", "").astype(str)))
    target = list(target_names)

    positions = current_positions(account)
    held_names: dict[str, str] = {}
    if not positions.empty:
        for _, p in positions.iterrows():
            code = str(p["code"]).zfill(6)
            if code.startswith(("60", "00")):  # 只比个股；ETF 不在策略清单口径内
                held_names[code] = str(p.get("name", ""))
    held = list(held_names)

    matched = [c for c in held if c in target]
    missing = [c for c in target if c not in held]
    extra = [c for c in held if c not in target]
    return {
        "account": account,
        "target_strategy": target_sid,
        "n_target": len(target),
        "n_held_stocks": len(held),
        "n_matched": len(matched),
        "compliance": _num(len(matched) / len(target)) if target else None,
        "matched": [{"code": c, "name": target_names.get(c, held_names.get(c, ""))} for c in matched],
        "missing": [{"code": c, "name": target_names.get(c, "")} for c in missing],
        "extra": [{"code": c, "name": held_names.get(c, "")} for c in extra],
        "note": "遵从率 = 持有的目标股 / 目标清单数；ETF 与现金不参与该口径。",
    }


def _review(rebalance_date: str | None = None) -> dict[str, object]:
    from quant_a.review import _load_context, attribution, execution_scorecard, factor_health

    ctx = _load_context()
    return {
        "attribution": attribution(ctx),
        "execution": execution_scorecard(rebalance_date, ctx),
        "factor_health": factor_health(ctx),
    }


def _factor_health() -> dict[str, object]:
    from quant_a.review import factor_health

    return factor_health()


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
    t.add_argument("--strategy", default=DEFAULT_STRATEGY_ID)

    c = sub.add_parser("add-cash")
    c.add_argument("--date", required=True)
    c.add_argument("--amount", type=float, required=True)
    c.add_argument("--type", default="deposit")
    c.add_argument("--strategy", default=DEFAULT_STRATEGY_ID)

    ls = sub.add_parser("list")
    ls.add_argument("--strategy", default=DEFAULT_STRATEGY_ID)
    rp = sub.add_parser("report")
    rp.add_argument("--strategy", default=DEFAULT_STRATEGY_ID)
    h = sub.add_parser("holdings")
    h.add_argument("--refresh", action="store_true")
    h.add_argument("--strategy", default=DEFAULT_STRATEGY_ID)
    sub.add_parser("next-rebalance")
    ab = sub.add_parser("add-batch")
    ab.add_argument("--strategy", required=True)
    dt = sub.add_parser("del-trade")
    dt.add_argument("--id", type=int, required=True)
    dt.add_argument("--strategy", required=True)
    dc = sub.add_parser("del-cash")
    dc.add_argument("--id", type=int, required=True)
    dc.add_argument("--strategy", required=True)
    rl = sub.add_parser("review-lite")
    rl.add_argument("--strategy", required=True, help="记账账户 id")
    rl.add_argument("--target", default=None, help="对照策略 id（默认按账户映射）")
    rv = sub.add_parser("review")
    rv.add_argument("--date", default=None)
    rv.add_argument("--strategy", default=DEFAULT_STRATEGY_ID)
    sub.add_parser("factor-health")

    args = parser.parse_args()
    if args.cmd == "add-trade":
        tid = add_trade(args.date, args.code, args.name, args.action, args.shares, args.price, args.fee, args.sleeve, strategy_id=args.strategy)
        print(json.dumps({"ok": True, "id": tid}))
    elif args.cmd == "add-cash":
        cid = add_cash_flow(args.date, args.amount, args.type, strategy_id=args.strategy)
        print(json.dumps({"ok": True, "id": cid}))
    elif args.cmd == "list":
        df = get_trades(args.strategy)
        print(json.dumps(df.to_dict(orient="records"), ensure_ascii=False, default=str))
    elif args.cmd == "report":
        print(json.dumps(_report(args.strategy), ensure_ascii=False, default=str))
    elif args.cmd == "holdings":
        print(json.dumps(_holdings(refresh=args.refresh, strategy_id=args.strategy), ensure_ascii=False, default=str))
    elif args.cmd == "next-rebalance":
        print(json.dumps(_next_rebalance(), ensure_ascii=False))
    elif args.cmd == "add-batch":
        import sys as _sys

        payload = json.loads(_sys.stdin.read() or "{}")
        print(json.dumps(_add_batch(args.strategy, payload), ensure_ascii=False))
    elif args.cmd == "del-trade":
        from quant_a.portfolio_db import delete_trade

        n = delete_trade(args.id, strategy_id=args.strategy)
        print(json.dumps({"ok": n > 0, "deleted": n}))
    elif args.cmd == "del-cash":
        from quant_a.portfolio_db import delete_cash_flow

        n = delete_cash_flow(args.id, strategy_id=args.strategy)
        print(json.dumps({"ok": n > 0, "deleted": n}))
    elif args.cmd == "review-lite":
        print(json.dumps(_review_lite(args.strategy, args.target), ensure_ascii=False, default=str))
    elif args.cmd == "review":
        # 复盘归因绑定核心-卫星的选股上下文；别的策略账户直接调会把 cs 的归因错安到它头上。
        if args.strategy != "core_satellite":
            print(json.dumps({"error": f"复盘目前只支持 core_satellite 策略（收到 {args.strategy}）"}, ensure_ascii=False))
        else:
            print(json.dumps(_review(args.date), ensure_ascii=False, default=str))
    elif args.cmd == "factor-health":
        print(json.dumps(_factor_health(), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
