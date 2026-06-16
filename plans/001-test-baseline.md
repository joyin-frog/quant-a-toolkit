# Plan 001: Establish a pytest baseline with unit tests for the core pure logic

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: This plan targets **uncommitted working-tree
> code** built on top of commit `c253ce0`. A normal `git diff c253ce0..HEAD`
> will NOT show it — the session's work is not committed. Instead, open each
> file quoted under "Current state" and confirm the excerpts still match the
> live file. On any mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `c253ce0`, 2026-06-16

## Why this matters

The repo has **zero automated tests** (`tests/` exists but is empty; `pyproject.toml`
declares no test runner). Every change so far has been verified only by running the
full pipeline by hand, which needs network data and takes tens of seconds. This makes
the three bug-fix plans (002, 003, 004) unable to ship a regression test, and blocks
any future refactor from being done safely.

This plan installs a test runner and writes a first set of **fast, offline, deterministic**
unit tests for the three most load-bearing pure-logic modules: performance metrics
(`metrics.py`), factor stock-selection (`factor_strategy.py`), and the web/JSON helpers
(`portfolio_web.py`). It is the foundation the other three plans build their regression
tests on. After this lands, `python -m pytest` is a real verification gate.

## Current state

The relevant files:

- `pyproject.toml` — project metadata + runtime deps; **no** `[project.optional-dependencies]`,
  **no** `[tool.pytest.ini_options]`. Current full content:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "quant-a"
version = "0.1.0"
description = "Minimal A-share ETF rotation scaffold"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "akshare>=1.16.0",
  "alphalens-reloaded>=0.4.6",
  "backtrader>=1.9.78.123",
  "empyrical-reloaded>=0.5.12",
  "matplotlib>=3.9.0",
  "numpy>=1.26.0",
  "pandas>=2.2.0",
  "streamlit>=1.45.0",
]

[tool.setuptools.packages.find]
where = ["src"]
```

- `tests/` — exists but is **empty** (untracked, no files).

- `src/quant_a/metrics.py` — performance metrics. The function under test:

```python
def calculate_metrics(returns: pd.Series, equity_curve: pd.Series) -> dict[str, float]:
    clean_returns = returns.astype(float).fillna(0.0)
    non_zero_returns = clean_returns[clean_returns != 0]
    total_return = float(ep.cum_returns_final(clean_returns))
    ...
    return {
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "win_rate": win_rate,
    }
```

  NOTE: `calculate_metrics` can legitimately return **NaN** for degenerate input
  (e.g. all-zero returns → Sharpe is NaN). Do **not** write a test asserting all
  metrics are finite — that is false and is exactly why plans 002/004 add NaN
  sanitization elsewhere. Test only the robust invariants listed in the Test plan.

- `src/quant_a/factor_strategy.py` — factor scoring + selection (pure functions).
  `select_holdings_on(date, panel, candidate_mask, holdings, weights=None, require_full=True,
  current_holdings=None, sell_rank=None)`:
  - `panel` is a dict of factor-name → DataFrame (index = dates, columns = symbols);
    must contain at least `"lowvol"` and `"mom"` (validity filter uses both).
  - With `require_full=True`, returns `[]` when fewer than `holdings` candidates score.
  - **Buffer band**: when `current_holdings` and `sell_rank` are given and
    `sell_rank > holdings`, an existing holding is kept as long as its rank ≤ `sell_rank`;
    freed slots are filled from the top `holdings`. See lines 102-117.
  - For factors absent from `panel`, the weight is skipped, so a panel with only
    `lowvol`+`mom` uses only those two weights regardless of `FACTOR_WEIGHTS`.

- `src/quant_a/portfolio_web.py` — web/JSON CLI helpers. Two pure helpers under test:

```python
def _num(x) -> float | None:
    """NaN/Inf → None（JS 的 JSON.parse 不认 NaN，必须清洗）。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, 4) if np.isfinite(v) else None
```

  and `_next_rebalance(rebalance_day: int = REBALANCE_DAY or 15)` which returns a dict
  with keys `rebalance_day`, `next_date`, `days_until`, `is_rebalance_window`, computed
  off `date.today()` (not injectable — test invariants only).

Repo conventions to match:
- Modules start with a Chinese docstring; comments are Chinese. Tests may use short
  Chinese comments where helpful, but keep test function names English `snake_case`.
- `from __future__ import annotations` at the top of source modules. Test files do not
  need it.
- Type hints on function signatures.

## Commands you will need

| Purpose            | Command                                                        | Expected on success            |
|--------------------|---------------------------------------------------------------|--------------------------------|
| Create venv (once) | `python3 -m venv .venv`                                        | exit 0; `.venv/` created       |
| Install + dev deps | `.venv/bin/pip install -e ".[dev]"`                           | exit 0; pytest installed       |
| Run tests          | `.venv/bin/python -m pytest`                                   | exit 0; all tests pass         |
| Run one file       | `.venv/bin/python -m pytest tests/test_metrics.py`            | exit 0                         |

Run all commands from the repository root. If a `.venv` already exists at the repo root,
skip the create step and just run the install. (The git worktree used during development
has no `.venv`; create one or run in the main checkout.)

If your environment cannot reach PyPI to install `pytest`, STOP and report — do not
vendor or hand-roll a runner.

## Scope

**In scope** (the only files you may modify or create):
- `pyproject.toml` (modify — add dev extra + pytest config)
- `tests/test_metrics.py` (create)
- `tests/test_factor_strategy.py` (create)
- `tests/test_portfolio_web.py` (create)
- `tests/__init__.py` (create only if pytest collection fails without it — see Step 3)

**Out of scope** (do NOT touch):
- Any file under `src/quant_a/` — this plan only adds tests and config. Fixing the bugs
  those modules contain is the job of plans 002/003/004.
- Runtime dependency list in `pyproject.toml` (the `dependencies = [...]` array) — do not
  add, remove, or re-pin runtime deps here. Only add the new `[project.optional-dependencies]`
  and `[tool.pytest.ini_options]` tables.

## Git workflow

- Branch: `advisor/001-test-baseline`
- Commit style matches the repo log (short imperative English, capitalized, trailing period —
  e.g. `git log` shows `Add Streamlit backtest UI.`). Suggested message:
  `Add pytest baseline and unit tests for core logic.`
- Do NOT push or open a PR.

## Steps

### Step 1: Add the dev extra and pytest config to `pyproject.toml`

Append these two tables to the **end** of `pyproject.toml` (after the existing
`[tool.setuptools.packages.find]` table). The `pythonpath = ["src"]` line lets pytest
import `quant_a` without setting `PYTHONPATH`:

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"
```

Do not modify the existing tables.

**Verify**: `grep -n "pytest" pyproject.toml` → shows the `pytest>=8.0` line and the
`[tool.pytest.ini_options]` header.

### Step 2: Install dev dependencies

Run the venv + install commands from the Commands table.

**Verify**: `.venv/bin/python -m pytest --version` → prints a `pytest 8.x` version line, exit 0.

### Step 3: Write `tests/test_metrics.py`

Create `tests/test_metrics.py` with exactly this content:

```python
import numpy as np
import pandas as pd

from quant_a.metrics import calculate_metrics


def _series(vals):
    idx = pd.bdate_range("2024-01-02", periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)


def test_total_return_matches_compounded_product():
    r = _series([0.01, -0.02, 0.03, 0.0, 0.015])
    m = calculate_metrics(r, (1 + r).cumprod())
    expected = float((1 + r).prod() - 1)
    assert abs(m["total_return"] - expected) < 1e-9


def test_metric_ranges_are_sane():
    r = _series([0.02, -0.05, 0.03, -0.01, 0.04])
    m = calculate_metrics(r, (1 + r).cumprod())
    assert -1.0 <= m["max_drawdown"] <= 0.0
    assert 0.0 <= m["win_rate"] <= 1.0
    assert {"total_return", "annualized_return", "max_drawdown", "sharpe", "win_rate"} <= set(m)


def test_all_zero_returns_total_is_zero():
    r = _series([0.0, 0.0, 0.0])
    m = calculate_metrics(r, (1 + r).cumprod())
    assert m["total_return"] == 0.0
```

**Verify**: `.venv/bin/python -m pytest tests/test_metrics.py` → 3 passed, exit 0.

If collection fails with `ModuleNotFoundError: quant_a`, create an empty `tests/__init__.py`
and re-run. If it still fails, STOP and report (the `pythonpath` config from Step 1 is not
taking effect).

### Step 4: Write `tests/test_factor_strategy.py`

Create `tests/test_factor_strategy.py` with exactly this content. The fixture makes
A > B > C > D > E by score (both factors rank symbols in that order):

```python
import pandas as pd

from quant_a.factor_strategy import select_holdings_on


def _panel_and_mask():
    dates = pd.to_datetime(["2024-01-15", "2024-02-15"])
    syms = ["A", "B", "C", "D", "E"]
    vals = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}
    lowvol = pd.DataFrame([[vals[s] for s in syms]] * 2, index=dates, columns=syms)
    mom = lowvol.copy()
    panel = {"lowvol": lowvol, "mom": mom}
    mask = pd.DataFrame(True, index=dates, columns=syms)
    return panel, mask, dates


def test_select_top_holdings_by_score():
    panel, mask, dates = _panel_and_mask()
    picks = select_holdings_on(dates[0], panel, mask, holdings=2)
    assert picks == ["A", "B"]


def test_require_full_returns_empty_when_insufficient():
    panel, mask, dates = _panel_and_mask()
    picks = select_holdings_on(dates[0], panel, mask, holdings=10, require_full=True)
    assert picks == []


def test_buffer_band_keeps_existing_holding():
    panel, mask, dates = _panel_and_mask()
    # 已持有 C（综合排名第 3）。买入门槛是前 2 名，但 sell_rank=4：C 仍在前 4 名内 -> 保留不卖。
    picks = select_holdings_on(
        dates[0], panel, mask, holdings=2, current_holdings=["C"], sell_rank=4
    )
    assert set(picks) == {"C", "A"}
    assert "B" not in picks  # 缓冲带保住了 C，B 这次没顶上来
```

**Verify**: `.venv/bin/python -m pytest tests/test_factor_strategy.py` → 3 passed, exit 0.

If `test_select_top_holdings_by_score` returns something other than `["A", "B"]`, STOP and
report — the scoring/ranking contract has drifted from what this plan assumes.

### Step 5: Write `tests/test_portfolio_web.py`

Create `tests/test_portfolio_web.py` with exactly this content:

```python
import quant_a.portfolio_web as pw


def test_num_sanitizes_nan_inf():
    assert pw._num(1.23456) == 1.2346
    assert pw._num(float("nan")) is None
    assert pw._num(float("inf")) is None
    assert pw._num(float("-inf")) is None
    assert pw._num("not-a-number") is None
    assert pw._num(None) is None


def test_next_rebalance_invariants():
    r = pw._next_rebalance(rebalance_day=15)
    assert r["rebalance_day"] == 15
    assert r["days_until"] >= 0
    # next_date 可被解析为 YYYY-MM-DD
    import datetime

    datetime.date.fromisoformat(r["next_date"])
```

**Verify**: `.venv/bin/python -m pytest tests/test_portfolio_web.py` → 2 passed, exit 0.

### Step 6: Run the full suite

**Verify**: `.venv/bin/python -m pytest` → **8 passed**, exit 0.

## Test plan

This plan *is* the test baseline. New tests:
- `tests/test_metrics.py` — total-return identity, metric ranges, zero-return edge (3 tests).
- `tests/test_factor_strategy.py` — top-K selection, `require_full` empty case, buffer band (3 tests).
- `tests/test_portfolio_web.py` — `_num` sanitizer, `_next_rebalance` invariants (2 tests).

No existing test to model after (there are none); the structure above (module-level helpers
+ `test_*` functions, plain `assert`) is the pattern plans 002/003/004 must follow.

Verification: `.venv/bin/python -m pytest` → 8 passed.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.venv/bin/python -m pytest` exits 0 with **8 passed**
- [ ] `grep -n "pytest>=8.0" pyproject.toml` returns a match
- [ ] `grep -n "tool.pytest.ini_options" pyproject.toml` returns a match
- [ ] `ls tests/test_metrics.py tests/test_factor_strategy.py tests/test_portfolio_web.py` lists all three
- [ ] `git status --porcelain src/quant_a/` is empty (no source file modified)
- [ ] `plans/README.md` status row for 001 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- Any "Current state" excerpt does not match the live file (codebase drifted).
- `pip install` cannot reach PyPI to fetch pytest.
- `test_select_top_holdings_by_score` does not return `["A", "B"]`, or
  `test_buffer_band_keeps_existing_holding` does not yield `{"C", "A"}` — the selection
  contract differs from this plan's assumption; do not "fix" the test to match, report it.
- Importing `quant_a.portfolio_web` raises at collection time (it pulls in `cache`, `config`,
  `metrics`, `portfolio_db`; an import error means an environment problem, not a test bug).

## Maintenance notes

- These tests are deliberately offline and data-free; never add a test here that hits akshare
  or reads `data/`. Network/data-dependent checks belong in a separate, opt-in suite.
- `_next_rebalance` is tested by invariants only because it reads `date.today()`. If it is ever
  refactored to accept an injectable "today", tighten the test to assert exact dates.
- Plans 002, 003, 004 each add one regression test file and depend on this harness existing.
  A reviewer should confirm those land *after* this plan, or at least with this plan's
  `pyproject.toml` changes included.
- The runtime deps `alphalens-reloaded`, `backtrader`, `streamlit` are suspected dead weight
  (a separate, unplanned finding D). Do not touch them here, but a future cleanup will revisit
  the dependency list — keep the dev extra separate so that cleanup is independent.
