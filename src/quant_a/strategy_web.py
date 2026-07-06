"""统一策略网页 JSON 入口。

- `--list`：输出所有策略的元数据（参数声明/仓位分层），供 /api/strategies 渲染前端表单。
- 运行：参数按 StrategyDefinition 的声明组装，策略不认识的旗标会被忽略，
  新增策略不需要再改这里的任何分支。
"""

from __future__ import annotations

import argparse
import json

from quant_a.runner import build_registry
from quant_a.walkforward import rolling_return_summary
from quant_a.webjson import clean_number, monthly_curve

# 只记账、不可回测的账户（实盘记账页可切换；主页"生成清单"不显示）。
LEDGER_ACCOUNTS: list[dict[str, object]] = [
    {
        "strategy_id": "manual",
        "name": "手动实盘",
        "description": "真实券商账户（录屏导入 + 日常记账）",
        "params": [],
        "sleeves": [{"value": "自选", "label": "自选"}],
        "runnable": False,
        "cadence": {"kind": "none"},
    },
    {
        "strategy_id": "ai_paper",
        "name": "AI纸面跟踪",
        "description": "AI+机器人策略的模拟盘（虚拟资金，按月记录清单执行）",
        "params": [],
        "sleeves": [{"value": "AI", "label": "AI龙头"}],
        "runnable": False,
        "cadence": {"kind": "monthly", "day": 15},
    },
]


def _holdings(result, capital: float) -> list[dict[str, object]]:
    rows = []
    for raw in result.holdings.to_dict(orient="records"):
        code = str(raw.get("code", raw.get("symbol", ""))).zfill(6)
        shares = int(raw.get("shares", int(raw.get("lots", 0)) * 100))
        price = float(raw.get("price", raw.get("entry_price", 0)) or 0)
        cost = float(raw.get("cost", shares * price) or 0)
        rows.append({
            "sleeve": str(raw.get("sleeve", "组合")),
            "theme": str(raw.get("theme", "")),
            "code": code,
            "name": str(raw.get("name", "")),
            "price": round(price, 3),
            "lots": int(raw.get("lots", shares // 100)),
            "cost": round(cost, 0),
            "weight": clean_number(raw.get("weight", cost / capital if capital else 0)) or 0,
        })
    return rows


def build_payload(strategy_id: str, **candidates) -> dict[str, object]:
    registry = build_registry()
    params = registry.build_params(strategy_id, candidates)
    result = registry.run(strategy_id, **params)
    capital = float(params.get("capital") or 200_000)
    rows = _holdings(result, capital)
    invested = sum(float(row["cost"]) for row in rows)
    start, end = result.date_range
    rolling = result.diagnostics.get("rolling12m") or rolling_return_summary(
        result.equity_curve.pct_change(fill_method=None).fillna(0.0)
    )
    return {
        "strategy_id": strategy_id,
        "strategy_name": result.name,
        "params": params,
        "as_of": end.strftime("%Y-%m-%d"),
        "range": f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}",
        "metrics": {key: clean_number(value) for key, value in result.metrics.items()},
        "benchmark": {key: clean_number(value) for key, value in result.benchmark_metrics.items()},
        "rolling12m": {key: clean_number(value) for key, value in rolling.items()},
        "core_sectors": result.diagnostics.get("core_sectors", {}),
        "avg_cash_pct": clean_number(result.diagnostics.get("avg_cash_pct")),
        "invested": invested,
        "cash_left": max(0.0, capital - invested),
        "holdings_list": rows,
        "curve": monthly_curve(result.equity_curve, result.benchmark_curve),
        "warnings": result.warnings,
        # 迁移模式（account 参数）下：从账户现有持仓到目标组合的 卖出/保留/买入 过渡清单
        "transition": (
            {"summary": result.diagnostics["transition"], "orders": result.diagnostics.get("transition_orders", [])}
            if "transition" in result.diagnostics else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="输出策略元数据 JSON")
    parser.add_argument("--strategy", default="core_satellite")
    parser.add_argument("--capital", type=float, default=None)
    parser.add_argument("--holdings", type=int, default=None)
    parser.add_argument("--universe", default=None)
    parser.add_argument("--account", default=None)
    parser.add_argument("--locked", default=None)
    args = parser.parse_args()
    if args.list:
        entries = [{**item.metadata(), "runnable": True} for item in build_registry().list()]
        print(json.dumps(entries + LEDGER_ACCOUNTS, ensure_ascii=False))
        return
    payload = build_payload(
        args.strategy,
        capital=args.capital,
        holdings=args.holdings,
        universe=args.universe,
        account=args.account,
        locked=args.locked,
    )
    print(json.dumps(payload, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
