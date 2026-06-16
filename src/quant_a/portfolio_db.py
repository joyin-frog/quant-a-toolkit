"""实盘记账：SQLite 存【真实成交流水】+【资金流水】，并从成交重建实盘净值。

只记真实成交（不是推荐清单）——实盘会跳过涨停、成交价/手数有差，记真实的复盘才准、还能看纪律。
持仓/净值/绩效全部从成交流水推导，不单独维护。
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from quant_a.cache import cache_exists, load_cached_bars
from quant_a.config import DATA_DIR

DB_PATH = DATA_DIR / "portfolio.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, code TEXT NOT NULL, name TEXT,
            action TEXT NOT NULL, shares INTEGER NOT NULL, price REAL NOT NULL,
            fee REAL DEFAULT 0, sleeve TEXT, note TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS cash_flows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, amount REAL NOT NULL, type TEXT, note TEXT)"""
    )
    return conn


def add_trade(date, code, name, action, shares, price, fee=0.0, sleeve="", note="") -> int:
    if action not in ("buy", "sell"):
        raise ValueError("action 必须是 buy 或 sell")
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO trades(date,code,name,action,shares,price,fee,sleeve,note) VALUES(?,?,?,?,?,?,?,?,?)",
            (str(date), str(code).zfill(6), name, action, int(shares), float(price), float(fee), sleeve, note),
        )
        return int(cur.lastrowid)


def add_cash_flow(date, amount, flow_type="deposit", note="") -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO cash_flows(date,amount,type,note) VALUES(?,?,?,?)",
            (str(date), float(amount), flow_type, note),
        )
        return int(cur.lastrowid)


def get_trades() -> pd.DataFrame:
    with _conn() as conn:
        df = pd.read_sql_query("SELECT * FROM trades ORDER BY date, id", conn)
    if not df.empty:
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["date"] = pd.to_datetime(df["date"])
    return df


def get_cash_flows() -> pd.DataFrame:
    with _conn() as conn:
        df = pd.read_sql_query("SELECT * FROM cash_flows ORDER BY date, id", conn)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def current_positions() -> pd.DataFrame:
    """当前持仓：每个代码的净股数 + 买入均价（成本）。已清仓的不返回。"""
    trades = get_trades()
    if trades.empty:
        return pd.DataFrame(columns=["code", "name", "shares", "avg_cost", "sleeve"])
    rows: list[dict[str, object]] = []
    for code, group in trades.groupby("code"):
        buys = group[group["action"] == "buy"]
        sells = group[group["action"] == "sell"]
        net = int(buys["shares"].sum() - sells["shares"].sum())
        if net <= 0:
            continue
        buy_shares = int(buys["shares"].sum())
        buy_cost = float((buys["shares"] * buys["price"] + buys["fee"]).sum())
        avg_cost = buy_cost / buy_shares if buy_shares else 0.0
        rows.append(
            {
                "code": code,
                "name": str(group["name"].iloc[-1]),
                "shares": net,
                "avg_cost": avg_cost,
                "sleeve": str(group["sleeve"].iloc[-1]),
            }
        )
    return pd.DataFrame(rows)


def _first_on_or_after(index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    later = index[index >= date]
    return later[0] if len(later) else None


def reconstruct() -> dict[str, object] | None:
    """从成交+资金流水重建实盘：每日持仓、现金、净值（元）。返回 None 表示还没成交。"""
    trades = get_trades()
    flows = get_cash_flows()
    if trades.empty:
        return None

    codes = sorted(trades["code"].unique())
    close_cols: dict[str, pd.Series] = {}
    for code in codes:
        if cache_exists(code):
            bars = load_cached_bars(code)
            close_cols[code] = bars.set_index("date")["close"]
    if not close_cols:
        return None
    close = pd.DataFrame(close_cols).sort_index()

    start = trades["date"].min()
    index = close.index[close.index >= start]
    # 把【晚于最后一根缓存 K 线】的成交/资金日期并入索引并 ffill 价格，否则这些交易会被
    # _first_on_or_after 丢弃（净值漏算，甚至全部晚于缓存时 index[-1] 崩溃）。范围内的成交
    # 行为不变：仍由 _first_on_or_after 向后吸附到下一个交易日。
    last_cached = close.index.max()
    event_dates = list(trades["date"])
    if not flows.empty:
        event_dates += list(flows["date"])
    tail = pd.DatetimeIndex(sorted({pd.Timestamp(d) for d in event_dates if pd.Timestamp(d) > last_cached}))
    if len(tail):
        index = index.append(tail).unique().sort_values()
    close = close.reindex(index).ffill()

    deltas = pd.DataFrame(0.0, index=index, columns=codes)
    cash_delta = pd.Series(0.0, index=index)
    for _, t in trades.iterrows():
        d = _first_on_or_after(index, t["date"])
        if d is None:
            continue
        sign = 1 if t["action"] == "buy" else -1
        deltas.loc[d, t["code"]] += sign * t["shares"]
        cash_delta.loc[d] += -(t["shares"] * t["price"] + t["fee"]) if sign > 0 else (t["shares"] * t["price"] - t["fee"])
    for _, f in flows.iterrows():
        d = _first_on_or_after(index, f["date"])
        if d is not None:
            cash_delta.loc[d] += f["amount"] if f["type"] != "withdraw" else -f["amount"]

    holdings = deltas.cumsum()
    cash = cash_delta.cumsum()
    holdings_value = (holdings * close.fillna(0.0)).sum(axis=1)
    equity = cash + holdings_value

    last = index[-1]
    current = holdings.loc[last]
    current = current[current > 0]
    current_holdings = [
        {"code": c, "shares": int(current[c]), "price": float(close.loc[last, c]), "value": float(current[c] * close.loc[last, c])}
        for c in current.index
    ]
    return {
        "equity": equity,
        "cash": cash,
        "holdings_value": holdings_value,
        "current_holdings": current_holdings,
        "index": index,
    }
