import pandas as pd

from quant_a.cache import load_cached_bars


PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]


# 把单标的缓存拼成宽表 close_matrix；这是策略层和回测层共享的核心输入契约。
def load_aligned_closes(symbols: list[str]) -> pd.DataFrame:
    frames = []
    for symbol in symbols:
        bars = load_cached_bars(symbol).copy()
        bars["date"] = pd.to_datetime(bars["date"])
        bars = bars.sort_values("date").drop_duplicates(subset="date", keep="last")
        for column in PRICE_COLUMNS:
            bars[column] = pd.to_numeric(bars[column], errors="coerce")
        closes = bars.loc[:, ["date", "close"]].rename(columns={"close": symbol}).set_index("date")
        frames.append(closes)
    close_matrix = pd.concat(frames, axis=1).sort_index()
    close_matrix.index.name = "date"
    return close_matrix
