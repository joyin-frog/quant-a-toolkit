"""网页后端 JSON 入口：跑核心-卫星策略，把结果以 JSON 打到 stdout，供前端消费。

用法：python -m quant_a.cs_web --capital 200000 --holdings 17 --ai_weight 0.15
前端的 API 路由会以子进程方式调它、解析 stdout 的 JSON。
"""

from __future__ import annotations

import argparse
import json

import pandas as pd

from quant_a.cs_pipeline import run_cs_pipeline


def _sample_curve(curve: pd.Series, max_points: int = 240) -> list[dict[str, object]]:
    # 下采样到约月频，控制 JSON 体积。
    monthly = curve.resample("ME").last().dropna()
    if len(monthly) > max_points:
        step = len(monthly) // max_points + 1
        monthly = monthly.iloc[::step]
    return [{"date": d.strftime("%Y-%m"), "value": round(float(v), 4)} for d, v in monthly.items()]


def build_payload(capital: float, holdings: int, ai_weight: float) -> dict[str, object]:
    result = run_cs_pipeline(capital=capital, core_holdings=holdings, ai_weight=ai_weight)
    start, end = result["date_range"]
    buy_list = result["buy_list"]
    equity = result["equity_curve"]
    bench = result["benchmark_curve"]
    bench_aligned = bench.reindex(equity.index).ffill()

    e_pts = _sample_curve(equity)
    b_pts = {p["date"]: p["value"] for p in _sample_curve(bench_aligned)}
    curve = [{"date": p["date"], "strategy": p["value"], "benchmark": b_pts.get(p["date"])} for p in e_pts]

    return {
        "params": {"capital": capital, "holdings": holdings, "ai_weight": ai_weight},
        "as_of": end.strftime("%Y-%m-%d"),
        "range": f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}",
        "metrics": {k: round(float(v), 4) for k, v in result["metrics"].items()},
        "benchmark": {k: round(float(v), 4) for k, v in result["benchmark_metrics"].items()},
        "rolling12m": {k: round(float(v), 4) for k, v in result["rolling12m"].items()},
        "core_sectors": result["core_sectors"],
        "avg_cash_pct": round(float(result["avg_cash_pct"]), 4),
        "invested": float(buy_list.attrs.get("invested", 0)),
        "cash_left": float(buy_list.attrs.get("cash_left", 0)),
        "holdings_list": buy_list.to_dict(orient="records"),
        "curve": curve,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=float, default=200000)
    parser.add_argument("--holdings", type=int, default=17)
    parser.add_argument("--ai_weight", type=float, default=0.15)
    args = parser.parse_args()
    payload = build_payload(args.capital, args.holdings, args.ai_weight)
    print(json.dumps(payload, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
