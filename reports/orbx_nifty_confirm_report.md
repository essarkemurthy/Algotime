# orbx_nifty_confirm backtest  2022-01-01 -> 2026-11-25  (generated 2026-11-26 12:04 IST, commit 2d71f38)
- ledger rising bar: OOS CI lower bound must exceed 0.02 R

- 1-minute rows: 457,431; valid sessions (>= 70 five-minute bars, weekdays): 1192 (2022-01-03 .. 2026-11-11); sessions with features: 1178
- params: bar_minutes=5, or_minutes=15, session_open=09:15:00, signal_start=09:30:00, signal_end=11:00:00, time_exit=15:15:00, atr_period=14, adx_period=14, rsi_period=14, adx_min=20.0, rsi_line=50.0, stop_atr_cap=0.5, target_r=1.5, be_trigger_r=1.0, cost_points=3.0, min_session_bars=70, exclude_weekends=True

## Day-filter funnel and data sanity
| step | sessions |
|---|---|
| sessions in 1m data | 1200 |
| - weekend special sessions | 7 |
| - fewer than 70 bars of 5 min | 2 |
| = valid sessions | 1192 |
| - no features (warm-up) | 14 |
| = evaluable sessions | 1178 |
| - skip no_opening_range | 0 |
| - skip no_breakout | 102 |
| - skip adx_undefined | 0 |
| - skip adx_below_min | 94 |
| - skip rsi_wrong_side | 76 |
| - skip no_next_bar | 0 |
| - skip no_features | 14 |
| = trades taken | 906 |

- survivors of every filter == trades: **NO** (892 vs 906)
- duplicate 1-minute timestamps: 0
- valid sessions whose first 5m bar is not 09:15: 0
- weekend special sessions excluded: 7  ['2023-11-12', '2024-01-20', '2024-03-02', '2024-05-18', '2025-02-01', '2026-02-01', '2026-11-08']
- weekday sessions excluded for < 70 five-minute bars: 2  ['2022-03-07', '2024-11-01']
- trades by year: {2022: 170, 2023: 192, 2024: 189, 2025: 198, 2026: 157}

## Baseline (default params) and cost sensitivity
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| cost 0 pts | 906 | 0.020 | 41.6% | 18.2 | 31.1 | 1.04 | 1.7 |
| cost 3 pts | 906 | -0.027 | 41.1% | -24.4 | 41.9 | 0.94 | 1.7 |
| cost 6 pts | 906 | -0.074 | 40.6% | -67.1 | 72.5 | 0.85 | 1.7 |
| cost 10 pts | 906 | -0.137 | 40.3% | -123.9 | 128.5 | 0.75 | 1.7 |

Skips: adx_below_min=94, no_breakout=102, no_features=14, rsi_wrong_side=76; signal days=906 of 1192

## By year (net 3 pts; descriptive, see slice table for significance)
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| 2022 | 170 | 0.020 | 43.5% | 3.4 | 8.0 | 1.05 | 0.6 |
| 2023 | 192 | -0.194 | 34.4% | -37.3 | 41.9 | 0.66 | -7.0 |
| 2024 | 189 | 0.075 | 42.3% | 14.2 | 8.2 | 1.17 | 13.1 |
| 2025 | 198 | 0.019 | 42.9% | 3.9 | 8.2 | 1.04 | 1.9 |
| 2026 | 157 | -0.055 | 42.7% | -8.6 | 21.1 | 0.89 | -0.3 |

## Exit reasons (net 3 pts; conditioned on outcome, descriptive only)
| reason | n | avg R |
|---|---|---|
| stop | 385 | -1.049 |
| time | 225 | 0.293 |
| target | 219 | 1.450 |
| be_stop | 77 | -0.054 |

Target and stop buckets are positive/negative by construction and the time-exit bucket is selected on having avoided both; none of these is evidence for a variant.

## Parameter grid (full sample, net 3 pts; for robustness only, not selection)
- cells: 8; positive avg R: 2 (25%); grid = {'or_minutes': (15, 30), 'adx_min': (20.0, 25.0), 'rsi_line': (50.0, 55.0)}
| params | n | avg R | total R | max DD R |
|---|---|---|---|---|
| or_minutes=30 adx_min=25.0 rsi_line=55.0 | 640 | 0.014 | 8.9 | 14.7 |
| or_minutes=30 adx_min=25.0 rsi_line=50.0 | 629 | 0.013 | 8.3 | 13.7 |
| or_minutes=30 adx_min=20.0 rsi_line=55.0 | 787 | -0.001 | -0.7 | 21.5 |
| or_minutes=30 adx_min=20.0 rsi_line=50.0 | 787 | -0.001 | -1.0 | 20.9 |
| or_minutes=15 adx_min=25.0 rsi_line=55.0 | 758 | -0.011 | -8.7 | 26.0 |
| or_minutes=15 adx_min=25.0 rsi_line=50.0 | 748 | -0.017 | -13.0 | 29.0 |
| or_minutes=15 adx_min=20.0 rsi_line=55.0 | 903 | -0.021 | -19.0 | 34.2 |
| or_minutes=15 adx_min=20.0 rsi_line=50.0 | 906 | -0.027 | -24.4 | 41.9 |

## Walk-forward (12m in-sample / 3m out-of-sample, step 3m)
  WF 2022-01-01..2023-01-01 -> OOS to 2023-04-01: IS n=147 avgR=0.062 | OOS n=42 avgR=0.068 | or_minutes=30 adx_min=20.0 rsi_line=55.0
  WF 2022-04-01..2023-04-01 -> OOS to 2023-07-01: IS n=132 avgR=0.065 | OOS n=33 avgR=-0.075 | or_minutes=30 adx_min=25.0 rsi_line=55.0
  WF 2022-07-01..2023-07-01 -> OOS to 2023-10-01: IS n=162 avgR=0.063 | OOS n=46 avgR=-0.170 | or_minutes=30 adx_min=20.0 rsi_line=55.0
  WF 2022-10-01..2023-10-01 -> OOS to 2024-01-01: IS n=133 avgR=0.027 | OOS n=31 avgR=0.054 | or_minutes=30 adx_min=25.0 rsi_line=55.0
  WF 2023-01-01..2024-01-01 -> OOS to 2024-04-01: IS n=131 avgR=0.000 | OOS n=35 avgR=0.193 | or_minutes=30 adx_min=25.0 rsi_line=55.0
  WF 2023-04-01..2024-04-01 -> OOS to 2024-07-01: IS n=151 avgR=0.047 | OOS n=36 avgR=-0.203 | or_minutes=15 adx_min=25.0 rsi_line=55.0
  WF 2023-07-01..2024-07-01 -> OOS to 2024-10-01: IS n=130 avgR=0.035 | OOS n=31 avgR=0.039 | or_minutes=30 adx_min=25.0 rsi_line=55.0
  WF 2023-10-01..2024-10-01 -> OOS to 2025-01-01: IS n=126 avgR=0.083 | OOS n=31 avgR=0.044 | or_minutes=30 adx_min=25.0 rsi_line=50.0
  WF 2024-01-01..2025-01-01 -> OOS to 2025-04-01: IS n=125 avgR=0.094 | OOS n=38 avgR=-0.025 | or_minutes=30 adx_min=25.0 rsi_line=50.0
  WF 2024-04-01..2025-04-01 -> OOS to 2025-07-01: IS n=197 avgR=0.038 | OOS n=44 avgR=0.095 | or_minutes=15 adx_min=20.0 rsi_line=50.0
  WF 2024-07-01..2025-07-01 -> OOS to 2025-10-01: IS n=152 avgR=0.074 | OOS n=39 avgR=-0.164 | or_minutes=15 adx_min=25.0 rsi_line=50.0
  WF 2024-10-01..2025-10-01 -> OOS to 2026-01-01: IS n=157 avgR=0.072 | OOS n=41 avgR=0.164 | or_minutes=15 adx_min=25.0 rsi_line=55.0
  WF 2025-01-01..2026-01-01 -> OOS to 2026-04-01: IS n=159 avgR=0.087 | OOS n=38 avgR=0.141 | or_minutes=15 adx_min=25.0 rsi_line=50.0
  WF 2025-04-01..2026-04-01 -> OOS to 2026-07-01: IS n=158 avgR=0.095 | OOS n=45 avgR=-0.186 | or_minutes=15 adx_min=25.0 rsi_line=55.0
  WF 2025-07-01..2026-07-01 -> OOS to 2026-10-01: IS n=161 avgR=0.012 | OOS n=40 avgR=-0.243 | or_minutes=15 adx_min=25.0 rsi_line=50.0
  WF 2025-10-01..2026-10-01 -> OOS to 2027-01-01: IS n=136 avgR=0.024 | OOS n=18 avgR=0.117 | or_minutes=30 adx_min=25.0 rsi_line=50.0

| IS from | IS to | OOS to | IS n | IS avg R | OOS n | OOS avg R | OOS total R | params |
|---|---|---|---|---|---|---|---|---|
| 2022-01-01 | 2023-01-01 | 2023-04-01 | 147 | 0.062 | 42 | 0.068 | 2.9 | or_minutes=30 adx_min=20.0 rsi_line=55.0 |
| 2022-04-01 | 2023-04-01 | 2023-07-01 | 132 | 0.065 | 33 | -0.075 | -2.5 | or_minutes=30 adx_min=25.0 rsi_line=55.0 |
| 2022-07-01 | 2023-07-01 | 2023-10-01 | 162 | 0.063 | 46 | -0.170 | -7.8 | or_minutes=30 adx_min=20.0 rsi_line=55.0 |
| 2022-10-01 | 2023-10-01 | 2024-01-01 | 133 | 0.027 | 31 | 0.054 | 1.7 | or_minutes=30 adx_min=25.0 rsi_line=55.0 |
| 2023-01-01 | 2024-01-01 | 2024-04-01 | 131 | 0.000 | 35 | 0.193 | 6.8 | or_minutes=30 adx_min=25.0 rsi_line=55.0 |
| 2023-04-01 | 2024-04-01 | 2024-07-01 | 151 | 0.047 | 36 | -0.203 | -7.3 | or_minutes=15 adx_min=25.0 rsi_line=55.0 |
| 2023-07-01 | 2024-07-01 | 2024-10-01 | 130 | 0.035 | 31 | 0.039 | 1.2 | or_minutes=30 adx_min=25.0 rsi_line=55.0 |
| 2023-10-01 | 2024-10-01 | 2025-01-01 | 126 | 0.083 | 31 | 0.044 | 1.4 | or_minutes=30 adx_min=25.0 rsi_line=50.0 |
| 2024-01-01 | 2025-01-01 | 2025-04-01 | 125 | 0.094 | 38 | -0.025 | -1.0 | or_minutes=30 adx_min=25.0 rsi_line=50.0 |
| 2024-04-01 | 2025-04-01 | 2025-07-01 | 197 | 0.038 | 44 | 0.095 | 4.2 | or_minutes=15 adx_min=20.0 rsi_line=50.0 |
| 2024-07-01 | 2025-07-01 | 2025-10-01 | 152 | 0.074 | 39 | -0.164 | -6.4 | or_minutes=15 adx_min=25.0 rsi_line=50.0 |
| 2024-10-01 | 2025-10-01 | 2026-01-01 | 157 | 0.072 | 41 | 0.164 | 6.7 | or_minutes=15 adx_min=25.0 rsi_line=55.0 |
| 2025-01-01 | 2026-01-01 | 2026-04-01 | 159 | 0.087 | 38 | 0.141 | 5.4 | or_minutes=15 adx_min=25.0 rsi_line=50.0 |
| 2025-04-01 | 2026-04-01 | 2026-07-01 | 158 | 0.095 | 45 | -0.186 | -8.4 | or_minutes=15 adx_min=25.0 rsi_line=55.0 |
| 2025-07-01 | 2026-07-01 | 2026-10-01 | 161 | 0.012 | 40 | -0.243 | -9.7 | or_minutes=15 adx_min=25.0 rsi_line=50.0 |
| 2025-10-01 | 2026-10-01 | 2027-01-01 | 136 | 0.024 | 18 | 0.117 | 2.1 | or_minutes=30 adx_min=25.0 rsi_line=50.0 |

### Pooled out-of-sample
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| OOS cost 0 pts | 588 | 0.024 | 44.6% | 14.1 | 21.1 | 1.06 | 2.6 |
| OOS cost 3 pts | 588 | -0.018 | 44.0% | -10.8 | 23.9 | 0.96 | 2.6 |
| OOS cost 6 pts | 588 | -0.061 | 43.5% | -35.8 | 44.8 | 0.87 | 2.6 |
| OOS cost 10 pts | 588 | -0.118 | 42.3% | -69.2 | 76.4 | 0.77 | 2.6 |
- bootstrap 95% CI of mean R (net 3 pts): [-0.100, 0.065]
- distinct parameter sets chosen across windows: 6 of 16

## Like-for-like: fixed spec params vs walk-forward, same OOS windows (net 3 pts)
- OOS windows: 949 sessions, 2023-01-02 .. 2026-11-11
| set | n | avg R | 95% CI | win % | total R | max DD R |
|---|---|---|---|---|---|---|
| fixed spec params | 736 | -0.038 | [-0.112, 0.034] | 40.5% | -27.9 | 41.9 |
| walk-forward (re-chosen) | 588 | -0.018 | [-0.100, 0.065] | 44.0% | -10.8 | 23.9 |
- difference walk-forward minus fixed: 0.019R, 95% CI [-0.089, 0.130]
- parameter selection added measurable value: **no** (CI of the difference includes zero)

## Slice analysis (exploratory; 28 slices examined, Holm-adjusted; full sample, net 3 pts)
| dimension | slice | n | mean R | rest mean R | p raw | p Holm | significant |
|---|---|---|---|---|---|---|---|
| year | 2022 | 170 | 0.020 | -0.038 | 0.509 | 1.000 | no |
| year | 2023 | 192 | -0.194 | 0.018 | 0.011 | 0.320 | no |
| year | 2024 | 189 | 0.075 | -0.054 | 0.143 | 1.000 | no |
| year | 2025 | 198 | 0.019 | -0.040 | 0.475 | 1.000 | no |
| year | 2026 | 157 | -0.055 | -0.021 | 0.706 | 1.000 | no |
| side | LONG | 461 | -0.036 | -0.018 | 0.797 | 1.000 | no |
| side | SHORT | 445 | -0.018 | -0.036 | 0.797 | 1.000 | no |
| adx_at_entry | 20-25 | 304 | -0.012 | -0.034 | 0.769 | 1.000 | no |
| adx_at_entry | 25-30 | 197 | -0.003 | -0.034 | 0.708 | 1.000 | no |
| adx_at_entry | 30+ | 405 | -0.050 | -0.009 | 0.552 | 1.000 | no |
| rsi_at_entry | 40-50 | 158 | -0.084 | -0.015 | 0.463 | 1.000 | no |
| rsi_at_entry | 50-60 | 132 | -0.021 | -0.028 | 0.946 | 1.000 | no |
| rsi_at_entry | <40 | 287 | 0.018 | -0.048 | 0.370 | 1.000 | no |
| rsi_at_entry | >60 | 329 | -0.041 | -0.019 | 0.750 | 1.000 | no |
| or_atr_tercile | T1 | 302 | -0.058 | -0.012 | 0.537 | 1.000 | no |
| or_atr_tercile | T2 | 302 | 0.040 | -0.060 | 0.169 | 1.000 | no |
| or_atr_tercile | T3 | 302 | -0.063 | -0.009 | 0.453 | 1.000 | no |
| gap_vs_side | against | 379 | -0.023 | -0.030 | 0.931 | 1.000 | no |
| gap_vs_side | with | 527 | -0.030 | -0.023 | 0.931 | 1.000 | no |
| weekday | Fri | 180 | 0.102 | -0.059 | 0.069 | 1.000 | no |
| weekday | Mon | 177 | -0.026 | -0.027 | 0.992 | 1.000 | no |
| weekday | Thu | 185 | -0.061 | -0.018 | 0.623 | 1.000 | no |
| weekday | Tue | 184 | -0.109 | -0.006 | 0.211 | 1.000 | no |
| weekday | Wed | 180 | -0.037 | -0.025 | 0.890 | 1.000 | no |
| expiry_day | expiry | 193 | -0.043 | -0.023 | 0.811 | 1.000 | no |
| expiry_day | other | 713 | -0.023 | -0.043 | 0.811 | 1.000 | no |
| signal_hour | first_hour | 733 | -0.008 | -0.106 | 0.253 | 1.000 | no |
| signal_hour | later | 173 | -0.106 | -0.008 | 0.253 | 1.000 | no |
- **No slice is significant after multiplicity** (28 looks). Weekday, side, year and hour differences are consistent with noise. No slice may be used as a filter in this strategy.

## Regime check: rolling 50-trade hit rate vs a stationary binomial
- trades 906, hit rate 41.1%, overlapping windows 857
- observed rolling range: 24% .. 56%
- simulated 95% band for the minimum: 18% .. 30%; for the maximum: 52% .. 66%
- observed range outside the band: **no**. No regime change is supported: the swings are what a constant hit rate produces.

## Go-live gates
| gate | result | detail |
|---|---|---|
| 1 walk-forward OOS net 3 pts: n>=100, avg R>=0.10, CI low>0.02 | **FAIL** | n=588 avgR=-0.018 CI95=[-0.100, 0.065] |
| 2 robustness: avg R>0 at 6 pts; >=60% grid cells positive; stable params | **FAIL** | avgR@6pts=-0.061 grid positive=2/8 (25%) distinct WF param sets=6/16 |
| 3 OOS max drawdown <= 12R | **FAIL** | maxDD=23.9R = Rs 47,815 = 31.9% of Rs 150,000 |
| 4 paper phase: >=30 sessions with alerts + journal, realised vs backtest R within tolerance | **PENDING** | PENDING - paper phase not started |
| 5 live one lot only for >=20 sessions before any size change | **PENDING** | PENDING - after gate 4 |

## Verdict: **FAIL**
- like-for-like: fixed -0.038R vs walk-forward -0.018R, difference CI [-0.089, 0.130]; selection added value: no
- slices significant after multiplicity: 0 of 28
- regime change supported: no
- data 2022-01-01 .. 2026-11-25 is CONSUMED for this strategy family (see hypotheses/ledger.md)

- wrote reports/orbx_nifty_confirm_trades.csv (906 rows), reports/orbx_nifty_confirm_oos_trades.csv (588 rows); elapsed 12s
