# pcl_nifty_confirm backtest  2022-01-01 -> 2026-11-25  (generated 2026-11-26 12:04 IST, commit 2d71f38)

- 1-minute rows: 457,431; valid sessions (>= 23 five-minute bars, weekdays): 1192 (2022-01-03 .. 2026-11-11); sessions with features: 1178
- params: bar_minutes=15, session_open=09:15:00, signal_start=09:30:00, signal_end=14:30:00, time_exit=15:00:00, atr_period=14, adx_period=14, rsi_period=14, gap_atr=1.0, or_atr=0.2, adx_min=20.0, rsi_mid=50.0, buffer_atr=0.15, round_step=100, merge_atr=0.05, risk_min_atr=0.1, risk_max_atr=1.0, rr_min=2.0, max_entries=2, cost_points=3.0, min_session_bars=23, exclude_weekends=True

## Day-filter funnel and data sanity
| step | sessions |
|---|---|
| sessions in 1m data | 1200 |
| - weekend special sessions | 7 |
| - fewer than 23 bars of 15 min | 2 |
| = valid sessions | 1192 |
| - no features (warm-up) | 14 |
| = evaluable sessions | 1178 |
| - skip no_signal | 383 |
| - skip rr_too_low | 763 |
| - skip risk_out_of_band | 0 |
| - skip no_level_below | 0 |
| - skip no_t2 | 391 |
| - skip no_next_bar | 0 |
| - skip no_features | 14 |
| = sessions with at least one trade | 368 |
| = trades taken | 434 |

- survivors of every filter == trades: **yes** (368 vs 434)
- duplicate 1-minute timestamps: 0
- valid sessions whose first 5m bar is not 09:15: 0
- weekend special sessions excluded: 7  ['2023-11-12', '2024-01-20', '2024-03-02', '2024-05-18', '2025-02-01', '2026-02-01', '2026-11-08']
- weekday sessions excluded for < 23 five-minute bars: 2  ['2022-03-07', '2024-11-01']
- trades by year: {2022: 75, 2023: 72, 2024: 88, 2025: 107, 2026: 92}

## Baseline (default params) and cost sensitivity
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| cost 0 pts | 434 | 0.099 | 49.3% | 43.2 | 14.2 | 1.24 | 4.0 |
| cost 3 pts | 434 | 0.028 | 48.2% | 12.2 | 17.1 | 1.06 | 4.0 |
| cost 6 pts | 434 | -0.043 | 43.8% | -18.8 | 30.8 | 0.91 | 4.0 |
| cost 10 pts | 434 | -0.138 | 40.8% | -60.0 | 68.8 | 0.75 | 4.0 |

Skips: no_features=14, no_signal=383, no_t2=391, rr_too_low=763; signal days=434 of 1192

## By year (net 3 pts; descriptive, see slice table for significance)
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| 2022 | 75 | 0.017 | 45.3% | 1.3 | 15.6 | 1.04 | 4.4 |
| 2023 | 72 | 0.133 | 55.6% | 9.6 | 5.1 | 1.34 | 7.2 |
| 2024 | 88 | -0.018 | 45.5% | -1.6 | 10.9 | 0.96 | 0.8 |
| 2025 | 107 | 0.054 | 48.6% | 5.8 | 12.2 | 1.13 | 6.6 |
| 2026 | 92 | -0.032 | 46.7% | -2.9 | 17.1 | 0.93 | 1.2 |

## Exit reasons (net 3 pts; conditioned on outcome, descriptive only)
| reason | n | avg R |
|---|---|---|
| stop/stop | 169 | -1.072 |
| T1/trail | 92 | 0.339 |
| time/time | 71 | 0.082 |
| T1/time | 54 | 1.030 |
| T1/T2 | 48 | 2.099 |

Target and stop buckets are positive/negative by construction and the time-exit bucket is selected on having avoided both; none of these is evidence for a variant.

## Parameter grid (full sample, net 3 pts; for robustness only, not selection)
- cells: 36; positive avg R: 16 (44%); grid = {'gap_atr': (0.75, 1.0), 'or_atr': (0.15, 0.2, 0.25), 'adx_min': (20.0, 25.0), 'buffer_atr': (0.1, 0.15, 0.2)}
| params | n | avg R | total R | max DD R |
|---|---|---|---|---|
| gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 | 248 | 0.102 | 25.3 | 11.9 |
| gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 | 249 | 0.098 | 24.3 | 11.9 |
| gap_atr=1.0 or_atr=0.25 adx_min=25.0 buffer_atr=0.2 | 170 | 0.082 | 14.0 | 9.2 |
| gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2 | 171 | 0.076 | 12.9 | 9.2 |
| gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.15 | 392 | 0.056 | 21.9 | 20.3 |
| gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.15 | 390 | 0.055 | 21.3 | 20.3 |
| gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2 | 296 | 0.036 | 10.6 | 14.0 |
| gap_atr=1.0 or_atr=0.2 adx_min=20.0 buffer_atr=0.2 | 296 | 0.036 | 10.6 | 14.0 |

## Walk-forward (12m in-sample / 3m out-of-sample, step 3m)
  WF 2022-01-01..2023-01-01 -> OOS to 2023-04-01: IS n=75 avgR=0.017 | OOS n=20 avgR=0.011 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.15
  WF 2022-04-01..2023-04-01 -> OOS to 2023-07-01: IS n=46 avgR=0.014 | OOS n=9 avgR=0.072 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2
  WF 2022-07-01..2023-07-01 -> OOS to 2023-10-01: IS n=35 avgR=0.018 | OOS n=15 avgR=0.110 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2022-10-01..2023-10-01 -> OOS to 2024-01-01: IS n=45 avgR=0.168 | OOS n=15 avgR=0.245 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2023-01-01..2024-01-01 -> OOS to 2024-04-01: IS n=35 avgR=0.292 | OOS n=7 avgR=-0.393 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2
  WF 2023-04-01..2024-04-01 -> OOS to 2024-07-01: IS n=74 avgR=0.061 | OOS n=19 avgR=-0.358 | gap_atr=0.75 or_atr=0.15 adx_min=25.0 buffer_atr=0.1
  WF 2023-07-01..2024-07-01 -> OOS to 2024-10-01: IS n=89 avgR=0.098 | OOS n=24 avgR=-0.260 | gap_atr=0.75 or_atr=0.15 adx_min=20.0 buffer_atr=0.15
  WF 2023-10-01..2024-10-01 -> OOS to 2025-01-01: IS n=47 avgR=0.061 | OOS n=17 avgR=0.168 | gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2024-01-01..2025-01-01 -> OOS to 2025-04-01: IS n=49 avgR=0.041 | OOS n=10 avgR=0.667 | gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2024-04-01..2025-04-01 -> OOS to 2025-07-01: IS n=47 avgR=0.320 | OOS n=11 avgR=0.444 | gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2024-07-01..2025-07-01 -> OOS to 2025-10-01: IS n=47 avgR=0.340 | OOS n=18 avgR=-0.091 | gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2024-10-01..2025-10-01 -> OOS to 2026-01-01: IS n=56 avgR=0.228 | OOS n=24 avgR=0.124 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2025-01-01..2026-01-01 -> OOS to 2026-04-01: IS n=63 avgR=0.205 | OOS n=15 avgR=0.618 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2025-04-01..2026-04-01 -> OOS to 2026-07-01: IS n=68 avgR=0.228 | OOS n=15 avgR=-0.368 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2025-07-01..2026-07-01 -> OOS to 2026-10-01: IS n=72 avgR=0.071 | OOS n=12 avgR=-0.282 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2025-10-01..2026-10-01 -> OOS to 2027-01-01: IS n=42 avgR=0.068 | OOS n=4 avgR=0.531 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2

| IS from | IS to | OOS to | IS n | IS avg R | OOS n | OOS avg R | OOS total R | params |
|---|---|---|---|---|---|---|---|---|
| 2022-01-01 | 2023-01-01 | 2023-04-01 | 75 | 0.017 | 20 | 0.011 | 0.2 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.15 |
| 2022-04-01 | 2023-04-01 | 2023-07-01 | 46 | 0.014 | 9 | 0.072 | 0.6 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2 |
| 2022-07-01 | 2023-07-01 | 2023-10-01 | 35 | 0.018 | 15 | 0.110 | 1.7 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2022-10-01 | 2023-10-01 | 2024-01-01 | 45 | 0.168 | 15 | 0.245 | 3.7 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2023-01-01 | 2024-01-01 | 2024-04-01 | 35 | 0.292 | 7 | -0.393 | -2.8 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2 |
| 2023-04-01 | 2024-04-01 | 2024-07-01 | 74 | 0.061 | 19 | -0.358 | -6.8 | gap_atr=0.75 or_atr=0.15 adx_min=25.0 buffer_atr=0.1 |
| 2023-07-01 | 2024-07-01 | 2024-10-01 | 89 | 0.098 | 24 | -0.260 | -6.2 | gap_atr=0.75 or_atr=0.15 adx_min=20.0 buffer_atr=0.15 |
| 2023-10-01 | 2024-10-01 | 2025-01-01 | 47 | 0.061 | 17 | 0.168 | 2.9 | gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2024-01-01 | 2025-01-01 | 2025-04-01 | 49 | 0.041 | 10 | 0.667 | 6.7 | gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2024-04-01 | 2025-04-01 | 2025-07-01 | 47 | 0.320 | 11 | 0.444 | 4.9 | gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2024-07-01 | 2025-07-01 | 2025-10-01 | 47 | 0.340 | 18 | -0.091 | -1.6 | gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2024-10-01 | 2025-10-01 | 2026-01-01 | 56 | 0.228 | 24 | 0.124 | 3.0 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2025-01-01 | 2026-01-01 | 2026-04-01 | 63 | 0.205 | 15 | 0.618 | 9.3 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2025-04-01 | 2026-04-01 | 2026-07-01 | 68 | 0.228 | 15 | -0.368 | -5.5 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2025-07-01 | 2026-07-01 | 2026-10-01 | 72 | 0.071 | 12 | -0.282 | -3.4 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2025-10-01 | 2026-10-01 | 2027-01-01 | 42 | 0.068 | 4 | 0.531 | 2.1 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2 |

### Pooled out-of-sample
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| OOS cost 0 pts | 235 | 0.101 | 51.9% | 23.8 | 12.7 | 1.27 | 5.7 |
| OOS cost 3 pts | 235 | 0.037 | 48.9% | 8.7 | 16.8 | 1.09 | 5.7 |
| OOS cost 6 pts | 235 | -0.028 | 45.1% | -6.5 | 22.1 | 0.94 | 5.7 |
| OOS cost 10 pts | 235 | -0.114 | 42.6% | -26.8 | 34.0 | 0.77 | 5.7 |
- bootstrap 95% CI of mean R (net 3 pts): [-0.089, 0.180]
- distinct parameter sets chosen across windows: 7 of 16

## Like-for-like: fixed spec params vs walk-forward, same OOS windows (net 3 pts)
- OOS windows: 949 sessions, 2023-01-02 .. 2026-11-11
| set | n | avg R | 95% CI | win % | total R | max DD R |
|---|---|---|---|---|---|---|
| fixed spec params | 359 | 0.030 | [-0.083, 0.157] | 48.7% | 10.9 | 17.1 |
| walk-forward (re-chosen) | 235 | 0.037 | [-0.089, 0.180] | 48.9% | 8.7 | 16.8 |
- difference walk-forward minus fixed: 0.006R, 95% CI [-0.173, 0.189]
- parameter selection added measurable value: **no** (CI of the difference includes zero)

## Slice analysis (exploratory; 29 slices examined, Holm-adjusted; full sample, net 3 pts)
| dimension | slice | n | mean R | rest mean R | p raw | p Holm | significant |
|---|---|---|---|---|---|---|---|
| year | 2022 | 75 | 0.017 | 0.030 | 0.932 | 1.000 | no |
| year | 2023 | 72 | 0.133 | 0.007 | 0.418 | 1.000 | no |
| year | 2024 | 88 | -0.018 | 0.040 | 0.688 | 1.000 | no |
| year | 2025 | 107 | 0.054 | 0.020 | 0.783 | 1.000 | no |
| year | 2026 | 92 | -0.032 | 0.044 | 0.562 | 1.000 | no |
| day_type | RANGE | 15 | 0.101 | 0.025 | 0.781 | 1.000 | no |
| day_type | TREND | 419 | 0.025 | 0.101 | 0.781 | 1.000 | no |
| side | LONG | 203 | -0.059 | 0.105 | 0.135 | 1.000 | no |
| side | SHORT | 231 | 0.105 | -0.059 | 0.135 | 1.000 | no |
| level_type | camarilla | 8 | 0.123 | 0.026 | 0.799 | 1.000 | no |
| level_type | pivot | 212 | -0.029 | 0.083 | 0.311 | 1.000 | no |
| level_type | round | 214 | 0.082 | -0.024 | 0.345 | 1.000 | no |
| bias_at_entry | -1 | 223 | 0.099 | -0.046 | 0.190 | 1.000 | no |
| bias_at_entry | 0 | 13 | 0.069 | 0.027 | 0.892 | 1.000 | no |
| bias_at_entry | 1 | 198 | -0.054 | 0.097 | 0.169 | 1.000 | no |
| weekday | Fri | 84 | 0.026 | 0.028 | 0.989 | 1.000 | no |
| weekday | Mon | 91 | 0.067 | 0.018 | 0.703 | 1.000 | no |
| weekday | Thu | 88 | 0.020 | 0.030 | 0.942 | 1.000 | no |
| weekday | Tue | 74 | 0.139 | 0.005 | 0.397 | 1.000 | no |
| weekday | Wed | 97 | -0.085 | 0.061 | 0.249 | 1.000 | no |
| expiry_day | expiry | 92 | 0.119 | 0.004 | 0.414 | 1.000 | no |
| expiry_day | other | 342 | 0.004 | 0.119 | 0.414 | 1.000 | no |
| gap_vs_side | against | 117 | 0.267 | -0.060 | 0.017 | 0.494 | no |
| gap_vs_side | with | 317 | -0.060 | 0.267 | 0.017 | 0.494 | no |
| or_atr_tercile | T1 | 145 | -0.139 | 0.112 | 0.027 | 0.728 | no |
| or_atr_tercile | T2 | 144 | 0.142 | -0.029 | 0.147 | 1.000 | no |
| or_atr_tercile | T3 | 145 | 0.082 | 0.001 | 0.506 | 1.000 | no |
| entry_seq | 1 | 368 | -0.015 | 0.267 | 0.061 | 1.000 | no |
| entry_seq | 2 | 66 | 0.267 | -0.015 | 0.061 | 1.000 | no |
- **No slice is significant after multiplicity** (29 looks). Weekday, side, year and hour differences are consistent with noise. No slice may be used as a filter in this strategy.

## Regime check: rolling 50-trade hit rate vs a stationary binomial
- trades 434, hit rate 48.2%, overlapping windows 385
- observed rolling range: 30% .. 62%
- simulated 95% band for the minimum: 24% .. 40%; for the maximum: 56% .. 72%
- observed range outside the band: **no**. No regime change is supported: the swings are what a constant hit rate produces.

## Go-live gates
| gate | result | detail |
|---|---|---|
| 1 walk-forward OOS net 3 pts: n>=100, avg R>=0.10, CI low>0 | **FAIL** | n=235 avgR=0.037 CI95=[-0.089, 0.180] |
| 2 robustness: avg R>0 at 6 pts; >=60% grid cells positive; stable params | **FAIL** | avgR@6pts=-0.028 grid positive=16/36 (44%) distinct WF param sets=7/16 |
| 3 OOS max drawdown <= 12R | **FAIL** | maxDD=16.8R = Rs 33,631 = 22.4% of Rs 150,000 |
| 4 paper phase: >=30 sessions with alerts + journal, realised vs backtest R within tolerance | **PENDING** | PENDING - paper phase not started |
| 5 live one lot only for >=20 sessions before any size change | **PENDING** | PENDING - after gate 4 |

## Verdict: **FAIL**
- like-for-like: fixed 0.030R vs walk-forward 0.037R, difference CI [-0.173, 0.189]; selection added value: no
- slices significant after multiplicity: 0 of 29
- regime change supported: no
- data 2022-01-01 .. 2026-11-25 is CONSUMED for this strategy family (see hypotheses/ledger.md)

- wrote reports/pcl_nifty_confirm_trades.csv (434 rows), reports/pcl_nifty_confirm_oos_trades.csv (235 rows); elapsed 18s
