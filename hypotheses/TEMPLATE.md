# Hypothesis <id>

Status: DRAFT (not approved; nothing may be run until the owner approves this file)

## Economic reason
Why should this make money? Who is on the other side and why do they lose? One paragraph.

## Exact rules
- Instrument, session, bar size.
- Features (each with the data it uses; state "day t uses data through day t-1" explicitly).
- Entry condition, entry fill rule (e.g. next 5-minute bar open).
- Stop, target, trailing/breakeven rule, time exit, tie-break when stop and target fall in one bar.
- Skip rules.

## Parameters
| name | value | why this value | range to examine in walk-forward |
|---|---|---|---|

## Data
- Test set: <table>, <from> .. <to>. Must not overlap data listed as consumed in `ledger.md` for this family.
- Cost model: <points round trip>.
- Walk-forward: <IS months> / <OOS months>.

## Bar to clear
- Standard gates (strategies/backtest.py `--gates`) plus the ledger's rising bar:
  variants already tried in this family = <n>, so OOS CI lower bound must exceed <0.02 x n> R.

## Pre-registered slices (optional)
Slices that will be reported, Holm-adjusted. None becomes a filter.

## Approval
- Owner: [ ] approved on <date>
