# quant-a

一个最小化的 A 股 / ETF 轮动研究脚手架，当前包含：AkShare 抓数、双回测引擎、绩效指标、因子分析、订单输出和图表报告。

## 安装

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## 运行

```bash
PYTHONPATH=src .venv/bin/python main.py
```

如果系统代理影响 Eastmoney：

```bash
NO_PROXY=".eastmoney.com,push2his.eastmoney.com" no_proxy=".eastmoney.com,push2his.eastmoney.com" PYTHONPATH=src .venv/bin/python main.py
```

## 回测引擎

默认引擎由 `src/quant_a/config.py` 的 `BACKTEST_ENGINE` 控制，可选：

- `vectorized`
- `backtrader`

也可以在代码里指定：

```python
from quant_a.main import run_pipeline

result = run_pipeline(engine="backtrader")
print(result["engine"])
print(result["metrics"])
```

## 输出

- `data/`：行情缓存
- `orders/latest_orders.csv`：最新交易清单
- `reports/`：净值、回撤、持仓图

## Web 页面

安装完依赖后可启动最小 Streamlit 面板：

```bash
PYTHONPATH=src .venv/bin/streamlit run streamlit_app.py
```

页面支持切换回测引擎，并调整动量窗口、持仓数和初始资金；现有 CLI 用法保持不变。

## 因子分析

`run_pipeline()` 会返回 `factor_analysis`。当股票池太小或分层不足时，Alphalens 会跳过分析，并把原因写进 `factor_analysis["warnings"]`。
