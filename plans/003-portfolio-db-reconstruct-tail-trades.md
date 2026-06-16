# Plan 003: Stop portfolio_db.reconstruct from silently dropping trades dated after the last cached price

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: This plan targets **uncommitted working-tree
> code** built on top of commit `c253ce0`. A normal `git diff c253ce0..HEAD`
> will NOT show it. Instead, open `src/quant_a/portfolio_db.py` and confirm the
> excerpts under "Current state" still match the live file. On any mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: plans/001-test-baseline.md (for the pytest harness the regression test uses)
- **Category**: bug
- **Planned at**: commit `c253ce0`, 2026-06-16

## Why this matters

`portfolio_db.reconstruct()` rebuilds the live-trading equity curve from recorded trades by
indexing them onto cached price dates. It builds its date index purely from cached close prices
(`index = close.index[close.index >= start]`) and places each trade with
`_first_on_or_after(index, trade_date)`, which returns `None` when **no cached price date is on or
after the trade date**. When that happens the trade is silently `continue`-skipped.

This is exactly the normal mid-month workflow the user just built: you record a real trade *today*,
but the local price cache may not have a bar for today yet. The trade then vanishes from the
reconstructed equity — under-counting holdings and corrupting every performance number derived
from it (real-vs-backtest, tracking error, P&L). In the worst case (all trades dated after the
last cached bar) `index` is empty and `reconstruct()` raises `IndexError` at `index[-1]`.

The fix: extend the reconstruction index with any trade/cash-flow dates that fall **after the last
cached price**, and forward-fill prices onto them so those trades are placed and valued at the last
known close. In-range behavior is unchanged.

## Current state

`src/quant_a/portfolio_db.py` — SQLite-backed live accounting. The two relevant pieces:

```python
# line 101-103 — the helper that returns None for a date past the end of the index
def _first_on_or_after(index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    later = index[index >= date]
    return later[0] if len(later) else None
```

```python
# line 106-139 — reconstruct(): the index is bounded by cached prices, so post-cache trades drop
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
```

Downstream of the excerpt (do not change these lines, shown for context):

```python
    holdings = deltas.cumsum()
    cash = cash_delta.cumsum()
    holdings_value = (holdings * close.fillna(0.0)).sum(axis=1)
    equity = cash + holdings_value
    last = index[-1]
    current = holdings.loc[last]
    current = current[current > 0]
    current_holdings = [ ... ]
    return {"equity": equity, "cash": cash, "holdings_value": holdings_value,
            "current_holdings": current_holdings, "index": index}
```

Facts that make the fix correct:
- `get_trades()` returns `date` as `datetime64` (it does `pd.to_datetime`). `get_cash_flows()`
  likewise, and returns an empty DataFrame **with** a `date` column when there are no flows.
- At the point of the fix, `close` (line 121) is the full cached frame, **before** the
  `close.reindex(index)` on line 125. So `close.index.max()` is the latest cached date across all
  held codes — the correct "last cached price" boundary.
- `holdings_value` on line 143 already does `close.fillna(0.0)`, so a forward-filled tail with no
  prior price (the rare all-after-cache case) degrades to a 0 valuation rather than crashing.

Repo conventions: Chinese comments, `from __future__ import annotations`, type hints.

## Commands you will need

| Purpose       | Command                                                          | Expected on success |
|---------------|------------------------------------------------------------------|---------------------|
| Install + dev | `.venv/bin/pip install -e ".[dev]"`                             | exit 0              |
| Run new test  | `.venv/bin/python -m pytest tests/test_portfolio_db.py`         | exit 0; all pass    |
| Full suite    | `.venv/bin/python -m pytest`                                     | exit 0; all pass    |
| Byte-compile  | `.venv/bin/python -m py_compile src/quant_a/portfolio_db.py`    | exit 0              |

Run from the repo root. If `.venv` is absent, see plan 001's Commands table.

## Scope

**In scope** (the only files you may modify or create):
- `src/quant_a/portfolio_db.py` (modify — only the two lines that build `index`, inside `reconstruct`)
- `tests/test_portfolio_db.py` (create)

**Out of scope** (do NOT touch):
- `_first_on_or_after` — leave its body exactly as is. The fix works by feeding it a richer index,
  not by changing the helper. (Changing it would alter the in-range "snap forward to next trading
  day" behavior, which must stay.)
- `add_trade`, `add_cash_flow`, `get_trades`, `get_cash_flows`, `current_positions`, `_conn`,
  the table DDL — no schema or query changes.
- The downstream `holdings/cash/equity/current_holdings` computation (lines 141-159).

## Git workflow

- Branch: `advisor/003-portfolio-db-reconstruct-tail-trades`
- Commit style: short imperative English with trailing period. Suggested:
  `Keep trades dated after the last cached price in reconstruct.`
- Do NOT push or open a PR.

## Steps

### Step 1: Extend the reconstruction index with post-cache event dates

In `reconstruct()`, replace these two lines:

```python
    start = trades["date"].min()
    index = close.index[close.index >= start]
    close = close.reindex(index).ffill()
```

with this block (note `close.index.max()` is captured **before** the reindex, while `close` is
still the full cached frame):

```python
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
```

Do not change anything else in the function.

**Verify**: `.venv/bin/python -m py_compile src/quant_a/portfolio_db.py` → exit 0.

### Step 2: Write the regression test `tests/test_portfolio_db.py`

This test uses a temp SQLite DB and a synthetic in-memory price cache (monkeypatched), records one
trade inside the cache range and one trade **after** the last cached bar, and asserts both are
counted. Create `tests/test_portfolio_db.py` with exactly:

```python
import pandas as pd

import quant_a.portfolio_db as db


def _fake_bars():
    cache_dates = pd.bdate_range("2024-01-02", "2024-01-31")
    return pd.DataFrame(
        {
            "date": cache_dates,
            "open": 10.0,
            "high": 10.0,
            "low": 10.0,
            "close": 10.0,
            "volume": 1,
        }
    )


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "portfolio.db")
    monkeypatch.setattr(db, "cache_exists", lambda code: code == "600000")
    monkeypatch.setattr(db, "load_cached_bars", lambda code: _fake_bars())


def test_reconstruct_keeps_trade_after_last_cached_price(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    db.add_trade("2024-01-05", "600000", "X", "buy", 100, 10.0)   # 缓存范围内
    db.add_trade("2024-02-15", "600000", "X", "buy", 100, 10.0)   # 晚于最后缓存价(01-31)
    rc = db.reconstruct()
    assert rc is not None
    held = {h["code"]: h["shares"] for h in rc["current_holdings"]}
    assert held.get("600000") == 200, "晚于最后缓存价的成交被漏算了"
    # 净值末值 = 200 股 * 10 元 - 现金支出(2000) ... 现金为负，holdings_value=2000
    assert rc["holdings_value"].iloc[-1] == 2000.0


def test_reconstruct_in_range_trade_still_snaps_forward(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    # 周六(01-06，非交易日)买入：应被吸附到下一个交易日，仍计入。
    db.add_trade("2024-01-06", "600000", "X", "buy", 100, 10.0)
    rc = db.reconstruct()
    held = {h["code"]: h["shares"] for h in rc["current_holdings"]}
    assert held.get("600000") == 100
```

**Verify**: `.venv/bin/python -m pytest tests/test_portfolio_db.py` → 2 passed, exit 0.

To prove this is a real regression guard: if you temporarily revert Step 1, the first test must
**fail** with `held.get("600000") == 100` (the post-cache trade dropped). Re-apply Step 1 before
continuing. (Optional sanity check — do not leave the code reverted.)

### Step 3: Run the full suite

**Verify**: `.venv/bin/python -m pytest` → all pass (10 from plans 001+002 if those landed, plus 2
here; if running standalone on top of 001 only, 8 + 2 = 10), exit 0.

## Test plan

- New file `tests/test_portfolio_db.py`, plain-`assert` style matching plan 001:
  - `test_reconstruct_keeps_trade_after_last_cached_price` — the regression: an in-range buy plus a
    post-cache buy yields 200 shares (before the fix it was 100).
  - `test_reconstruct_in_range_trade_still_snaps_forward` — guards the unchanged behavior: a
    non-trading-day trade inside the cache range still snaps to the next trading day and is counted.
- Both use `monkeypatch` to swap `DB_PATH`, `cache_exists`, and `load_cached_bars`, so no real DB,
  network, or `data/` access occurs.
- Verification: `.venv/bin/python -m pytest tests/test_portfolio_db.py` → 2 passed.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.venv/bin/python -m pytest tests/test_portfolio_db.py` → 2 passed
- [ ] `.venv/bin/python -m pytest` exits 0 (full suite green)
- [ ] `grep -n "last_cached = close.index.max()" src/quant_a/portfolio_db.py` returns a match
- [ ] `grep -n "def _first_on_or_after" src/quant_a/portfolio_db.py` still returns a match and its
      body is unchanged (the helper was not edited)
- [ ] `git status --porcelain` shows only `src/quant_a/portfolio_db.py` and
      `tests/test_portfolio_db.py` changed/added
- [ ] `plans/README.md` status row for 003 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- The "Current state" excerpts do not match the live `portfolio_db.py` (drift).
- `test_reconstruct_keeps_trade_after_last_cached_price` still asserts 100 (not 200) after Step 1
  — the fix did not take; report the actual `current_holdings` rather than tweaking the test.
- `load_cached_bars` in the real module expects a column not present in `_fake_bars()` and raises
  during `reconstruct` — report the missing column; do not silently add unrelated columns beyond
  what `set_index("date")["close"]` needs.
- You find yourself wanting to edit `_first_on_or_after` to make a test pass — that is out of scope;
  stop and report.

## Maintenance notes

- The rare "all trades dated after the last cached bar" case no longer crashes, but those holdings
  are valued at 0 until prices are refreshed (forward-fill has nothing to carry). The intended
  operational flow is: refresh prices around the trade, then reconstruct. If a future change makes
  reconstruction run before any price refresh, revisit this — you may want to fetch a price for the
  trade date instead of forward-filling.
- This valuation uses the last *known* close for post-cache dates; it is an estimate, not a mark to
  an actual close. A reviewer should confirm the UI/report copy does not imply these tail points are
  real market closes.
- If `reconstruct` is ever extended to handle short positions or T+1 settlement, the index-building
  block changed here is the place that decides which dates exist; keep the "tail dates after last
  cache" rule in mind.
