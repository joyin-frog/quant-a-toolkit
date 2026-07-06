from __future__ import annotations

import argparse
import json

from quant_a.platform.adapters import run_core_satellite_adapter, run_multi_factor_adapter
from quant_a.platform.contracts import ParamSpec, SleeveSpec
from quant_a.platform.registry import StrategyDefinition, StrategyRegistry
from quant_a.platform.reporting import save_strategy_result

_CAPITAL = ParamSpec("capital", "number", 200_000, label="本金（元）", minimum=10_000)
_UNIVERSE = ParamSpec("universe", "choice", "csi1000", label="股票池", choices=("csi1000", "mainboard"))


def build_registry() -> StrategyRegistry:
    from quant_a.strategies.active_leader.pipeline import run_active_leader
    from quant_a.strategies.ai_leader.pipeline import run_ai_leader

    registry = StrategyRegistry()
    registry.register(StrategyDefinition(
        "active_leader", "活跃龙头", "图片博主的底仓+机动仓规则",
        run_active_leader,
        params=(_CAPITAL, _UNIVERSE),
        sleeves=(SleeveSpec("long", "底仓"), SleeveSpec("tactical", "机动仓")),
    ))
    registry.register(StrategyDefinition(
        "core_satellite", "沪深300核心-卫星", "分散核心+AI产业链卫星",
        run_core_satellite_adapter,
        params=(
            _CAPITAL,
            ParamSpec("holdings", "integer", 17, label="核心持仓只数", minimum=8, maximum=30, step=1),
            ParamSpec("ai_weight", "number", 0.15, label="AI 卫星比例", minimum=0.0, maximum=0.5, step=0.01),
        ),
        sleeves=(SleeveSpec("核心", "核心"), SleeveSpec("AI卫星", "AI卫星")),
    ))
    registry.register(StrategyDefinition(
        "multi_factor", "中证1000低波动多因子", "月度多因子组合",
        run_multi_factor_adapter,
        params=(
            _CAPITAL,
            ParamSpec("holdings", "integer", 30, label="持仓只数", minimum=10, maximum=40, step=1),
            _UNIVERSE,
        ),
        sleeves=(SleeveSpec("组合", "组合"),),
    ))
    registry.register(StrategyDefinition(
        "ai_leader", "主板AI产业链龙头", "AI算力全产业链子链龙头（仅主板，排除创业板/科创板）",
        run_ai_leader,
        params=(_CAPITAL,),
        sleeves=(SleeveSpec("AI", "AI龙头"),),
    ))
    return registry


def main() -> None:
    parser = argparse.ArgumentParser(description="统一多策略运行入口")
    parser.add_argument("--list", action="store_true", help="列出可用策略")
    parser.add_argument("--json", action="store_true", help="--list 时输出 JSON 元数据（参数/仓位分层）")
    parser.add_argument("--strategy", default="active_leader")
    parser.add_argument("--capital", type=float, default=None)
    parser.add_argument("--holdings", type=int, default=None)
    parser.add_argument("--ai_weight", type=float, default=None)
    parser.add_argument("--universe", default=None)
    args = parser.parse_args()
    registry = build_registry()
    if args.list:
        if args.json:
            print(json.dumps([item.metadata() for item in registry.list()], ensure_ascii=False))
        else:
            for item in registry.list():
                names = ", ".join(sorted(item.param_names()))
                print(f"{item.strategy_id:18s} {item.name} - {item.description}（参数: {names}）")
        return
    candidates = {
        "capital": args.capital,
        "holdings": args.holdings,
        "ai_weight": args.ai_weight,
        "universe": args.universe,
    }
    try:
        params = registry.build_params(args.strategy, candidates, strict=True)
        result = registry.run(args.strategy, **params)
    except ValueError as exc:
        parser.error(str(exc))
        return
    save_strategy_result(result)
    print(json.dumps(result.summary(), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
