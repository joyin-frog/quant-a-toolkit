from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
ORDERS_DIR = BASE_DIR / "orders"
REPORTS_DIR = BASE_DIR / "reports"

STOCK_INDEX_SYMBOL = "000852"
STOCK_POOL_NAME = "中证1000成分股"

# 选股板块过滤：排除这些代码前缀（创业板 300/301、科创板 688/689、北交所/其他 8/4/9）。
# 只保留沪深主板（60/000/001/002/003）。
EXCLUDED_BOARD_PREFIXES = ("300", "301", "688", "689", "8", "4", "9")

START_DATE = "2018-01-01"
END_DATE = None
ADJUST = "qfq"

# BACKTEST_ENGINE = "vectorized"
BACKTEST_ENGINE = "backtrader"
INITIAL_CASH = 100_000.0

# 调这个值：更短更灵敏，更长更稳但更慢。
MOMENTUM_WINDOW = 20

# 调这个值：更短更容易进场，更长过滤更严格。
MA_WINDOW = 20

# 调这个值：用来过滤过新的股票，避免样本太早就进候选池。
MIN_LISTING_DAYS = 120

# 基础流动性过滤：窗口越大越稳，阈值越高越严格。
LIQUIDITY_WINDOW = 20
MIN_AVG_VOLUME = 500_000.0

# 跳空或涨跌停附近时，默认按 10% 粗粒度处理。
LIMIT_MOVE_THRESHOLD = 0.095

# 想更分散就调大，想更集中就调小。
TARGET_HOLDINGS = 8

# 控制组合上限；通常 >= TARGET_HOLDINGS。
MAX_HOLDINGS = 10

# 控制换手速度；越大越敏捷，越小越稳。
DAILY_MAX_SYMBOL_CHANGES = 2

# 组合总仓位上限；留出的部分默认是现金。
MAX_EXPOSURE = 0.85

# 手续费率（单边）
# 当前为：
# 0.0005 = 万5 = 0.05%
COMMISSION = 0.0005

# 滑点率
# 当前配置：
# 0.0010 = 0.1%
SLIPPAGE = 0.0010

# 一年交易日数量
TRADING_DAYS_PER_YEAR = 252


# ======================================================================
# 低波动多因子组合策略（月度调仓）——经回测对比后的主力策略
# 结论：低波动打底 + 动量微叠，风险调整后明显优于单一金叉/动量/纯基准。
# ======================================================================

# 持仓只数：25-30 是 20 万本金的甜区（更少会丢分散度、毁掉因子优势；更多则零碎、闲置现金高）。
# 应随本金缩放：本金越大可适当调大。
FACTOR_HOLDINGS = 30

# 卖出缓冲带（滞后/无交易区）：买入仍要进前 FACTOR_HOLDINGS 名，但已持有的票要等排名
# 掉到 FACTOR_SELL_RANK 名之外才卖。避免在第 30 名边界反复横跳、把刚要回血的票一次次扔掉。
# 实测把它从 30（无缓冲）放到 45：换手减半、近三年夏普 0.55→0.70。设为 FACTOR_HOLDINGS 即关闭缓冲。
FACTOR_SELL_RANK = 45

# 本金与最小交易单位（A 股 1 手 = 100 股，必须整手买卖）。
FACTOR_CAPITAL = 200_000.0
LOT_SIZE = 100

# 因子权重：5 因子（低波动/动量/价值/质量/股东人数）。
# 前 4 个摊开持有抗"单因子失效"；第 5 个"股东人数(筹码集中)"是 A 股散户市的真信号
# （户数减少=机构吸筹），实测小权重加入能把全程夏普 0.82→0.92、近三年基本不变（权重别大，等权会拖累近三年）。
# holders 只在有股东数据的票上生效（data/holders/），无数据则按中性分处理、自动退化。
FACTOR_WEIGHTS = {"lowvol": 0.21, "mom": 0.21, "value": 0.21, "quality": 0.21, "holders": 0.16}

# 因子计算参数。
FACTOR_VOL_WINDOW = 60          # 低波动：过去 60 个交易日收益率标准差
FACTOR_MOM_LOOKBACK = 126       # 动量：约 6 个月
FACTOR_MOM_SKIP = 21            # 动量跳过最近 1 个月（避开短期反转噪声）
# 价值=账面市值比(每股净资产/价)，质量=ROE，均来自 fundamentals.py（报告期+120天滞后防未来函数）。

# 现价上限（与选股要求一致：只买 500 元以下）。
FACTOR_MAX_PRICE = 500.0

# 调仓频率（pandas resample 频率别名；ME = 月末）。
FACTOR_REBALANCE = "ME"
# 每月在"该号数之后的第一个交易日"调仓（实测哪天调差别都是噪声，按用户习惯设月中 15 号）。
# 设为 None/0 则退回月末。
REBALANCE_DAY = 15

# ----- 核心-卫星组合（分散核心 + AI 产业链龙头卫星）-----
# 核心持仓只数 + 同一行业最多几只（避免"全是银行"扎堆）。
CS_CORE_HOLDINGS = 17
CORE_MAX_PER_SECTOR = 3
# AI 卫星总仓位：用户坚定看好 AI 产业链，但这是【信仰仓/主动赌注】（回测含幸存者偏差），控制比例。
AI_SATELLITE_WEIGHT = 0.15
