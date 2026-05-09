from pathlib import Path

import pandas as pd

from quant_a.config import ORDERS_DIR


# 订单表只是“当前持仓 vs 最新目标权重”的差异视图，方便手工下单或接后续执行系统。
def generate_order_table(target_weights: pd.DataFrame, current_holdings: dict[str, float] | None = None) -> pd.DataFrame:
    latest_date = target_weights.index[-1]
    latest_target = target_weights.iloc[-1]
    current_holdings = current_holdings or {}

    symbols = sorted(set(target_weights.columns) | set(current_holdings))
    rows = []
    for symbol in symbols:
        current_weight = float(current_holdings.get(symbol, 0.0))
        target_weight = float(latest_target.get(symbol, 0.0))
        delta = target_weight - current_weight
        if delta > 0:
            action = "buy"
        elif delta < 0:
            action = "sell"
        elif target_weight > 0:
            action = "hold"
        else:
            action = "none"
        rows.append(
            {
                "date": latest_date,
                "symbol": symbol,
                "action": action,
                "current_weight": current_weight,
                "target_weight": target_weight,
                "delta_weight": delta,
            }
        )
    return pd.DataFrame(rows)


# 输出层默认覆盖 latest_orders.csv，便于外部脚本总是读取最新一次调仓建议。
def save_order_table(order_table: pd.DataFrame, file_name: str = "latest_orders.csv") -> Path:
    ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = ORDERS_DIR / file_name
    order_table.to_csv(output_path, index=False)
    return output_path
