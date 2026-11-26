# Hypothesis ORBX-15 — NIFTY 15-minute opening-range breakout confirmed by ADX and RSI

Status: APPROVED 2026-11-26 — data fetch and build in progress; verdict pending

Family: NIFTY opening-range breakout. Variants tried in family: 1 (ORB-CPR-15, FAIL, 2022-2026).
So the ledger's rising bar applies: OOS CI lower bound must exceed 0 + 0.02 R × 1 = **0.02 R**.
Source: owner, 2026-11-26 ("consider strategies like ORB, ADX and RSI") after learning that the
engine's VWAP on the index is a volume-less running average.

## Economic reason
An opening-range breakout bets that the first 15 minutes set the day's auction range and that a
close outside it, when the move has momentum behind it, continues. The repo's cash backtests found
ORB positive on stocks only when breakout volume confirmed it (PF 1.05-1.06 before costs); the index
has no volume, so the gate that made ORB tolerable on stocks is vacuous on NIFTY (the detector's
`volume >= 1.5 × average` reads `0 >= 0` and passes). This hypothesis replaces volume with two
volume-free trend measures: ADX(14) says a trend exists, RSI(14) says it points the breakout's way.
The other side is the range trader fading the first move; the claim is that they lose on the subset
of days where ADX and RSI already agree with the break.

The prior is weak. ORB-CPR-15 (same breakout, filtered by CPR width, gap and OR size) returned
avg R ≈ 0 net of 3 points on 1,195 NIFTY sessions. ADX/RSI are the most common retail filters on
this setup and anything common is likely arbitraged; the test is whether they carry information the
CPR/gap/OR filters did not.

## Exact rules
Identical to `strategies/orb_cpr_nifty.py` except for the filter set, so the comparison isolates
the filters:
- Instrument: NIFTY 50 index, 5-minute bars from `nifty_1m` (sessions with ≥ 70 bars; special
  sessions dropped). Traded in the engine as the ATM option (see Deviations).
- Opening range = high/low of 09:15-09:30 (3 five-minute bars).
- ATR(14) Wilder on daily bars as of the previous close (sizing of stop cap only).
- ADX(14) and RSI(14), Wilder, on the continuous 5-minute series across sessions (so 09:35 has
  values). Bar k uses bars through k.
- LONG: a 5-minute bar closes above OR-high, bar close in (09:30, 11:00], ADX ≥ 20, RSI ≥ 50.
  SHORT: close below OR-low, same window, ADX ≥ 20, RSI ≤ 50. No volume condition.
- One signal per day (first that qualifies). Entry = open of the next 5-minute bar.
- Stop distance S = min(OR range, 0.5 ATR); stop = entry ∓ S. Target = entry ± 1.5 S.
  After +1 S the stop moves to entry, effective from the next bar. Stop and target in one bar ⇒ stop.
- Time exit at the open of the 15:15 bar.
- R = points / S, net of costs. Skip rules: none; ADX/RSI buckets are slices.

## Parameters
| name | value | why this value | range to examine in walk-forward (robustness only) |
|---|---|---|---|
| OR length | 15 min | engine's `orb_bars`; ORB-CPR used the same | 15, 30 |
| ADX threshold | 20 | textbook trend/no-trend line | 20, 25 |
| RSI side line | 50 | engine's `vwap_trend_rsi` default | 50, 55 |
| stop cap, target, BE, exit | 0.5 ATR, 1.5 S, 1 S, 15:15 | copied from ORB-CPR-15 so only filters change | fixed |
| signal window | (09:30, 11:00] | ORB-CPR-15 | fixed |

Grid = 2 × 2 × 2 = 8 cells for gate 2 only. Nothing is picked from it.

## Data
- Test set: `nifty_1m` 2015-01-05 .. 2021-12-31 (same fetch as PCL-15; both are new families on that
  range, neither may be tuned on the other's results). Daily ATR warm-up from `candles` 1d.
- Confirmation set: 2022-01-03 .. 2026-11-25, reported but not gating (consumed by ORB-CPR-15).
- Cost model: 3 points round trip base, 6 points robust (`strategies/backtest.py`).
- Walk-forward: 12 months in-sample / 3 months out-of-sample, rolling.

## Bar to clear
1. Walk-forward OOS 2015-2021, base costs: n ≥ 100, mean R ≥ 0.10, bootstrap 95% CI lower bound
   > **0.02 R** (variant 2 of the family).
2. Robustness: mean R > 0 at 6 points; ≥ 60% of 8 grid cells positive; stable walk-forward picks.
3. OOS max drawdown ≤ 12 R.
4. Paper phase: ≥ 30 sessions, signals-only alerts with journal, realised vs backtest R in tolerance.
5. Live: one lot ≥ 20 sessions before any size change.

On FAIL the family is frozen at variants = 2. No ADX, RSI, OR-length or window variant may be
validated on 2015-2026 NIFTY data afterwards.

## Pre-registered slices (reported, Holm-adjusted, never filters)
year; side; ADX at entry (20-25, 25-30, > 30); RSI at entry (50-60, > 60 and mirror); OR size in ATR
terciles; gap sign vs side; day-of-week; expiry day; first-hour vs later signal.

## Deviations and engine notes
- R is measured on index points, as in ORB-CPR-15. The engine would buy the ATM option; today it
  manages options with a 30% / 50% premium bracket, which has nothing to do with the index-level
  stop and target here. Before gate 4 the options path needs an index-level exit mapped onto the
  contract (exit the option when the index hits S or 1.5 S), not a premium percentage.
- ADX does not exist in `signals/` yet; it is added as a pure Wilder implementation with a unit test
  against a hand-computed series, shared by the backtest and any later live detector.
- The detector-level `vol_mult` gate stays untouched in `signals/detectors.py`; this file records
  that it is vacuous on indices so nobody mistakes an index ORB signal for a volume-confirmed one.

## Build plan after approval
1. Fetch 2015-2021 (shared with PCL-15) and record the actual coverage here.
2. `strategies/indicators_tf.py`: Wilder ADX/RSI on bar sequences + tests.
3. `strategies/orbx_nifty.py` on the ORB-CPR module's `Bar`/`DayState` pattern; backtest harness
   takes the module as an argument; run `--gates` on 2015-2021, then the 2022-2026 confirmation.
4. Verdict file, ledger row, this file marked PASS or FAIL.

## Approval
- Owner: [x] approved on 2026-11-26 (owner's "yes go ahead" in chat; ticked by the agent on that instruction)
