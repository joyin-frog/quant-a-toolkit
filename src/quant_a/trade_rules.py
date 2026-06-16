from __future__ import annotations

import pandas as pd

from quant_a.config import LIMIT_MOVE_THRESHOLD, LIQUIDITY_WINDOW, MIN_AVG_VOLUME, MIN_LISTING_DAYS


def _normalize_metadata(stock_metadata: pd.DataFrame) -> pd.DataFrame:
    metadata = stock_metadata.copy()
    if metadata.empty or "symbol" not in metadata.columns:
        return pd.DataFrame(columns=["name", "listing_date", "is_st"], index=pd.Index([], name="symbol"))
    metadata["symbol"] = metadata["symbol"].astype(str).str.zfill(6)
    if "name" not in metadata.columns:
        metadata["name"] = ""
    metadata["name"] = metadata["name"].astype(str)
    metadata["listing_date"] = pd.to_datetime(metadata.get("listing_date"), errors="coerce")
    if "is_st" not in metadata.columns:
        metadata["is_st"] = False
    metadata["is_st"] = metadata["is_st"].fillna(False).astype(bool)
    return metadata.drop_duplicates(subset="symbol", keep="last").set_index("symbol")


def _broadcast_symbol_series(series: pd.Series, index: pd.DatetimeIndex, columns: pd.Index) -> pd.DataFrame:
    frame = pd.DataFrame(index=index, columns=columns)
    for symbol in columns:
        frame[symbol] = series.get(symbol, False)
    return frame.fillna(False).astype(bool)


def build_trade_eligibility(
    close_matrix: pd.DataFrame,
    high_matrix: pd.DataFrame,
    low_matrix: pd.DataFrame,
    volume_matrix: pd.DataFrame,
    stock_metadata: pd.DataFrame,
    min_listing_days: int | None = None,
    liquidity_window: int | None = None,
    min_avg_volume: float | None = None,
    limit_move_threshold: float | None = None,
) -> dict[str, pd.DataFrame]:
    selected_min_listing_days = min_listing_days or MIN_LISTING_DAYS
    selected_liquidity_window = liquidity_window or LIQUIDITY_WINDOW
    selected_min_avg_volume = min_avg_volume if min_avg_volume is not None else MIN_AVG_VOLUME
    selected_limit_move_threshold = limit_move_threshold or LIMIT_MOVE_THRESHOLD

    close_matrix = close_matrix.copy()
    high_matrix = high_matrix.reindex(index=close_matrix.index, columns=close_matrix.columns)
    low_matrix = low_matrix.reindex(index=close_matrix.index, columns=close_matrix.columns)
    volume_matrix = volume_matrix.reindex(index=close_matrix.index, columns=close_matrix.columns).fillna(0.0)

    metadata = _normalize_metadata(stock_metadata)
    if metadata.empty:
        metadata = pd.DataFrame(index=close_matrix.columns, data={"name": "", "listing_date": pd.NaT, "is_st": False})
    metadata = metadata.reindex(close_matrix.columns)
    default_listing_date = close_matrix.index.min() - pd.Timedelta(days=selected_min_listing_days + 1)
    metadata["listing_date"] = metadata["listing_date"].fillna(default_listing_date)
    metadata["is_st"] = metadata["is_st"].fillna(False).astype(bool)
    st_symbols = metadata["is_st"] if "is_st" in metadata.columns else pd.Series(dtype=bool)
    st_mask = _broadcast_symbol_series(st_symbols, close_matrix.index, close_matrix.columns)

    listing_dates = metadata.get("listing_date", pd.Series(dtype="datetime64[ns]"))
    listing_mask = pd.DataFrame(False, index=close_matrix.index, columns=close_matrix.columns)
    for symbol in close_matrix.columns:
        listing_date = listing_dates.get(symbol, pd.NaT)
        if pd.isna(listing_date):
            continue
        listing_mask[symbol] = close_matrix.index >= (pd.Timestamp(listing_date) + pd.Timedelta(days=selected_min_listing_days))

    liquidity_mask = (
        volume_matrix.rolling(selected_liquidity_window, min_periods=selected_liquidity_window).mean()
        >= selected_min_avg_volume
    )
    liquidity_mask = liquidity_mask.fillna(False)

    halted_mask = volume_matrix.le(0.0) | close_matrix.isna() | high_matrix.isna() | low_matrix.isna()
    candidate_mask = (~st_mask) & listing_mask & liquidity_mask & (~halted_mask)

    prev_close = close_matrix.shift(1)
    daily_return = close_matrix / prev_close - 1.0
    limit_up_mask = daily_return >= selected_limit_move_threshold
    limit_down_mask = daily_return <= -selected_limit_move_threshold

    can_buy = (~halted_mask) & (~limit_up_mask)
    can_sell = (~halted_mask) & (~limit_down_mask)

    return {
        "candidate_mask": candidate_mask.fillna(False),
        "can_buy": can_buy.fillna(False),
        "can_sell": can_sell.fillna(False),
        "halted": halted_mask.fillna(False),
        "limit_up": limit_up_mask.fillna(False),
        "limit_down": limit_down_mask.fillna(False),
        "st": st_mask.fillna(False),
        "liquidity": liquidity_mask.fillna(False),
        "listing": listing_mask.fillna(False),
    }
