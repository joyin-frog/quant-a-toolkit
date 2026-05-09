from pathlib import Path

import pandas as pd
import streamlit as st

from quant_a.backtest import SUPPORTED_ENGINES
from quant_a.config import BACKTEST_ENGINE, INITIAL_CASH, MAX_HOLDINGS, MOMENTUM_WINDOW, SYMBOLS
from quant_a.main import run_pipeline


PERCENT_METRICS = {"total_return", "annualized_return", "max_drawdown", "volatility", "win_rate"}


def _format_metric(name: str, value: float) -> str:
    if name in PERCENT_METRICS:
        return f"{value:.2%}"
    return f"{value:.4f}"


def _summarize_refresh_warning(warning: str) -> str:
    if ": using cached data because refresh failed" not in warning:
        return warning
    symbol = warning.split(":", 1)[0]
    return f"{symbol} 在线行情刷新失败，已自动使用本地缓存继续回测。"


def _summarize_factor_warning(warning: str) -> str:
    if warning == "factor analysis skipped: trading-calendar frequency could not be inferred":
        return "因子分析已跳过：当前数据频率未被分析库稳定识别，但这不影响回测、图表和订单结果。"
    if warning.startswith("factor analysis skipped:"):
        return "因子分析已跳过：当前样本或数据条件不满足分析要求，但这不影响回测、图表和订单结果。"
    return warning


def _render_metrics(metrics: dict[str, float]) -> None:
    st.subheader("指标")
    metrics_frame = pd.DataFrame(
        {
            "metric": list(metrics.keys()),
            "value": [_format_metric(name, value) for name, value in metrics.items()],
        }
    )
    st.dataframe(metrics_frame, use_container_width=True, hide_index=True)


def _render_reports(report_paths: dict[str, Path]) -> None:
    st.subheader("图表")
    for name, path in report_paths.items():
        st.markdown(f"**{name}**")
        if path.exists():
            st.image(str(path), use_container_width=True)
        else:
            st.warning(f"Missing report image: {path}")


def _render_output_paths(order_path: Path, report_paths: dict[str, Path]) -> None:
    st.subheader("输出文件")
    st.code(str(order_path))
    for name, path in report_paths.items():
        st.write(f"{name}: {path}")


def main() -> None:
    st.set_page_config(page_title="quant-a 回测面板", layout="wide")
    st.title("quant-a 回测面板")
    st.caption("点按钮执行现有研究流水线，在线查看指标、图表和订单结果。")

    with st.sidebar:
        st.header("参数")
        engine = st.selectbox(
            "回测引擎",
            options=sorted(SUPPORTED_ENGINES),
            index=sorted(SUPPORTED_ENGINES).index(BACKTEST_ENGINE),
        )
        momentum_window = int(
            st.number_input(
                "动量窗口",
                min_value=1,
                max_value=250,
                value=MOMENTUM_WINDOW,
                step=1,
            )
        )
        max_holdings = int(
            st.number_input(
                "持仓数 Top N",
                min_value=1,
                max_value=len(SYMBOLS),
                value=MAX_HOLDINGS,
                step=1,
            )
        )
        initial_cash = float(
            st.number_input(
                "初始资金",
                min_value=1.0,
                value=float(INITIAL_CASH),
                step=10000.0,
            )
        )
        run_clicked = st.button("开始回测", use_container_width=True)

    if run_clicked:
        params = {
            "engine": engine,
            "momentum_window": momentum_window,
            "max_holdings": max_holdings,
            "initial_cash": initial_cash,
        }
        try:
            with st.spinner("正在运行回测..."):
                result = run_pipeline(**params)
            st.session_state["last_run"] = {"params": params, "result": result}
        except Exception as error:
            st.error(str(error))

    last_run = st.session_state.get("last_run")
    if not last_run:
        st.info("先在左侧设置参数，然后点击“开始回测”。")
        return

    params = last_run["params"]
    result = last_run["result"]
    warnings = [_summarize_refresh_warning(warning) for warning in result["warnings"]]
    factor_warnings = [_summarize_factor_warning(warning) for warning in result["factor_analysis"].get("warnings", [])]

    st.subheader("本次运行")
    st.json(params)

    if warnings:
        st.info("以下标的本次使用了本地缓存：")
        for warning in warnings:
            st.warning(warning)
    if factor_warnings:
        with st.expander("查看因子分析说明"):
            for warning in factor_warnings:
                st.info(warning)

    equity_curve = result["backtest"]["equity_curve"]
    latest_nav = float(equity_curve.iloc[-1]) if not equity_curve.empty else 0.0
    st.write(f"最新净值: {latest_nav:.4f}")
    st.write(f"按当前初始资金折算的最新组合价值: {latest_nav * params['initial_cash']:,.2f}")

    _render_metrics(result["metrics"])
    _render_reports(result["report_paths"])

    st.subheader("订单")
    st.dataframe(result["orders"], use_container_width=True, hide_index=True)

    _render_output_paths(result["order_path"], result["report_paths"])


if __name__ == "__main__":
    main()
