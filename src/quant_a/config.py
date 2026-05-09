from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
ORDERS_DIR = BASE_DIR / "orders"
REPORTS_DIR = BASE_DIR / "reports"

UNIVERSE = {
    # 科创50ETF平安
    "589150": "etf",
    # 中韩半导体ETF华泰柏瑞
    "513310": "etf",
    # 人工智能ETF易方达
    "159819": "etf",
    # 科力远
    "600478": "stock",
    # 联创电子
    "002036": "stock",
    # 佰维存储
    "688525": "stock",
}
SYMBOLS = list(UNIVERSE.keys())
START_DATE = "2018-01-01"
END_DATE = None
ADJUST = "qfq"
# BACKTEST_ENGINE = "vectorized"
BACKTEST_ENGINE = "backtrader"
INITIAL_CASH = 1_000_000.0

MOMENTUM_WINDOW = 60
MA_WINDOW = 20
REBALANCE_WEEKDAY = 4
MAX_HOLDINGS = 2
POSITION_SIZE = 0.25
MAX_EXPOSURE = 0.50
COMMISSION = 0.0005
SLIPPAGE = 0.0010
TRADING_DAYS_PER_YEAR = 252
