# Plan 004: Fix the benchmark inf bug in factor_pipeline (dirty 0→positive price poisons the curve)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: This plan targets **uncommitted working-tree
> code** built on top of commit `c253ce0`. A normal `git diff c253ce0..HEAD`
> will NOT show it. Instead, open `src/quant_a/factor_pipeline.py` and confirm
> the excerpts under "Current state" still match the live file. On any mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/001-test-baseline.md (for the pytest harness the regression test uses)
- **Category**: bug
- **Planned at**: commit `c253ce0`, 2026-06-16

## Why this matters

A stock whose cached price goes from `0` to a positive value on consecutive days produces a
`pct_change` of `+inf`. In `factor_pipeline._benchmark_returns`, that `inf` flows into the
equal-weight benchmark return on a day the stock is held, and `benchmark_curve = (1.0 +
benchmark_returns).cumprod()` then explodes to `inf` from that point on — making the benchmark
metrics (and the equity-vs-benchmark chart) garbage.

This exact bug was already found and fixed in the **live** core-satellite pipeline
(`cs_pipeline.py:102` adds `.replace([float("inf"), float("-inf")], 0.0)`), but the **research**
pipeline `factor_pipeline.py` was never patched. `factor_pipeline` is the module that produces the
de-biased `--mainboard` numbers and the `orders/factor_holdings.csv` list, so a bad benchmark there
silently corrupts the research conclusions. This plan ports the same one-line guard and adds a
regression test.

## Current state

`src/quant_a/factor_pipeline.py` — the low-volatility multi-factor research pipeline. The benchmark
helper, with the missing guard on the `pct_change` line:

```python
# line 34-46
def _benchmark_returns(close_matrix: pd.DataFrame, candidate_mask: pd.DataFrame) -> pd.Series:
    # 公平基准 = 月度等权持有【全部合格股】（同样月调、但不选股）。
    # 策略相对它的超额 = 纯粹的"选股"能力。月调让赢家在月内复利，口径与策略一致。
    daily = close_matrix.pct_change(fill_method=None)
    rebal = rebalance_dates(close_matrix.index)
    weights = pd.DataFrame(0.0, index=close_matrix.index, columns=close_matrix.columns)
    for date in rebal:
        eligible = candidate_mask.loc[date]
        names = eligible[eligible].index
        if len(names) > 0:
            weights.loc[date, names] = 1.0 / len(names)
    held = weights.loc[rebal].reindex(close_matrix.index).ffill().fillna(0.0)
    return (held.shift(1) * daily).sum(axis=1).fillna(0.0)
```

The downstream caller that turns the poisoned returns into a poisoned curve:

```python
# line 121-122
    benchmark_returns = _benchmark_returns(close_m, candidate)
    benchmark_curve = (1.0 + benchmark_returns).cumprod()
```

The already-correct sibling for reference — `src/quant_a/cs_pipeline.py:102`:

```python
    # 个别脏价格(0→正)会让 pct_change 出 inf、cumprod 炸成无穷，先把 inf 收益清成 0。
    daily = close_m.pct_change(fill_method=None).replace([float("inf"), float("-inf")], 0.0)
```

`rebalance_dates(index)` (from `factor_backtest.py`) picks, for each month, the first trading day
whose day-of-month ≥ `REBALANCE_DAY` (which is `15`). So a fixture spanning ~3 calendar months of
business days is guaranteed to contain at least one rebalance, which is required for a held weight
(and thus for the `inf` to actually reach the benchmark return).

Repo conventions: Chinese comments, `from __future__ import annotations`, type hints.

## Commands you will need

| Purpose       | Command                                                            | Expected on success |
|---------------|--------------------------------------------------------------------|---------------------|
| Install + dev | `.venv/bin/pip install -e ".[dev]"`                               | exit 0              |
| Run new test  | `.venv/bin/python -m pytest tests/test_factor_pipeline.py`        | exit 0; all pass    |
| Full suite    | `.venv/bin/python -m pytest`                                       | exit 0; all pass    |
| Byte-compile  | `.venv/bin/python -m py_compile src/quant_a/factor_pipeline.py`   | exit 0              |

Run from the repo root. If `.venv` is absent, see plan 001's Commands table.

NOTE: `factor_pipeline.py` imports `matplotlib` lazily inside `_save_charts`, and the test below
does **not** call `run_factor_pipeline` (which needs the data cache). The test imports only
`_benchmark_returns`, so it stays offline and fast.

## Scope

**In scope** (the only files you may modify or create):
- `src/quant_a/factor_pipeline.py` (modify — one line inside `_benchmark_returns`)
- `tests/test_factor_pipeline.py` (create)

**Out of scope** (do NOT touch):
- `src/quant_a/cs_pipeline.py` — already fixed; it is the reference, do not edit.
- `_save_charts`, `run_factor_pipeline`, `_print_*`, `main` — no changes; the fix is confined to
  `_benchmark_returns`.
- The strategy returns path (`run_factor_backtest`) — its `pct_change` handling is a separate
  concern; this plan only fixes the *benchmark* computation that mirrors the cs_pipeline fix.

## Git workflow

- Branch: `advisor/004-factor-pipeline-benchmark-inf`
- Commit style: short imperative English with trailing period. Suggested:
  `Drop inf returns from factor_pipeline benchmark.`
- Do NOT push or open a PR.

## Steps

### Step 1: Add the inf guard to `_benchmark_returns`

In `src/quant_a/factor_pipeline.py`, inside `_benchmark_returns`, change the `daily` line from:

```python
    daily = close_matrix.pct_change(fill_method=None)
```

to (mirroring `cs_pipeline.py:102`):

```python
    # 个别脏价格(0→正)会让 pct_change 出 inf、cumprod 炸成无穷，先把 inf 收益清成 0（与 cs_pipeline 一致）。
    daily = close_matrix.pct_change(fill_method=None).replace([float("inf"), float("-inf")], 0.0)
```

Do not change anything else.

**Verify**: `grep -n "replace(\[float(\"inf\")" src/quant_a/factor_pipeline.py` → returns a match;
and `.venv/bin/python -m py_compile src/quant_a/factor_pipeline.py` → exit 0.

### Step 2: Write the regression test `tests/test_factor_pipeline.py`

This builds a 3-month business-day price frame with one column that drops to `0` then recovers
(producing a `+inf` pct_change on the recovery day), and asserts the benchmark returns and curve
are finite. Create `tests/test_factor_pipeline.py` with exactly:

```python
import numpy as np
import pandas as pd

from quant_a.factor_pipeline import _benchmark_returns


def test_benchmark_is_finite_with_dirty_zero_price():
    idx = pd.bdate_range("2024-01-02", "2024-03-29")  # 跨 3 个月 -> 必含调仓日(每月约 15 号)
    close = pd.DataFrame({"AAA": 20.0, "BBB": 10.0}, index=idx)
    # BBB 出现一次脏价：2024-02-20 为 0，次日恢复 10 -> 恢复日 pct_change = inf
    close.loc["2024-02-20", "BBB"] = 0.0
    mask = pd.DataFrame(True, index=idx, columns=close.columns)

    ret = _benchmark_returns(close, mask)
    assert np.isfinite(ret).all(), "脏价(0→正)让 benchmark 收益出现了 inf/NaN"

    curve = (1.0 + ret).cumprod()
    assert np.isfinite(curve).all(), "benchmark 净值被 inf 污染（cumprod 炸成无穷）"
```

**Verify**: `.venv/bin/python -m pytest tests/test_factor_pipeline.py` → 1 passed, exit 0.

To confirm it is a real guard: if you temporarily revert Step 1, this test must **fail**
(`np.isfinite(ret).all()` is False because the recovery-day return is `inf`). Re-apply Step 1
before continuing. (Optional sanity check — do not leave the code reverted.)

### Step 3: Run the full suite

**Verify**: `.venv/bin/python -m pytest` → all pass, exit 0.

## Test plan

- New file `tests/test_factor_pipeline.py`, plain-`assert` style matching plan 001:
  - `test_benchmark_is_finite_with_dirty_zero_price` — the regression: a `0→positive` price spike no
    longer produces `inf` in either the benchmark return series or the cumulative curve.
- The test calls only `_benchmark_returns` with a synthetic frame — no data cache, no network, no
  matplotlib.
- Verification: `.venv/bin/python -m pytest tests/test_factor_pipeline.py` → 1 passed.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.venv/bin/python -m pytest tests/test_factor_pipeline.py` → 1 passed
- [ ] `.venv/bin/python -m pytest` exits 0 (full suite green)
- [ ] `grep -n 'replace(\[float("inf"), float("-inf")\], 0.0)' src/quant_a/factor_pipeline.py`
      returns a match (the guard is present)
- [ ] `git status --porcelain` shows only `src/quant_a/factor_pipeline.py` and
      `tests/test_factor_pipeline.py` changed/added
- [ ] `plans/README.md` status row for 004 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- The "Current state" excerpt does not match the live `factor_pipeline.py` (drift).
- After Step 1 the test still fails `np.isfinite(ret).all()` — `rebalance_dates` may not have
  produced a rebalance in the fixture window (so BBB never got weight, meaning the test isn't
  exercising the bug). Report the rebalance dates you observe; do not weaken the assertion.
- `2024-02-20` is not present in `pd.bdate_range("2024-01-02", "2024-03-29")` in this pandas
  version (it is a Tuesday, so it should be) — if `close.loc["2024-02-20", "BBB"] = 0.0` raises a
  KeyError, report it rather than picking an arbitrary different date.

## Maintenance notes

- The strategy-side returns in `run_factor_backtest` are a separate code path; this plan does not
  touch them. If a future audit finds the same `pct_change` inf hazard there, fix it the same way
  and add an analogous test.
- `_benchmark_returns` here and the inline benchmark block in `cs_pipeline.py` are now two copies of
  the same equal-weight-benchmark logic with the same guard. If a third copy appears, or the two
  drift apart, consider lifting a shared `equal_weight_benchmark(close, mask)` helper — but only as
  part of the larger pipeline-consolidation work (a separate, unplanned finding), not here.
- A reviewer should confirm the guard sets inf→0 (treat a dirty recovery day as a flat day), which
  matches `cs_pipeline`'s intent; do not change it to drop the row or forward-fill, which would
  diverge from the live pipeline.
