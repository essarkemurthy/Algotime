# Hypothesis PCL-15 — NIFTY intraday pivot / Camarilla level signals (15-minute)

Status: DRAFT (not approved; nothing may be run until the owner approves this file)

Family: NIFTY intraday level system (floor pivots + CPR + Camarilla). Variants tried in family: 0.
Source: owner-supplied spec "Intraday Nifty Level Signals" (pasted 2026-11-26). This file pins down
every choice the spec leaves open; where it deviates from the spec it says so in "Deviations".

## Economic reason
Floor pivots, CPR and Camarilla levels are computed from the previous day's OHLC by a large share of
Indian index intraday traders and are drawn on broker charts by default. The claim is that this
shared attention makes them act as self-fulfilling reference prices: on trend days (large gap or
wide opening range) a 15-minute close through R1/S1 or a round number marks the point where
range-bound traders are stopped out and trend followers add, so price continues to the next level;
on range days (small gap, narrow opening range) a failed test of an edge level marks exhaustion and
price returns toward the central pivot. The other side is the trader who fades a confirmed break on
a trend day or chases a test on a range day. The day-type filter is what is supposed to tell the two
apart; without it the two rules are opposite bets on the same levels and should net to zero.

Prior in this repo: ORB-CPR-15 (CPR width + gap + opening-range filters, 2022-2026) FAILED all three
backtest gates with avg R ≈ 0 net of 3 points. This family shares the gap and opening-range filters,
so its prior is weak and the burden of proof is on the data.

## Exact rules
- Instrument: signals on the NIFTY 50 index; traded as the near-month NIFTY future, 1 lot = 65
  (Jan-2026 series). The backtest uses index 1-minute bars (`nifty_1m`) as the price series; see
  Deviations for the futures basis.
- Session: every NSE trading day with ≥ 70 five-minute bars (special/partial sessions dropped, as in
  `strategies/orb_cpr_nifty.py`). Bar size: 15 minutes anchored at 09:15 (25 bars; the last opens 15:15).
- Previous-day features (day t uses day t-1's O/H/L/C only; the previous *valid* session):
  - P = (H+L+C)/3, R1 = 2P-L, S1 = 2P-H, BC = (H+L)/2, TC = 2P-BC (CPR top = max(BC,TC), bottom = min).
  - Camarilla: H3 = C + 1.1(H-L)/4, H4 = C + 1.1(H-L)/2, L3 = C - 1.1(H-L)/4, L4 = C - 1.1(H-L)/2.
  - ATR(14), Wilder smoothing, on daily bars, as of day t-1's close.
  - Round levels: every multiple of 100 index points inside [L4 - ATR, H4 + ATR].
  - Level ladder for day t = sorted set {L4, L3, S1, CPR bottom, P, CPR top, R1, H3, H4} ∪ round
    levels. Levels closer than 0.05 ATR to each other are merged (keep the lower).
  - The ladder is fixed for the day. "Targets updated each bar" in the spec therefore has no effect
    (see Deviations).
- Intraday indicators on the continuous 15-minute series (not reset daily, so the first bars of the
  day have values): ADX(14) Wilder, RSI(14) Wilder. Bar k's values use bars through bar k's close.
- Day type, decided once at the close of the first 15-minute bar (09:30) and never revised:
  TREND if |open - prev close| > 1.0 ATR or (first-15m high - low) > 0.20 ATR; else RANGE.
  Open = first 1-minute bar's open of the day.
- Directional bias at each 15-minute bar close:
  +1 if close > CPR top and ADX ≥ 20 and RSI > 50; -1 if close < CPR bottom and ADX ≥ 20 and
  RSI < 50; 0 otherwise.
- Entry signals, evaluated on 15-minute bar closes in (09:30, 14:30]; at most one open position;
  at most 2 entries per day; the second entry needs a new signal after the first trade has closed:
  - TREND day LONG: bar close > L for a break level L in {R1} ∪ round levels, previous bar close ≤ L,
    bias = +1. SHORT mirror: close < L for L in {S1} ∪ round levels, previous close ≥ L, bias = -1.
  - RANGE day LONG (failed test of a lower edge): for edge E in {S1, L3, CPR bottom}: bar low ≤ E,
    bar close > E, previous bar close > E, bias ≠ -1. SHORT mirror at E in {R1, H3, CPR top}: bar
    high ≥ E, close < E, previous close < E, bias ≠ +1.
  - Confirmation is the bar close itself (trend: close through the level with ADX ≥ 20 via the bias;
    range: close back inside). No extra buffer.
- Fill: open of the next 15-minute bar (entry, and every exit except intrabar stop/target hits).
- Initial stop (LONG): nearest ladder level strictly below entry, minus 0.15 ATR; SHORT mirror.
  Initial risk = |entry - stop|. Skip the signal if risk > 1.0 ATR (ladder gap) or risk < 0.10 ATR.
- Targets (LONG): T1 = nearest ladder level strictly above entry; T2 = the next ladder level above
  T1. Skip the signal if (T2 - entry) < 2 × risk (the spec's 2:1 reward/risk requirement) or T2 does
  not exist. SHORT mirror.
- Position = two equal half-units. Half 1 exits at T1, half 2 at T2.
- Trailing stop: when a bar's high (LONG) touches a ladder level above entry, the stop for what is
  still open moves to that level minus 0.15 ATR, effective from the next bar. Stops and targets are
  intrabar: hit when the bar's low ≤ stop or high ≥ target. Stop and target in one bar ⇒ stop first.
- Time exit: whatever is open exits at the open of the 15:00 bar.
- R for the trade = (points on half 1 + points on half 2) / 2 / initial risk, net of costs.
- Skip rules: none beyond the above. Day type, side and level type are reported as slices.

## Parameters
| name | value | why this value | range to examine in walk-forward (robustness only) |
|---|---|---|---|
| gap threshold | 1.0 ATR | spec | 0.75, 1.0 |
| first-15m range threshold | 0.20 ATR | spec | 0.15, 0.20, 0.25 |
| ADX threshold | 20 | spec says "ADX confirming"; 20 is the textbook trend/no-trend line | 20, 25 |
| RSI midline | 50 | spec says "RSI momentum"; 50 is the only non-arbitrary line | fixed |
| stop buffer | 0.15 ATR | spec | 0.10, 0.15, 0.20 |
| indicator periods | 14 | spec | fixed |
| round-level step | 100 points | common retail definition of "psychological level" | fixed |
| time exit | 15:00 | spec | fixed |
| max entries/day | 2 | spec ("1-2 lots", one position at a time) | fixed |

Grid = 2 × 3 × 2 × 3 = 36 cells, used for gate 2 only. Parameters are not picked from it.

## Data
- Test set: `nifty_1m`, 2015-01-05 .. 2021-12-31 (to be fetched; Breeze serves 1-minute NIFTY back
  to 2015-01-05 per the ledger's probe). Daily ATR warm-up from `candles` 1d (available from 2012).
  This range is not consumed by any family in `ledger.md`.
- Confirmation set: `nifty_1m` 2022-01-03 .. 2026-11-25, reported separately. It is CONSUMED by the
  ORB-CPR family, which shares this family's gap/opening-range filters, so it may not decide the
  gates; it is shown so a pass on 2015-2021 cannot hide a collapse in the modern regime.
- Fetch budget: ≈ 1,750 sessions × 1 call = 1,750 calls (one day's quota is 4,500); must run inside
  the app's Breeze session or with the app stopped.
- Cost model: 3 points round trip per half-unit base, 6 points robust (same as `strategies/backtest.py`),
  converted to R by the trade's initial risk. Futures basis is ignored (see Deviations).
- Walk-forward: 12 months in-sample / 3 months out-of-sample, rolling, as in `strategies/backtest.py`.

## Bar to clear
Standard gates from `strategies/backtest.py --gates`, variants already tried = 0:
1. Walk-forward OOS on 2015-2021, base costs: n ≥ 100 trades, mean R ≥ 0.10, bootstrap 95% CI lower
   bound > 0.
2. Robustness: mean R > 0 at 6 points; ≥ 60% of the 36 grid cells positive; walk-forward picks stable
   parameters.
3. OOS max drawdown ≤ 12 R.
4. Paper phase: ≥ 30 sessions of signals-only alerts with a journal, realised R within tolerance.
5. Live: one lot for ≥ 20 sessions before any size change, only after the account can carry a NIFTY
   futures lot (≈ ₹1.3-1.5 lakh margin; usable capital today ≈ ₹7,900, so this gate is far away).

If any gate fails on 2015-2021 the family is frozen at variants = 1 and this file records FAIL. No
threshold, level-set, buffer or time variant may then be validated on 2015-2021 or 2022-2026 data.

## Pre-registered slices (reported, Holm-adjusted, never filters)
year; day type (trend/range); side; entry level type (pivot, Camarilla, round); bias at entry (+1/0/-1);
day-of-week; expiry day (weekly from 2019-02; monthly before); gap sign vs trade side; first-15m range
tercile.

## Sizing (not part of the hypothesis; recorded because the spec asks for it)
Lots = min(2, floor(0.5% × capital / (initial risk × 65))). With risk typically 0.3-0.6 ATR
(≈ 60-150 points today) one lot needs capital of ₹8-20 lakh at 0.5% risk. The backtest reports R per
unit; lot sizing only matters at gate 5. "Adjusting strikes to fit" (options as the vehicle) is out of
scope: level-based stops and targets in index points do not map onto an option's P&L.

## Deviations from the spec
- Price series: index spot, not the near-month future. Levels and signals in live use would come from
  the same series the trader watches; the futures basis (≈ 0.3-0.8% premium, slowly varying) shifts
  every level and price by about the same amount and so leaves breaks, tests and distances intact.
  Breeze has no multi-year futures history in this repo (`futures_candles` starts 2026-04).
- "Targets updated each bar based on recalculated levels": the levels here are fixed for the day, so
  targets are fixed. Intraday-recomputed pivots were not specified and are not used.
- "Target 1 hit" and "Target 2 hit" as separate exits are implemented as two half-units.
- Bias, ADX and RSI are on 15-minute bars; the spec gives no bar size for ADX/RSI.
- Entries are only on bar closes (no tick-level breaks) because the backtest has 1-minute data and the
  spec evaluates "each 15 min bar".

## Build plan after approval (in this order; nothing before the tick)
1. Fetch 2015-01-05 .. 2021-12-31 into `nifty_1m` (extend `scripts/fetch_nifty_history.py --from`);
   record the actual first date and the missing sessions in this file.
2. `strategies/level_signals_nifty.py`: pure functions on the `Bar`/`DayState` pattern of the ORB-CPR
   module (features, ladder, day type, bias, signal, `simulate_trade`), with unit tests for every rule
   above (a synthetic day per rule).
3. Make `strategies/backtest.py` take the strategy module as an argument (today it imports ORB-CPR
   directly) and run `--gates` on 2015-2021, then the 2022-2026 confirmation report.
4. Verdict file under `reports/`, ledger row updated, this file marked PASS or FAIL.
5. Only on PASS: signals-only runner (alerts + journal), gate 4.

## Approval
- Owner: [ ] approved on <date>
