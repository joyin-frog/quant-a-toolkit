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

四套并行，主力是第 1 套。

### 1) 主力：中证1000主板多因子（月中调仓）

5 因子：低波动 / 动量 / 价值 / 质量 各 0.21 + **股东人数（筹码集中）0.16**；20 万本金、
100 股整手、买入前 30 名 / 跌出 45 名才卖的**缓冲带**。

```bash
PYTHONPATH=src .venv/bin/python fetch_universe.py                      # 首次抓数（断点续抓）
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline             # 回测 + 本月下单清单
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline --walkforward            # 逐年滚动验证
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline --mainboard --walkforward # 去幸存者偏差（全主板）
```

输出 `orders/factor_holdings.csv` + `reports/` 净值 / 回撤图。

### 2) 核心-卫星：沪深300核心 + AI 产业链卫星

核心 ~85%（沪深300主板 5 因子 + 行业上限，破解“全是银行”）+ AI 卫星 15%（8 条子链各选
一只**买得起的**动量龙头）。

```bash
PYTHONPATH=src .venv/bin/python -m quant_a.cs_pipeline
```

输出 `orders/cs_holdings.csv` + `reports/cs_equity.png`。

### 3) 金叉择时（对照，非主力）

5/20 日均线金叉事件驱动；真实成交下无优势，仅作对照。

```bash
PYTHONPATH=src .venv/bin/python -m quant_a.gc_pipeline
```

### 4) 旧沪深300周频轮动（历史入口）

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
  跟踪误差。
- 配色 A 股**红涨绿跌**。git worktree 开发时 venv 在主检出，用
  `QUANT_PYTHON=/绝对路径/.venv/bin/python npm run dev` 覆盖。

## 实盘记账（CLI）

SQLite（`data/portfolio.db`）存**真实成交 + 资金流水**，持仓 / 净值 / 绩效全从成交推导。

```bash
PYTHONPATH=src .venv/bin/python -m quant_a.portfolio_web add-trade \
    --date 2026-06-15 --code 600000 --action buy --shares 100 --price 10.5 --sleeve core
PYTHONPATH=src .venv/bin/python -m quant_a.portfolio_web report     # 实盘绩效（JSON）
PYTHONPATH=src .venv/bin/python -m quant_a.portfolio_web holdings   # 当前持仓盈亏（JSON）
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
