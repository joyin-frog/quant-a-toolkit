"""【兼容入口】核心-卫星网页 JSON CLI，已委托给统一入口 quant_a.strategy_web。

网页前端现在直接调 strategy_web（多策略）；本模块只保留旧命令行用法：
    python -m quant_a.cs_web --capital 200000 --holdings 17 --ai_weight 0.15
"""

from __future__ import annotations

import argparse
import json

from quant_a.strategy_web import build_payload as _strategy_payload
from quant_a.webjson import clean_number as _num  # noqa: F401  # 兼容旧引用（测试/脚本用过 cs_web._num）


def build_payload(capital: float, holdings: int, ai_weight: float) -> dict[str, object]:
    return _strategy_payload("core_satellite", capital=capital, holdings=holdings, ai_weight=ai_weight)


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
