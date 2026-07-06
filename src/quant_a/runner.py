from __future__ import annotations

import argparse
import json

from quant_a.platform.contracts import ParamSpec, SleeveSpec
from quant_a.platform.registry import StrategyDefinition, StrategyRegistry
from quant_a.platform.reporting import save_strategy_result

_CAPITAL = ParamSpec("capital", "number", 200_000, label="本金（元）", minimum=10_000)
_UNIVERSE = ParamSpec("universe", "choice", "csi1000", label="股票池", choices=("csi1000", "mainboard"))
_ACCOUNT = ParamSpec("account", "choice", "", label="从账户迁移", choices=("", "manual", "ai_paper"))
_LOCKED = ParamSpec("locked", "text", "", label="锁仓代码（逗号分隔，策略不卖）")


def build_registry() -> StrategyRegistry:
    """正式策略只保留 3 条线：低波长线（主力）、AI+机器人（信仰仓）、活跃龙头（研究/对照）。

    - 低波长线沿用 strategy_id=core_satellite（记账账户与 reports/ 目录的连续性），
      即原核心-卫星去掉 AI 卫星；AI 敞口独立成 ai_leader。
    - 中证1000多因子退出注册表，研究线保留 CLI：python -m quant_a.factor_pipeline。
    """
    from quant_a.strategies.active_leader.pipeline import run_active_leader
    from quant_a.strategies.ai_leader.pipeline import run_ai_leader
    from quant_a.strategies.lowvol_core import run_lowvol_core

    registry = StrategyRegistry()
    registry.register(StrategyDefinition(
        "core_satellite", "低波长线（沪深300核心）", "5因子低波主导+缓冲带+行业上限，月度调仓；支持从现有账户迁移+锁仓",
        run_lowvol_core,
        params=(
            _CAPITAL,
            ParamSpec("holdings", "integer", 17, label="持仓只数", minimum=5, maximum=30, step=1),
            _ACCOUNT,
            _LOCKED,
        ),
        sleeves=(SleeveSpec("核心", "核心"),),
        cadence={"kind": "monthly", "day": 15},
    ))
    registry.register(StrategyDefinition(
        "ai_leader", "AI+机器人主板龙头", "AI算力全产业链+机器人子链龙头（仅主板）；支持从现有账户迁移+锁仓",
        run_ai_leader,
        params=(_CAPITAL, _ACCOUNT, _LOCKED),
        sleeves=(SleeveSpec("AI", "AI龙头"),),
        cadence={"kind": "monthly", "day": 15},
    ))
    registry.register(StrategyDefinition(
        "active_leader", "活跃龙头", "图片博主的底仓+机动仓规则（研究/对照，回测未验证盈利）",
        run_active_leader,
        params=(_CAPITAL, _UNIVERSE),
        sleeves=(SleeveSpec("long", "底仓"), SleeveSpec("tactical", "机动仓")),
        cadence={"kind": "daily_signal"},
    ))
    return registry


def main() -> None:
    parser = argparse.ArgumentParser(description="统一多策略运行入口")
    parser.add_argument("--list", action="store_true", help="列出可用策略")
    parser.add_argument("--json", action="store_true", help="--list 时输出 JSON 元数据（参数/仓位分层）")
    parser.add_argument("--strategy", default="core_satellite")
    parser.add_argument("--capital", type=float, default=None)
    parser.add_argument("--holdings", type=int, default=None)
    parser.add_argument("--universe", default=None)
    parser.add_argument("--account", default=None, help="从该记账账户的现有持仓出发生成迁移清单（如 manual）")
    parser.add_argument("--locked", default=None, help="锁仓代码，逗号分隔（策略不卖、占名额）")
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
        "universe": args.universe,
        "account": args.account,
        "locked": args.locked,
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
