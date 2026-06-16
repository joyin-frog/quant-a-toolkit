import pandas as pd

from quant_a.strategy import compute_strategy_signals


FORWARD_PERIODS = (1, 5, 10, 20)
DEFAULT_QUANTILES = 5


FREQUENCY_WARNING_FRAGMENT = "does not conform to passed frequency C"


def _empty_analysis(warnings: list[str] | None = None) -> dict[str, object]:
    return {
        "factor_data": pd.DataFrame(),
        "ic": pd.DataFrame(),
        "mean_quantile_returns": pd.DataFrame(),
        "factor_decay": pd.DataFrame(),
        "warnings": warnings or [],
    }


def _format_analysis_error(error: Exception) -> str:
    message = str(error)
    if FREQUENCY_WARNING_FRAGMENT in message:
        return "factor analysis skipped: trading-calendar frequency could not be inferred"
    return f"factor analysis skipped: {message}"


# 研究层只关心“因子值 + 未来收益”的整理，不参与回测执行或仓位计算。
def run_factor_analysis(
    close_matrix: pd.DataFrame,
    momentum_window: int | None = None,
    candidate_mask: pd.DataFrame | None = None,
) -> dict[str, object]:
    try:
        import alphalens.performance as al_performance
        import alphalens.utils as al_utils
    except Exception as error:
        return _empty_analysis([f"factor analysis unavailable: {error}"])

    factor_score = compute_strategy_signals(close_matrix, momentum_window=momentum_window)["factor_score"]
    if candidate_mask is not None:
        candidate_mask = candidate_mask.reindex(index=close_matrix.index, columns=close_matrix.columns).fillna(False)
        factor_score = factor_score.where(candidate_mask)
    factor_frame = factor_score
    factor_series = factor_frame.stack().rename("factor")
    if factor_series.empty:
        return _empty_analysis(["factor analysis skipped: no non-null factor scores on available dates"])

    counts = factor_series.groupby(level=0).size()
    valid_dates = counts[counts >= 2].index
    if valid_dates.empty:
        return _empty_analysis(["factor analysis skipped: need at least 2 ranked assets on rebalance dates"])

    factor_series = factor_series.loc[factor_series.index.get_level_values(0).isin(valid_dates)]
    quantiles = min(DEFAULT_QUANTILES, int(counts.loc[valid_dates].min()))
    if quantiles < 2:
        return _empty_analysis(["factor analysis skipped: insufficient assets for quantile analysis"])

    try:
        factor_data = al_utils.get_clean_factor_and_forward_returns(
            factor=factor_series,
            prices=close_matrix,
            quantiles=quantiles,
            periods=FORWARD_PERIODS,
            max_loss=1.0,
        )
    except Exception as error:
        return _empty_analysis([_format_analysis_error(error)])

    ic = al_performance.factor_information_coefficient(factor_data)
    mean_quantile_returns, _ = al_performance.mean_return_by_quantile(factor_data)
    factor_decay = pd.DataFrame(
        {
            f"period_{period}": al_performance.factor_rank_autocorrelation(factor_data, period=period)
            for period in FORWARD_PERIODS
        }
    )

    warnings = []
    skipped_dates = len(counts) - len(valid_dates)
    if skipped_dates > 0:
        warnings.append(f"factor analysis skipped {skipped_dates} date(s) with fewer than 2 assets")

    return {
        "factor_data": factor_data,
        "ic": ic,
        "mean_quantile_returns": mean_quantile_returns,
        "factor_decay": factor_decay,
        "warnings": warnings,
    }
