import pandas as pd

from quant_a.config import DAILY_MAX_SYMBOL_CHANGES, MA_WINDOW, MAX_EXPOSURE, MAX_HOLDINGS, MOMENTUM_WINDOW, TARGET_HOLDINGS


def compute_strategy_signals(close_matrix: pd.DataFrame, momentum_window: int | None = None) -> dict[str, pd.DataFrame]:
    selected_momentum_window = momentum_window or MOMENTUM_WINDOW
    momentum = close_matrix / close_matrix.shift(selected_momentum_window) - 1
    moving_average = close_matrix.rolling(MA_WINDOW).mean()
    long_moving_average = close_matrix.rolling(MA_WINDOW * 3).mean()
    eligible = close_matrix.gt(moving_average) & moving_average.gt(long_moving_average)
    factor_score = momentum.where(eligible)
    return {
        "momentum": momentum,
        "moving_average": moving_average,
        "long_moving_average": long_moving_average,
        "eligible": eligible,
        "factor_score": factor_score,
    }


def build_target_weights(
    close_matrix: pd.DataFrame,
    momentum_window: int | None = None,
    target_holdings: int | None = None,
    max_holdings: int | None = None,
    max_symbol_changes: int | None = None,
    candidate_mask: pd.DataFrame | None = None,
) -> pd.DataFrame:
    selected_target_holdings = min(target_holdings or TARGET_HOLDINGS, len(close_matrix.columns))
    selected_max_holdings = min(max_holdings or MAX_HOLDINGS, len(close_matrix.columns))
    selected_max_symbol_changes = max_symbol_changes or DAILY_MAX_SYMBOL_CHANGES
    if selected_target_holdings < 1:
        raise ValueError("target_holdings must be at least 1")
    if selected_max_holdings < selected_target_holdings:
        raise ValueError("max_holdings must be greater than or equal to target_holdings")
    if selected_max_symbol_changes < 1:
        raise ValueError("max_symbol_changes must be at least 1")

    signals = compute_strategy_signals(close_matrix, momentum_window=momentum_window)
    factor_score = signals["factor_score"]
    if candidate_mask is not None:
        candidate_mask = candidate_mask.reindex(index=close_matrix.index, columns=close_matrix.columns).fillna(False)
        factor_score = factor_score.where(candidate_mask)

    targets = pd.DataFrame(0.0, index=close_matrix.index, columns=close_matrix.columns)
    current = pd.Series(0.0, index=close_matrix.columns)

    for current_date in close_matrix.index:
        ranked = factor_score.loc[current_date].dropna()
        ranked = ranked[ranked > 0].sort_values(ascending=False)

        desired = ranked.head(selected_target_holdings).index.tolist()
        desired_total_count = min(selected_max_holdings, len(desired))

        current_selected = [symbol for symbol in current.index if current[symbol] > 1e-8]
        selected = current_selected[:]

        stale = [symbol for symbol in current_selected if symbol not in desired]
        missing = [symbol for symbol in desired if symbol not in current_selected]

        replacement_limit = min(len(stale), len(missing), selected_max_symbol_changes // 2)
        for idx in range(replacement_limit):
            stale_symbol = stale[idx]
            missing_symbol = missing[idx]
            selected.remove(stale_symbol)
            selected.append(missing_symbol)

        changes_used = replacement_limit * 2
        slots_to_fill = max(0, desired_total_count - len(selected))
        add_limit = min(slots_to_fill, len(missing) - replacement_limit, selected_max_symbol_changes - changes_used)
        for symbol in missing[replacement_limit : replacement_limit + add_limit]:
            selected.append(symbol)

        if len(selected) > selected_max_holdings:
            selected_scores = ranked.reindex(selected).fillna(float("-inf"))
            selected = selected_scores.sort_values(ascending=False).head(selected_max_holdings).index.tolist()

        next_weights = pd.Series(0.0, index=close_matrix.columns)
        selected_scores = ranked.reindex(selected).dropna()
        selected_scores = selected_scores[selected_scores > 0]
        if not selected_scores.empty:
            next_weights.loc[selected_scores.index] = selected_scores / selected_scores.sum() * MAX_EXPOSURE

        current = next_weights
        targets.loc[current_date] = current

    return targets
