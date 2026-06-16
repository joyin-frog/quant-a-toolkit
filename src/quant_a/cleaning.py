import pandas as pd

from quant_a.cache import load_cached_bars


PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]


# 把单标的缓存拼成宽表 close_matrix；这是策略层和回测层共享的核心输入契约。
def load_aligned_closes(symbols: list[str]) -> pd.DataFrame:
    return load_aligned_ohlcv(symbols)["close"]


def load_aligned_ohlcv(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, list[pd.DataFrame]] = {column: [] for column in PRICE_COLUMNS}
    for symbol in symbols:
        bars = load_cached_bars(symbol).copy()
        bars["date"] = pd.to_datetime(bars["date"])
        bars = bars.sort_values("date").drop_duplicates(subset="date", keep="last")
        for column in PRICE_COLUMNS:
            bars[column] = pd.to_numeric(bars[column], errors="coerce")
            series = bars.loc[:, ["date", column]].rename(columns={column: symbol}).set_index("date")
            frames[column].append(series)

    aligned = {}
    for column, parts in frames.items():
        if not parts:
            aligned[column] = pd.DataFrame()
            continue
        matrix = pd.concat(parts, axis=1).sort_index()
        matrix.index.name = "date"
        aligned[column] = matrix
    return aligned
