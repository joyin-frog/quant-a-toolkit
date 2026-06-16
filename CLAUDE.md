# CLAUDE.md

本文件用于说明这个仓库的常用命令、主流程和关键约束。

## 常用命令

### 初始化
```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

### 运行
```bash
PYTHONPATH=src .venv/bin/python main.py
```

如果 AkShare / Eastmoney 受系统代理影响，改用：
```bash
NO_PROXY=".eastmoney.com,push2his.eastmoney.com" no_proxy=".eastmoney.com,push2his.eastmoney.com" PYTHONPATH=src .venv/bin/python main.py
```

### 依赖变更后重装
```bash
.venv/bin/pip install -e .
```

### 测试
单元测试用 pytest（离线、纯逻辑：绩效指标 / 因子选股含缓冲带 / JSON 的 NaN-Inf 清洗 / 实盘净值重建）：
```bash
.venv/bin/pip install -e ".[dev]"   # 首次装测试依赖（pytest）
.venv/bin/python -m pytest           # 跑全部（当前 13 个，全绿）
```
端到端 / 抓数路径没有单测，仍用主流程烟测（需要数据 / 网络）：
```bash
PYTHONPATH=src .venv/bin/python main.py
```

对比两套回测引擎：
```bash
PYTHONPATH=src .venv/bin/python -c "from quant_a.main import run_pipeline; print(run_pipeline(engine='vectorized')['metrics']); print(run_pipeline(engine='backtrader')['metrics'])"
```

### 主力策略：多因子组合（中证1000主板，月度调仓）
**5 因子**（低波动/动量/价值/质量各 0.21 + 股东人数 0.16，见 `config.FACTOR_WEIGHTS`）。
前 4 个摊开抗"单因子失效"；第 5 个【股东人数/筹码集中】是 A 股散户市真信号（户数减少=机构吸筹），
实测小权重加入能提升全程夏普、近三年不降（`fundamentals.load_holder_factor`，按公告日对齐，`fetch_holders.py` 抓数）。
调仓默认**月中 15 号**（`config.REBALANCE_DAY`，实测哪天调差别是噪声）。流水线会自动输出**滚动12月收益**分布。
`factor_scores_on(sector_map=)` 支持**行业中性化**（行业内排名，需 `data/industry_map.csv`，东财行业接口不稳时缺失）。先抓数再跑：
```bash
# 1) 抓中证1000主板个股日线（约649只，首次约10-20分钟，断点续抓）
NO_PROXY=".eastmoney.com,push2his.eastmoney.com,.csindex.com.cn" no_proxy=".eastmoney.com,push2his.eastmoney.com,.csindex.com.cn" PYTHONPATH=src .venv/bin/python fetch_universe.py

# 2) 跑回测 + 输出"本月该买哪30只"的下单清单（20万本金、100股整手）
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline

# 滚动验证（逐年是否稳定赢基准）：
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline --walkforward

# 去幸存者偏差版（用全主板 ~3200 只点对点选股，需先抓全主板）：
PYTHONPATH=src .venv/bin/python fetch_mainboard.py            # 大抓数，约 40-50 分钟，断点续抓
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline --mainboard --walkforward
```
本金/持仓数可调：`run_factor_pipeline(capital=200_000, holdings=30, universe="mainboard", walkforward=True)`（20万的甜区是 25-30 只）。
下单清单存到 `orders/factor_holdings.csv`，净值/回撤图存到 `reports/`。

**卖出缓冲带**（`config.FACTOR_SELL_RANK=45`）：买入要进前 30 名，但已持有的票要掉到 45 名外才卖
（滞后/无交易区），避免在边界反复换手、卖飞刚要回血的票。实测换手减半、近三年夏普 0.54→0.75。
实操含义：每月别因为某只持仓掉到 31-45 名就卖，掉出 45 名才换掉。

> 幸存者偏差：默认中证1000池用的是【当前】成分股回溯，偏乐观；`--mainboard` 用全主板个股 +
> trade_rules 点对点流动性筛选，消除了"指数成分股选择"这层偏差（残留：已退市个股不在内）。

### 核心-卫星组合（沪深300分散核心 + AI产业链龙头卫星）
大盘股版本 + 用户的 AI 信仰仓。核心=沪深300主板4因子（含缓冲带 + 行业上限，避免"全是银行"扎堆）；
卫星≈15%=AI产业链（光通信/半导体/消费电子/算力/PCB/铜箔/电子布/电力）每条子链选 1 只【买得起的】动量龙头。
```bash
PYTHONPATH=src .venv/bin/python -m quant_a.cs_pipeline   # 输出 orders/cs_holdings.csv + reports/cs_equity.png
```
- 模块：`portfolio.py`（AI龙头池 + 行业上限 + 核心/卫星选股 + 整手回测 + 下单清单）、`cs_pipeline.py`（总控）。
- 参数：`config.CS_CORE_HOLDINGS=17`、`CORE_MAX_PER_SECTOR=3`、`AI_SATELLITE_WEIGHT=0.15`。
- 数据：`data/hs300_mainboard.csv`（沪深300主板清单）；行业分类 `data/industry_map.csv` 可选（缺失时只卡金融三类）。
- ⚠️ AI卫星是【信仰仓/主动赌注】：AI龙头池按当下认知选、回测含幸存者偏差，实盘会打折；20万下贵龙头（北方华创/韦尔）买不起，故只选买得起的。
- ⚠️ 每月跑前最好先刷新全部成分股数据到同一天，否则结尾日期参差会让清单的AI覆盖不全。

### 网页前端（shadcn / Next.js）
`web/` 是一个 Next.js + shadcn/ui 前端：填本金/持仓数/AI比例 → 一键生成本月调仓清单 + 指标卡片 + 净值图。
```bash
cd web && npm install   # 首次
cd web && npm run dev    # → http://localhost:3000
```
- 原理：前端 `app/api/run/route.ts`（Node API 路由）以子进程调 `quant_a.cs_web`（输出 JSON），无需另开后端服务，一个 `npm run dev` 即可。
- Python 解释器默认用 `项目根/.venv`（主检出即对）；在 git worktree 里开发时 venv 在主检出，需 `QUANT_PYTHON=/绝对/路径/.venv/bin/python npm run dev` 覆盖。
- `cs_web.py` 是网页用的 JSON 入口（`run_cs_pipeline` 的薄封装）。

#### 实盘记账与绩效
网页 `/portfolio` 页（顶部链接进入）：记【真实成交】+ 入金 → 自动重建实盘净值 → 对比回测/基准 + 跟踪误差。
- 存储：`portfolio_db.py`（SQLite `data/portfolio.db`，`trades` + `cash_flows` 两表；持仓/净值全从成交推导）。
- 报告：`portfolio_web.py`（CLI 子命令 `add-trade`/`add-cash`/`list`/`report`，输出 JSON）；`report` 会跑一次策略回测对齐到实盘窗口算跟踪误差/损耗。
- 网页 API：`/api/trades`（GET列/POST增）、`/api/portfolio`（GET绩效）；前端 `app/portfolio/page.tsx`。
- 关键指标：实盘总收益、对基准超额、**对回测损耗（执行滑点/纪律）**、跟踪误差——实盘最该盯后两个。
- ⚠️ 只记真实成交（不是推荐清单）；跑前数据要刷新到成交覆盖的日期。

> 另有并行的研究/对照入口：`quant_a.factor_pipeline`（中证1000主板4因子，主力）、`quant_a.main`（旧沪深300周频轮动）。

## 架构

核心逻辑都在 `src/quant_a`。最初是最小化的沪深300 / ETF 轮动脚手架（`main.py` 入口），现已长出多套并行策略
（主力多因子 `factor_pipeline`、核心卫星 `cs_pipeline`）+ 网页前端（`web/`）+ SQLite
实盘记账（`portfolio_db` / `portfolio_web`）。下面的“主流程”特指旧的 `main.py` 轮动入口：

主流程在 `src/quant_a/main.py`：
1. 刷新行情缓存
2. 对齐收盘价矩阵
3. 跑因子分析
4. 生成目标权重
5. 执行回测
6. 计算指标
7. 输出订单和图表

## 模块边界

- `config.py`：统一配置，含股票池、回测引擎、参数和输出目录
- `data_fetch.py`：AkShare 抓数，含代理绕过和重试
- `cache.py` / `cleaning.py`：本地 CSV 缓存与价格对齐
- `strategy.py`：旧策略打分和目标权重（沪深300周频轮动）
- `factor_analysis.py`：Alphalens 因子分析
- `backtest.py`：回测执行，支持 `vectorized` 和 `backtrader`
- `metrics.py`：绩效指标
- `orders.py`：交易清单
- `plotting.py`：净值、回撤、持仓图
- **主力策略（低波动多因子）**：
  - `universe.py`：中证1000成分股 + 排除创业板/科创板/北交所
  - `factor_strategy.py`：低波动+动量打分与选股（纯函数）
  - `factor_backtest.py`：固定本金 + 100股整手的真实回测 + 下单清单生成
  - `factor_pipeline.py`：主力策略总控入口（回测/指标/基准对比/下单清单/报告图）
  - `trade_rules.py`：合格股票过滤（流动性/ST/停牌/上市天数）
- **核心-卫星 + 网页 + 实盘记账**：
  - `portfolio.py`：AI 龙头池 + 行业上限 + 核心/卫星选股 + 整手回测
  - `cs_pipeline.py` / `cs_web.py`：核心卫星总控 / 网页用 JSON 入口
  - `fundamentals.py`：价值/质量/股东人数因子（按报告期 + 滞后对齐）
  - `walkforward.py`：逐年 / 滚动验证；`refresh_cs.py`：增量刷新行情缓存
  - `portfolio_db.py` / `portfolio_web.py`：SQLite 实盘记账 / 绩效 CLI（add-trade / report / holdings…）
- 测试：`tests/`（pytest，纯逻辑离线单测）

## 关键约束

- 默认回测引擎来自 `config.py` 的 `BACKTEST_ENGINE`，也可用 `run_pipeline(engine=...)` 临时覆盖
- live 抓数失败但本地有缓存时，会继续使用缓存；只有“无缓存且抓数失败”才报错
- 当前因子分析基于策略真实使用的打分：`momentum.where(eligible)`
- 输出目录固定为：`data/`、`orders/`、`reports/`
- 现在有多套并行策略（主力 `factor_pipeline`、核心卫星 `cs_pipeline`、旧轮动 `main.py`）；新逻辑放到对应模块，别再堆进根目录 `main.py`

## 当前限制

- 已有 pytest 单元测试（`tests/`，纯逻辑 / 离线），但覆盖仍局部；抓数 / 回测端到端仍靠主流程烟测
- 暂无 lint / format / CI 配置
- 行情抓取依赖 AkShare / Eastmoney 可用性
- 两套回测引擎执行细节不同，指标有差异是正常的
- 股票池较小时，Alphalens 可能只返回 warning，分析价值有限
