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

### 烟测
当前没有测试和 lint，默认用主流程烟测：
```bash
PYTHONPATH=src .venv/bin/python main.py
```

对比两套回测引擎：
```bash
PYTHONPATH=src .venv/bin/python -c "from quant_a.main import run_pipeline; print(run_pipeline(engine='vectorized')['metrics']); print(run_pipeline(engine='backtrader')['metrics'])"
```

## 架构

这是一个最小化的 A 股 / ETF 轮动研究脚手架，核心逻辑都在 `src/quant_a`，根目录 `main.py` 只是入口。

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
- `strategy.py`：策略打分和目标权重
- `factor_analysis.py`：Alphalens 因子分析
- `backtest.py`：回测执行，支持 `vectorized` 和 `backtrader`
- `metrics.py`：绩效指标
- `orders.py`：交易清单
- `plotting.py`：净值、回撤、持仓图

## 关键约束

- 默认回测引擎来自 `config.py` 的 `BACKTEST_ENGINE`，也可用 `run_pipeline(engine=...)` 临时覆盖
- live 抓数失败但本地有缓存时，会继续使用缓存；只有“无缓存且抓数失败”才报错
- 当前因子分析基于策略真实使用的打分：`momentum.where(eligible)`
- 输出目录固定为：`data/`、`orders/`、`reports/`
- 当前不是通用框架，只有一套周频轮动策略；不要把逻辑继续堆到根目录 `main.py`

## 当前限制

- 暂无自动化测试
- 暂无 lint / format 配置
- 行情抓取依赖 AkShare / Eastmoney 可用性
- 两套回测引擎执行细节不同，指标有差异是正常的
- 股票池较小时，Alphalens 可能只返回 warning，分析价值有限
