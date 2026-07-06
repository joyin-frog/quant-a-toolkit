"""迁移调仓：从记账账户的【现有持仓】出发，生成到策略目标组合的 卖出/保留/买入 清单。

设计口径：
- 只处理 A 股主板个股（60/00 开头）；ETF/场内基金用户自己管理，忽略并在 note 里披露。
- locked = 用户锁仓的票：策略必须保留（哪怕它想卖），并占用一个持仓名额。
- 预算 = 账户内个股市值 + 记账现金；等权到目标只数。已保留的票不加不减（最小化换手），
  新买的票按"目标权重-0"整手买入，卖出的票全清。
- 这是【过渡建议清单】，不是历史回测——历史绩效由记账系统的 TWR/对比回测负责，
  你不听建议（锁仓/不卖）造成的差异会体现在"对回测损耗"里，而不是被隐藏。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_a.cache import cache_exists, load_cached_bars
from quant_a.config import LOT_SIZE


def _is_stock(code: str) -> bool:
    return len(code) == 6 and code.startswith(("60", "00"))


def account_stock_positions(account: str) -> tuple[dict[str, int], float, list[str]]:
    """读记账账户：返回 (个股持仓 {code: shares}, 记账现金, 被忽略的非个股代码列表)。"""
    from quant_a.portfolio_db import current_positions, reconstruct

    positions = current_positions(account)
    ignored: list[str] = []
    stocks: dict[str, int] = {}
    if not positions.empty:
        for _, row in positions.iterrows():
            code = str(row["code"]).zfill(6)
            if _is_stock(code):
                stocks[code] = int(row["shares"])
            else:
                ignored.append(code)
    rc = reconstruct(account)
    cash = float(rc["cash"].iloc[-1]) if rc is not None else 0.0
    return stocks, cash, ignored


def latest_price(code: str) -> float:
    if not cache_exists(code):
        return float("nan")
    bars = load_cached_bars(code)
    return float(bars["close"].iloc[-1])


def build_transition(
    account: str,
    target: list[str],
    names: dict[str, str],
    locked: list[str] | None = None,
    lot: int = LOT_SIZE,
) -> dict[str, object]:
    """现有持仓 → 目标组合的过渡清单。返回 {'orders': DataFrame, 'summary': dict}。"""
    locked = [c.zfill(6) for c in (locked or [])]
    held, cash, ignored = account_stock_positions(account)
    warnings: list[str] = []
    if ignored:
        warnings.append(f"账户中的非个股({'、'.join(ignored)})不参与迁移，请自行管理。")

    prices = {c: latest_price(c) for c in set(held) | set(target)}
    stale = [c for c, p in prices.items() if not np.isfinite(p)]
    if stale:
        warnings.append(f"以下代码无本地行情、按持有处理不动：{'、'.join(stale)}")

    equity = cash + sum(sh * prices[c] for c, sh in held.items() if np.isfinite(prices.get(c, float("nan"))))
    slots = max(1, len(target))
    per_slot = equity / slots

    rows: list[dict[str, object]] = []
    # 卖出：持有但不在目标里（锁仓票永不进卖出）
    for code, shares in sorted(held.items()):
        if code in target or code in locked or code in stale:
            continue
        px = prices[code]
        rows.append({
            "action": "卖出", "code": code, "name": names.get(code, ""),
            "shares": shares, "price": round(px, 2), "amount": round(shares * px, 0),
            "note": "不在目标组合",
        })
    # 保留：目标里已持有的（含锁仓），不加不减
    for code in target:
        if code in held:
            px = prices.get(code, float("nan"))
            rows.append({
                "action": "保留", "code": code, "name": names.get(code, ""),
                "shares": held[code], "price": round(px, 2) if np.isfinite(px) else None,
                "amount": round(held[code] * px, 0) if np.isfinite(px) else None,
                "note": "锁仓" if code in locked else "缓冲带/仍在目标",
            })
    # 买入：目标里没持有的，按每档预算整手买
    sell_proceeds = sum(r["amount"] for r in rows if r["action"] == "卖出")
    available = cash + sell_proceeds
    for code in target:
        if code in held:
            continue
        px = prices.get(code, float("nan"))
        if not np.isfinite(px) or px <= 0:
            warnings.append(f"{code} 无行情，无法给出买入手数")
            continue
        lots = int(min(per_slot, available) // (px * lot))
        if lots <= 0:
            warnings.append(f"{code} {names.get(code,'')} 预算不足一手（现价 {px:.2f}），跳过")
            continue
        cost = lots * lot * px
        available -= cost
        rows.append({
            "action": "买入", "code": code, "name": names.get(code, ""),
            "shares": lots * lot, "price": round(px, 2), "amount": round(cost, 0),
            "note": "新进目标组合",
        })

    order = {"卖出": 0, "保留": 1, "买入": 2}
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(by="action", key=lambda s: s.map(order)).reset_index(drop=True)
    summary = {
        "account": account,
        "equity": round(equity, 0),
        "cash_before": round(cash, 0),
        "cash_after": round(available, 0),
        "n_sell": int((frame["action"] == "卖出").sum()) if not frame.empty else 0,
        "n_keep": int((frame["action"] == "保留").sum()) if not frame.empty else 0,
        "n_buy": int((frame["action"] == "买入").sum()) if not frame.empty else 0,
        "locked": locked,
        "warnings": warnings,
    }
    return {"orders": frame, "summary": summary}
