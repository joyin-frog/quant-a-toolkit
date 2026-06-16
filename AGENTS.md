# AGENTS.md

A 股个人量化工具箱的 agent 指南。**完整命令、模块边界、关键约束以 [CLAUDE.md](CLAUDE.md) 为准**——
本文件是精简快速入口，改动时请与 CLAUDE.md 保持一致。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"     # 运行 + 测试依赖
.venv/bin/python -m pytest             # 单元测试（离线、纯逻辑，当前 13 个，全绿）
```

行情受系统代理影响时，命令前加（同名小写也加）：
`NO_PROXY=".eastmoney.com,push2his.eastmoney.com,.csindex.com.cn"`。

## 策略入口（详情见 CLAUDE.md）

```bash
PYTHONPATH=src .venv/bin/python -m quant_a.factor_pipeline [--mainboard] [--walkforward]  # 主力：中证1000主板5因子
PYTHONPATH=src .venv/bin/python -m quant_a.cs_pipeline      # 核心-卫星（沪深300核心 + AI卫星）
PYTHONPATH=src .venv/bin/python main.py                     # 旧沪深300周频轮动（入口）
```

- 抓数：`fetch_universe.py` / `fetch_mainboard.py` / `fetch_fundamentals.py` / `fetch_holders.py`。
- 网页：`cd web && npm run dev`（git worktree 里开发用 `QUANT_PYTHON=/绝对/.venv/bin/python npm run dev` 覆盖解释器）。
- 实盘记账：`python -m quant_a.portfolio_web {add-trade,add-cash,list,report,holdings,next-rebalance}`。

## 给 agent 的关键约束

- 选股只做**主板个股**（排除创业板/科创板/北交所），现价 < 500，过流动性 / ST / 停牌筛选。
- 调仓节奏 = 月中 15 号（`config.REBALANCE_DAY`）；多因子 = 低波 / 动量 / 价值 / 质量各 0.21 + 股东人数 0.16。
- 买入缓冲带：进前 30 名才买、掉出 45 名才卖（`config.FACTOR_SELL_RANK`）。
- 输出目录固定 `data/` / `orders/` / `reports/`（均被 `.gitignore`，不要提交）；新逻辑放对应模块，别堆进 `main.py`。
- 改完代码先跑 `.venv/bin/python -m pytest` 保绿；端到端用主流程烟测。
- JSON 输出要清洗 NaN/Inf（JS 的 `JSON.parse` 不认）；基准 `pct_change` 要把 inf 收益清零（脏价 0→正）。
- ⚠️ 回测含幸存者偏差（`--mainboard` 去偏）、AI 卫星是信仰仓——别把回测数当实盘承诺。

> 模块职责、参数细节、操作闭环、数据/抓数说明，全部见 [CLAUDE.md](CLAUDE.md)。
