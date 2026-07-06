"""多策略运行平台：统一契约、注册、运行和结果落盘。"""

from quant_a.platform.contracts import StrategyResult
from quant_a.platform.registry import StrategyDefinition, StrategyRegistry

__all__ = ["StrategyDefinition", "StrategyRegistry", "StrategyResult"]
