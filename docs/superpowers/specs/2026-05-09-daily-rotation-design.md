# Daily Rotation Strategy Design

## Goal

Upgrade the ETF rotation strategy from weekly top-N switching to a daily-checked rotation model that:

- allows daily rebalancing decisions
- keeps total exposure at or below 85%
- holds a broad book of up to 8-10 ETFs instead of 1-2
- limits turnover by changing at most 2 symbols per trading day
- uses dynamic weights instead of equal weights

## Strategy Rules

- Compute factor scores daily using the existing momentum-plus-trend filter.
- Rank eligible ETFs by factor score each day.
- Build a target candidate pool from the strongest ranked symbols.
- Keep existing holdings when they remain competitive.
- Replace at most 2 symbols per day with stronger candidates.
- Cap total holdings at 10 symbols and target 8 symbols when enough candidates exist.
- Allocate weights dynamically from normalized positive factor scores.
- Scale the final portfolio so total exposure does not exceed 85%.

## Weighting

- Only positive, eligible scores receive weight.
- Selected symbols receive weight proportional to their factor score.
- If fewer than 8 symbols are eligible, hold fewer symbols rather than forcing weak names in.
- If all selected scores are non-positive, move to 0 exposure.

## Turnover Control

- Daily ranking is allowed.
- Symbol entry/exit changes are capped at 2 per day.
- Symbols already in the portfolio are preferred when they still appear in the competitive candidate set.

## Implementation

- Extend strategy configuration with:
  - target holdings count
  - max holdings count
  - max symbol changes per day
- Update `build_target_weights()` to maintain a rolling selected set instead of full replacement on each rebalance date.
- Keep downstream backtest, metrics, orders, and plotting contracts unchanged.

## Testing

- Add unit tests for:
  - dynamic weights summing to max exposure
  - no more than 2 symbol changes per day
  - daily rebalance behavior without weekly gating
  - carrying prior holdings forward when not replaced
