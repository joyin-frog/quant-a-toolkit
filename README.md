# quant-a — A 股个人量化工具箱

面向【20 万本金、只做主板】的个人 A 股量化研究 + 实操工具箱。从最初的 ETF / 沪深300
轮动脚手架，演化成一套可每月实操的系统：多因子选股组合（主力）、核心-卫星组合（含 AI
卫星）、网页操作台、SQLite 实盘记账与绩效复盘。

> 本文件是高层入口；模块边界、带代理绕过的完整抓数/回测命令、参数细节见 [CLAUDE.md](CLAUDE.md)。

## 选股范围

- 只选个股（不含 ETF），且**只做主板**：排除创业板（300/301）、科创板（688/689）、北交所（8/4/9）。
- 现价 < 500，流动性达标、非 ST / 停牌、上市满一定天数（`trade_rules.py`）。

## 安装

```bash
python3 -m venv .venv
.venv/bin/pip install -e .          # 运行依赖
.venv/bin/pip install -e ".[dev]"   # 加上测试依赖（pytest）
```

行情来自 AkShare / Eastmoney。若系统代理影响抓数，在命令前加 `NO_PROXY` / `no_proxy`
（例子见 CLAUDE.md）。

## 策略与入口

三套并行。**主力 = 第 1 套沪深300核心-卫星**（网页、实盘记账、复盘都用它）；第 2 套中证1000多因子是命令行研究 / 对照；第 3 套是旧轮动。

### 1) 主力（网页 / 实盘在用）：沪深300核心-卫星 + AI 卫星（月中调仓）

核心 ~85%（沪深300主板 **5 因子** + 行业上限，破解“全是银行”）+ AI 卫星 15%（8 条子链各选
一只**买得起的**动量龙头）。5 因子 = 低波动 / 动量 / 价值 / 质量 各 0.21 + **股东人数（筹码集中）0.16**；
20 万本金、100 股整手、买入前 30 名 / 跌出 45 名才卖的**缓冲带**。**网页「生成清单」调的就是它。**

```bash
PYTHONPATH=src .venv/bin/python -m quant_a.cs_pipeline
```

输出 `orders/cs_holdings.csv` + `reports/cs_equity.png`。

### 2) 研究 / 对照：中证1000主板多因子（命令行）

同样 5 因子，但选股池是**中证1000**全市场（`--mainboard` 可用全主板做去幸存者偏差对比）。项目早期的研究主力，现作对照。

```bash
PYTHONPATH=src .venv/bin/python fetch_universe.py                      # 首次抓数（断点续抓）
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline             # 回测 + 本月下单清单
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline --walkforward            # 逐年滚动验证
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline --mainboard --walkforward # 去幸存者偏差（全主板）
```

输出 `orders/factor_holdings.csv` + `reports/` 净值 / 回撤图。

### 3) 旧沪深300周频轮动（历史入口）

```bash
PYTHONPATH=src .venv/bin/python main.py
```

## 网页操作台（Next.js + shadcn/ui）

`web/` 是一个前端，**一个 `npm run dev` 就能跑**：前端 API 路由以子进程调项目 Python
（输出 JSON），无需另开后端服务。

```bash
cd web && npm install   # 首次
cd web && npm run dev    # → http://localhost:3000
```

- **月度调仓页**：填本金 / 持仓数 / AI 比例 →（刷新行情 → 生成清单）→ 指标卡 + 净值曲线 +
  本月下单清单（核心 / AI Badge）。
- **实盘记账页**（`/portfolio`）：记真实成交 / 入金 → 当前持仓盈亏 + 实盘 vs 回测 vs 基准 +
  跟踪误差 + 月度复盘（执行评分卡 / 归因 / 因子体检）。
- 配色 A 股**红涨绿跌**。git worktree 开发时 venv 在主检出，用
  `QUANT_PYTHON=/绝对路径/.venv/bin/python npm run dev` 覆盖。

## 实盘记账（CLI）

SQLite（`data/portfolio.db`）存**真实成交 + 资金流水**，持仓 / 净值 / 绩效全从成交推导。

```bash
PYTHONPATH=src .venv/bin/python -m quant_a.portfolio_web add-trade \
    --date 2026-06-15 --code 600000 --action buy --shares 100 --price 10.5 --sleeve core
PYTHONPATH=src .venv/bin/python -m quant_a.portfolio_web report     # 实盘绩效（JSON）
PYTHONPATH=src .venv/bin/python -m quant_a.portfolio_web holdings   # 当前持仓盈亏（JSON）
PYTHONPATH=src .venv/bin/python -m quant_a.portfolio_web review     # 月度复盘（执行评分卡 / 归因 / 因子体检）
PYTHONPATH=src .venv/bin/python -m quant_a.portfolio_web factor-health  # 因子滚动 IC（季度看）
```

只记真实成交（不是推荐清单），关键看**对回测的损耗（滑点 / 纪律）**和对基准的超额。

## 测试

```bash
.venv/bin/python -m pytest
```

覆盖绩效指标、因子选股（含缓冲带）、JSON NaN/Inf 清洗、实盘净值重建等**纯逻辑**单测
（离线、不依赖抓数）。

## 抓数脚本

| 脚本 | 作用 |
|------|------|
| `fetch_universe.py`     | 中证1000主板个股日线（约 649 只） |
| `fetch_mainboard.py`    | 全主板（~3200 只），用于去幸存者偏差 |
| `fetch_fundamentals.py` | ROE / 资产负债率 / 每股净资产（价值、质量因子） |
| `fetch_holders.py`      | 股东人数（第 5 因子） |

## 输出目录

- `data/` — 行情 / 财报 / 股东缓存 + `portfolio.db`
- `orders/` — 下单清单 CSV
- `reports/` — 净值 / 回撤 / 持仓图

## 重要提醒（实盘前必读）

- **幸存者偏差**：默认用【当前】成分股回溯，偏乐观；`--mainboard` 点对点选股可去偏。已退市
  个股免费数据补不全，绝对收益要打折——策略真正价值是“风险调整后更稳”，不是暴利。
- **防御型性格**：跌年 / 震荡年赢、投机疯牛年（小盘暴涨）跑输；求稳不求最猛。
- **AI 卫星是信仰仓 / 主动赌注**，非 alpha，比例 ≤15%、亏得起。
- **月中调仓节奏**：刷新行情 → 生成清单 → 券商 APP 手动下单 → 记真实成交；涨停买不进 / 跌停
  卖不出就跳过。

## 架构与完整命令

模块边界、参数（`config.py`）、行业中性化、增量刷新等细节见 [CLAUDE.md](CLAUDE.md)。
## 多策略统一入口（正式 3 条线）

正式策略只保留 3 条线，通过注册表统一运行，结果按策略隔离到 `reports/<strategy_id>/`：

| 策略 | id | 定位 | 全程回测（2018-2026，20万整手） |
|---|---|---|---|
| **低波长线（沪深300核心）** | `core_satellite` | 主力：5因子低波主导+缓冲带+行业上限（银行/证券/保险子行业归并后卡上限），月度调仓 | 年化 +14.9% / 回撤 -19.1% / 夏普 0.81（基准 0.46） |
| **AI+机器人主板龙头** | `ai_leader` | 信仰仓：AI算力 20 链 + 机器人链，每链 1 只买得起的动量龙头 | 年化 +34.7% / 回撤 -39.2% / 夏普 1.19（基准 1.12）⚠️ 幸存者偏差重，超额≈主题beta |
| **活跃龙头** | `active_leader` | 研究/对照：博主口诀形式化，**回测未验证盈利**（年化 -17.8%） | 仅作纪律参考，勿实盘 |

中证1000多因子退出注册表，研究线保留 CLI：`python -m quant_a.factor_pipeline [--mainboard --walkforward]`。

```bash
PYTHONPATH=src .venv/bin/python -m quant_a.runner --list          # 加 --json 输出参数/仓位分层元数据
PYTHONPATH=src .venv/bin/python -m quant_a.runner --strategy core_satellite --capital 200000 --holdings 17
PYTHONPATH=src .venv/bin/python -m quant_a.runner --strategy ai_leader --capital 200000
PYTHONPATH=src .venv/bin/python -m quant_a.runner --strategy active_leader --universe csi1000 --capital 200000
```

### 迁移调仓与锁仓（从现有持仓出发，不是从零开始）

`--account` 指定记账账户（如 `manual`=真实券商账户），清单从该账户**现有个股持仓**出发给出
卖出/保留/买入 过渡方案；`--locked` 锁仓的票策略**不卖**（哪怕它想卖），占持仓名额、计入行业上限：

```bash
# 手动账户 → 6只低波长线组合，但锁住中航沈飞不卖
PYTHONPATH=src .venv/bin/python -m quant_a.runner --strategy core_satellite --holdings 6 --account manual --locked 600760
```

- ETF/场内基金不参与迁移（自行管理），会在警告中披露；
- 保留的票不加不减（最小化换手），卖出全清，新买按等权预算整手；
- 网页主页选策略后可切"从账户迁移"+ 填锁仓代码，出同样的迁移清单卡片；
- 你不照做没关系：实际成交记进账户后，绩效报告的"对回测损耗"会如实反映差异——锁仓/抗命的代价用数据说话。

统一结果包含净值、基准、指标、交易记录、当前持仓、诊断信息和数据限制。每个策略在注册表里声明自己的参数和仓位分层，CLI 与网页表单都由该声明驱动。`ai_leader` 池子（`strategies/ai_leader/pool.py`）人工圈定、只保留主板（无创业板/科创板权限），含幸存者偏差，属信仰仓口径。
