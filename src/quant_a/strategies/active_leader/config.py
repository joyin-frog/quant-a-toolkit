from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ActiveLeaderConfig:
    """图片中所有数字规则的唯一参数来源。"""

    max_leaders: int = 3
    lookback_days: int = 60
    min_limit_ups: int = 3
    turnover_proxy_low: float = 0.5
    turnover_proxy_high: float = 1.5
    long_weight: float = 0.50
    tactical_weight_normal: float = 0.20
    tactical_weight_hot: float = 0.50
    hot_limit_up_count: int = 50
    long_take_profit: float = 0.30
    long_stop_loss: float = -0.08
    tactical_take_profit: float = 0.07
    tactical_stop_loss: float = -0.05
    tactical_max_days: int = 5
    tactical_up_days_exit: int = 3
    tactical_down_days_entry: int = 4
    tactical_volume_contraction: float = 0.20
    pullback_entry: float = -0.10
    news_drop_proxy: float = -0.05
    news_rebound_exit: float = 0.03
    long_reentry_min_days: int = 8
    long_reentry_max_days: int = 10
    long_reentry_volume_fraction: float = 1 / 3
    lot_size: int = 100
    commission: float = 0.0005
    slippage: float = 0.001

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
