# Plan 002: Sanitize NaN/Inf in cs_web JSON output so the web "生成清单" never breaks

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: This plan targets **uncommitted working-tree
> code** built on top of commit `c253ce0`. A normal `git diff c253ce0..HEAD`
> will NOT show it. Instead, open `src/quant_a/cs_web.py` and confirm the
> excerpts under "Current state" still match the live file. On any mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/001-test-baseline.md (for the pytest harness the regression test uses)
- **Category**: bug
- **Planned at**: commit `c253ce0`, 2026-06-16

## Why this matters

The web "生成清单" (generate rebalance list) page calls `quant_a.cs_web`, which prints a JSON
payload that a Next.js API route parses with `JSON.parse`. `cs_web.build_payload` formats its
metric numbers with bare `round(float(v), 4)` (lines 23, 42, 43, 44, 46). When the strategy or
benchmark produces a degenerate value — Sharpe/Calmar/Sortino are **NaN** for near-zero-variance
return windows, and `empyrical` can yield `inf` — Python's `json.dumps` emits the literal tokens
`NaN` / `Infinity`. **`JSON.parse` rejects those**, so the whole page errors out instead of
showing the list.

The sibling module `portfolio_web.py` already solved this with a `_num()` helper (NaN/Inf → None).
`cs_web.py` was written without it. This plan ports the same helper into `cs_web` and routes the
metric fields through it, matching the established convention, plus adds a regression test.

## Current state

- `src/quant_a/cs_web.py` — JSON entrypoint for the web "月度调仓" page. It does **not**
  import `numpy` and has **no** `_num` helper. The two relevant spots:

```python
# line 17-23 — curve downsampler
def _sample_curve(curve: pd.Series, max_points: int = 240) -> list[dict[str, object]]:
    monthly = curve.resample("ME").last().dropna()
    if len(monthly) > max_points:
        step = len(monthly) // max_points + 1
        monthly = monthly.iloc[::step]
    return [{"date": d.strftime("%Y-%m"), "value": round(float(v), 4)} for d, v in monthly.items()]
```

```python
# line 38-51 — payload assembly (the bug is the bare round(float(v), 4) in the dict comprehensions)
    return {
        "params": {"capital": capital, "holdings": holdings, "ai_weight": ai_weight},
        "as_of": end.strftime("%Y-%m-%d"),
        "range": f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}",
        "metrics": {k: round(float(v), 4) for k, v in result["metrics"].items()},
        "benchmark": {k: round(float(v), 4) for k, v in result["benchmark_metrics"].items()},
        "rolling12m": {k: round(float(v), 4) for k, v in result["rolling12m"].items()},
        "core_sectors": result["core_sectors"],
        "avg_cash_pct": round(float(result["avg_cash_pct"]), 4),
        "invested": float(buy_list.attrs.get("invested", 0)),
        "cash_left": float(buy_list.attrs.get("cash_left", 0)),
        "holdings_list": buy_list.to_dict(orient="records"),
        "curve": curve,
    }
```

```python
# line 54-61 — CLI main
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=float, default=200000)
    parser.add_argument("--holdings", type=int, default=17)
    parser.add_argument("--ai_weight", type=float, default=0.15)
    args = parser.parse_args()
    payload = build_payload(args.capital, args.holdings, args.ai_weight)
    print(json.dumps(payload, ensure_ascii=False, default=str))
```

- `src/quant_a/portfolio_web.py` — the exemplar to copy from. Its helper:

```python
def _num(x) -> float | None:
    """NaN/Inf → None（JS 的 JSON.parse 不认 NaN，必须清洗）。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, 4) if np.isfinite(v) else None
```

Repo conventions to match:
- Chinese docstring/comments, `from __future__ import annotations`, type hints.
- `cs_web.py` already imports `pandas as pd`; it does **not** import `numpy` — you will add it.

## Commands you will need

| Purpose       | Command                                                       | Expected on success     |
|---------------|---------------------------------------------------------------|-------------------------|
| Install + dev | `.venv/bin/pip install -e ".[dev]"`                          | exit 0                  |
| Run new test  | `.venv/bin/python -m pytest tests/test_cs_web.py`            | exit 0; all pass        |
| Full suite    | `.venv/bin/python -m pytest`                                  | exit 0; all pass        |
| Byte-compile  | `.venv/bin/python -m py_compile src/quant_a/cs_web.py`       | exit 0                  |

Run from the repo root. If `.venv` is absent, see plan 001's Commands table to create it.

## Scope

**In scope** (the only files you may modify or create):
- `src/quant_a/cs_web.py` (modify)
- `tests/test_cs_web.py` (create)

**Out of scope** (do NOT touch):
- `src/quant_a/cs_pipeline.py` — `build_payload` calls `run_cs_pipeline` from here, but this
  plan only sanitizes the JSON layer. Do not change the pipeline.
- `src/quant_a/portfolio_web.py` — already correct; it is the reference, do not edit it.
- `holdings_list`, `invested`, `cash_left` — leave these as-is (they are finite by construction:
  prices × integer lots and their sums). Do not rewrite them in this plan; see Maintenance notes.
- The Next.js code under `web/` — no frontend changes needed.

## Git workflow

- Branch: `advisor/002-cs-web-nan-sanitize`
- Commit style: short imperative English with trailing period. Suggested:
  `Sanitize NaN/Inf in cs_web JSON payload.`
- Do NOT push or open a PR.

## Steps

### Step 1: Add the `numpy` import and the `_num` helper to `cs_web.py`

In `src/quant_a/cs_web.py`, add `import numpy as np` alongside the existing imports (it already
has `import pandas as pd`). Then add the `_num` helper — copy it verbatim from `portfolio_web.py`
— placing it above `_sample_curve`:

```python
def _num(x) -> float | None:
    """NaN/Inf → None（JS 的 JSON.parse 不认 NaN，必须清洗）。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, 4) if np.isfinite(v) else None
```

**Verify**: `.venv/bin/python -m py_compile src/quant_a/cs_web.py` → exit 0, no output.

### Step 2: Route the metric fields through `_num`

Make these four replacements in `build_payload` (the dict returned at lines 38-51). The
`round(float(v), 4)` becomes `_num(v)`, and `avg_cash_pct` uses `_num(...)`:

```python
        "metrics": {k: _num(v) for k, v in result["metrics"].items()},
        "benchmark": {k: _num(v) for k, v in result["benchmark_metrics"].items()},
        "rolling12m": {k: _num(v) for k, v in result["rolling12m"].items()},
        "core_sectors": result["core_sectors"],
        "avg_cash_pct": _num(result["avg_cash_pct"]),
```

Also sanitize the curve value in `_sample_curve` — change its return line to:

```python
    return [{"date": d.strftime("%Y-%m"), "value": _num(v)} for d, v in monthly.items()]
```

Leave `invested`, `cash_left`, and `holdings_list` unchanged (out of scope).

**Verify**: `grep -n "round(float(v), 4)\|round(float(result" src/quant_a/cs_web.py` → **no matches**
(every bare `round(float(...), 4)` on a metric is gone).

### Step 3: Write the regression test `tests/test_cs_web.py`

This test feeds a fake pipeline result containing NaN/Inf metrics through `build_payload` and
asserts the payload is JSON-safe under `allow_nan=False` (which raises if any `NaN`/`Infinity`
remains). It monkeypatches `run_cs_pipeline` so it needs no network or data cache. Create
`tests/test_cs_web.py` with exactly:

```python
import json

import pandas as pd

import quant_a.cs_web as cs_web


def _fake_result():
    idx = pd.bdate_range("2024-01-02", periods=300)
    equity = pd.Series(1.0, index=idx)
    bench = pd.Series(1.0, index=idx)
    buy = pd.DataFrame(
        [{"code": "600000", "name": "X", "sleeve": "core", "shares": 100, "amount": 1000.0, "weight": 0.5}]
    )
    buy.attrs["invested"] = 1000.0
    buy.attrs["cash_left"] = 0.0
    return {
        "date_range": (idx[0], idx[-1]),
        "buy_list": buy,
        "equity_curve": equity,
        "benchmark_curve": bench,
        "metrics": {"total_return": float("nan"), "sharpe": float("inf"), "max_drawdown": -0.1},
        "benchmark_metrics": {"total_return": 0.2},
        "rolling12m": {"median": float("nan")},
        "core_sectors": {"银行": 2},
        "avg_cash_pct": float("nan"),
    }


def test_num_sanitizes_nan_inf():
    assert cs_web._num(1.23456) == 1.2346
    assert cs_web._num(float("nan")) is None
    assert cs_web._num(float("inf")) is None
    assert cs_web._num(float("-inf")) is None
    assert cs_web._num("x") is None


def test_build_payload_is_json_safe(monkeypatch):
    monkeypatch.setattr(cs_web, "run_cs_pipeline", lambda **kw: _fake_result())
    payload = cs_web.build_payload(200000, 17, 0.15)
    # allow_nan=False 会在残留 NaN/Inf 时抛错；不抛 = 已清洗干净。
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, default=str)
    assert "NaN" not in text and "Infinity" not in text
    assert payload["metrics"]["total_return"] is None  # NaN -> None
    assert payload["metrics"]["sharpe"] is None         # Inf -> None
    assert payload["avg_cash_pct"] is None              # NaN -> None
    assert payload["rolling12m"]["median"] is None      # NaN -> None
```

**Verify**: `.venv/bin/python -m pytest tests/test_cs_web.py` → 2 passed, exit 0.

### Step 4: Run the full suite

**Verify**: `.venv/bin/python -m pytest` → all tests pass (8 from plan 001 + 2 here = 10),
exit 0.

## Test plan

- New file `tests/test_cs_web.py`, modeled on the plain-`assert` style from plan 001's tests:
  - `test_num_sanitizes_nan_inf` — unit-tests the ported helper (happy path + NaN + ±Inf + non-numeric).
  - `test_build_payload_is_json_safe` — the regression: a fake result with NaN/Inf metrics yields a
    payload that serializes under `allow_nan=False`, and the specific fields become `None`.
- Verification: `.venv/bin/python -m pytest tests/test_cs_web.py` → 2 passed; full suite → 10 passed.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.venv/bin/python -m pytest tests/test_cs_web.py` → 2 passed
- [ ] `.venv/bin/python -m pytest` exits 0 (full suite green)
- [ ] `grep -n "round(float(v), 4)" src/quant_a/cs_web.py` returns **no matches**
- [ ] `grep -n "def _num" src/quant_a/cs_web.py` returns a match
- [ ] `grep -n "import numpy as np" src/quant_a/cs_web.py` returns a match
- [ ] `git status --porcelain` shows only `src/quant_a/cs_web.py` and `tests/test_cs_web.py` changed/added
- [ ] `plans/README.md` status row for 002 updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- The "Current state" excerpts do not match the live `cs_web.py` (drift).
- After Step 2, `test_build_payload_is_json_safe` still raises a `ValueError` from
  `json.dumps(..., allow_nan=False)` — it means a NaN/Inf field was missed. Report which key
  appears in the error; do NOT silence it by removing `allow_nan=False`.
- `build_payload`'s set of result keys differs from the fake fixture's keys such that it raises
  `KeyError` — the pipeline contract drifted; report it rather than editing the fixture blindly.

## Maintenance notes

- `holdings_list`, `invested`, `cash_left` are intentionally left unsanitized because they are
  finite by construction. If a future change derives any of them from a ratio or an
  `empyrical` output (which can be NaN), route those through `_num` too — and consider adding
  `allow_nan=False` to the `json.dumps` in `cs_web.main()` as a permanent tripwire.
- `_num` is now duplicated in `portfolio_web.py` and `cs_web.py`. That duplication is acceptable
  for now (two small CLIs), but if a third copy appears, lift `_num` into a shared
  `quant_a/jsonsafe.py`. A reviewer should flag any *third* copy.
- This is the same class of bug as plan 004 (non-finite floats poisoning a downstream consumer);
  if you are doing both, keep them as separate commits.
