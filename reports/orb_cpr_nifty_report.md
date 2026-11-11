# orb_cpr_nifty backtest  2022-01-01 -> 2026-11-12  (generated 2026-11-12 01:03 IST, commit 9397e18)

- 1-minute rows: 457,431; valid sessions (>= 70 five-minute bars, weekdays): 1192 (2022-01-03 .. 2026-11-11); sessions with features: 1178
- params: bar_minutes=5, or_minutes=15, session_open=09:15:00, signal_start=09:30:00, signal_end=11:00:00, time_exit=15:15:00, atr_period=14, gap_atr_max=1.0, or_min_atr=0.2, or_max_atr=0.6, cpr_max_pct=0.6, stop_atr_cap=0.5, target_r=1.5, be_trigger_r=1.0, cost_points=3.0, min_session_bars=70, exclude_weekends=True, max_chase_atr=0.1

## Day-filter funnel and data sanity
| step | sessions |
|---|---|
| sessions in 1m data | 1200 |
| - weekend special sessions | 7 |
| - fewer than 70 five-minute bars | 2 |
| = valid sessions | 1192 |
| - no features (first 15 sessions) | 14 |
| = evaluable sessions | 1178 |
| pass gap | 1138 |
| pass or_min | 1002 |
| pass or_max | 961 |
| pass cpr | 939 |
| pass or_break | 861 |
| pass cpr_align | 670 |
| = trades taken | 670 |

- survivors of every filter == trades: **yes** (670 vs 670)
- duplicate 1-minute timestamps: 0
- valid sessions whose first 5m bar is not 09:15: 0
- weekend special sessions excluded: 7  ['2023-11-12', '2024-01-20', '2024-03-02', '2024-05-18', '2025-02-01', '2026-02-01', '2026-11-08']
- weekday sessions excluded for < 70 five-minute bars: 2  ['2022-03-07', '2024-11-01']
- trades by year: {2022: 114, 2023: 149, 2024: 126, 2025: 165, 2026: 116}

## Baseline (default params) and cost sensitivity
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| cost 0 pts | 670 | 0.046 | 44.0% | 31.1 | 16.8 | 1.11 | 3.6 |
| cost 3 pts | 670 | 0.002 | 43.7% | 1.2 | 25.3 | 1.00 | 3.6 |
| cost 6 pts | 670 | -0.043 | 43.3% | -28.7 | 37.9 | 0.91 | 3.6 |
| cost 10 pts | 670 | -0.102 | 42.7% | -68.6 | 74.2 | 0.80 | 3.6 |

Skips: cpr_too_wide=30, gap_too_large=38, no_breakout=269, no_features=14, or_too_large=37, or_too_small=134; signal days=670 of 1192

## By year (net 3 pts; descriptive, see slice table for significance)
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| 2022 | 114 | -0.045 | 40.4% | -5.1 | 9.8 | 0.90 | 0.6 |
| 2023 | 149 | -0.117 | 38.3% | -17.5 | 19.5 | 0.79 | -3.1 |
| 2024 | 126 | 0.088 | 45.2% | 11.0 | 8.9 | 1.21 | 11.4 |
| 2025 | 165 | 0.071 | 46.1% | 11.7 | 6.5 | 1.17 | 3.6 |
| 2026 | 116 | 0.009 | 49.1% | 1.1 | 19.0 | 1.02 | 6.3 |

## Exit reasons (net 3 pts; conditioned on outcome, descriptive only)
| reason | n | avg R |
|---|---|---|
| stop | 275 | -1.047 |
| time | 187 | 0.331 |
| target | 158 | 1.452 |
| be_stop | 50 | -0.047 |

Target and stop buckets are positive/negative by construction and the time-exit bucket is selected on having avoided both; none of these is evidence for a variant.

## Parameter grid (full sample, net 3 pts; for robustness only, not selection)
- cells: 81; positive avg R: 58 (72%); grid = {'or_min_atr': (0.15, 0.2, 0.25), 'or_max_atr': (0.5, 0.6, 0.7), 'target_r': (1.0, 1.5, 2.0), 'cpr_max_pct': (0.4, 0.6, 0.8)}
| params | n | avg R | total R | max DD R |
|---|---|---|---|---|
| or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 | 458 | 0.075 | 34.2 | 9.6 |
| or_min_atr=0.25 or_max_atr=0.6 target_r=2.0 cpr_max_pct=0.4 | 490 | 0.071 | 34.6 | 10.2 |
| or_min_atr=0.25 or_max_atr=0.7 target_r=2.0 cpr_max_pct=0.4 | 501 | 0.066 | 33.3 | 10.2 |
| or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4 | 458 | 0.065 | 29.9 | 11.0 |
| or_min_atr=0.25 or_max_atr=0.6 target_r=1.5 cpr_max_pct=0.4 | 490 | 0.061 | 30.0 | 11.5 |
| or_min_atr=0.25 or_max_atr=0.7 target_r=1.5 cpr_max_pct=0.4 | 501 | 0.056 | 28.1 | 11.5 |
| or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.6 | 488 | 0.049 | 23.7 | 10.6 |
| or_min_atr=0.25 or_max_atr=0.6 target_r=2.0 cpr_max_pct=0.6 | 524 | 0.046 | 24.1 | 11.2 |

## Walk-forward (12m in-sample / 3m out-of-sample, step 3m)
  WF 2022-01-01..2023-01-01 -> OOS to 2023-04-01: IS n=111 avgR=0.154 | OOS n=46 avgR=-0.135 | or_min_atr=0.15 or_max_atr=0.7 target_r=2.0 cpr_max_pct=0.4
  WF 2022-04-01..2023-04-01 -> OOS to 2023-07-01: IS n=139 avgR=0.034 | OOS n=39 avgR=0.033 | or_min_atr=0.15 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4
  WF 2022-07-01..2023-07-01 -> OOS to 2023-10-01: IS n=104 avgR=0.090 | OOS n=33 avgR=-0.171 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4
  WF 2022-10-01..2023-10-01 -> OOS to 2024-01-01: IS n=110 avgR=-0.024 | OOS n=22 avgR=0.129 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4
  WF 2023-01-01..2024-01-01 -> OOS to 2024-04-01: IS n=110 avgR=0.013 | OOS n=23 avgR=0.377 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4
  WF 2023-04-01..2024-04-01 -> OOS to 2024-07-01: IS n=103 avgR=0.131 | OOS n=13 avgR=-0.226 | or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4
  WF 2023-07-01..2024-07-01 -> OOS to 2024-10-01: IS n=91 avgR=0.054 | OOS n=16 avgR=0.203 | or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4
  WF 2023-10-01..2024-10-01 -> OOS to 2025-01-01: IS n=74 avgR=0.193 | OOS n=22 avgR=-0.048 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4
  WF 2024-01-01..2025-01-01 -> OOS to 2025-04-01: IS n=80 avgR=0.174 | OOS n=34 avgR=-0.115 | or_min_atr=0.25 or_max_atr=0.6 target_r=1.5 cpr_max_pct=0.4
  WF 2024-04-01..2025-04-01 -> OOS to 2025-07-01: IS n=102 avgR=-0.004 | OOS n=24 avgR=0.212 | or_min_atr=0.25 or_max_atr=0.6 target_r=2.0 cpr_max_pct=0.6
  WF 2024-07-01..2025-07-01 -> OOS to 2025-10-01: IS n=99 avgR=0.090 | OOS n=32 avgR=0.169 | or_min_atr=0.25 or_max_atr=0.6 target_r=1.5 cpr_max_pct=0.4
  WF 2024-10-01..2025-10-01 -> OOS to 2026-01-01: IS n=123 avgR=0.106 | OOS n=45 avgR=0.083 | or_min_atr=0.25 or_max_atr=0.6 target_r=1.5 cpr_max_pct=0.8
  WF 2025-01-01..2026-01-01 -> OOS to 2026-04-01: IS n=149 avgR=0.126 | OOS n=27 avgR=0.236 | or_min_atr=0.2 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4
  WF 2025-04-01..2026-04-01 -> OOS to 2026-07-01: IS n=113 avgR=0.237 | OOS n=24 avgR=-0.234 | or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4
  WF 2025-07-01..2026-07-01 -> OOS to 2026-10-01: IS n=162 avgR=0.137 | OOS n=44 avgR=-0.184 | or_min_atr=0.15 or_max_atr=0.7 target_r=2.0 cpr_max_pct=0.6
  WF 2025-10-01..2026-10-01 -> OOS to 2027-01-01: IS n=109 avgR=0.072 | OOS n=7 avgR=0.673 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4

| IS from | IS to | OOS to | IS n | IS avg R | OOS n | OOS avg R | OOS total R | params |
|---|---|---|---|---|---|---|---|---|
| 2022-01-01 | 2023-01-01 | 2023-04-01 | 111 | 0.154 | 46 | -0.135 | -6.2 | or_min_atr=0.15 or_max_atr=0.7 target_r=2.0 cpr_max_pct=0.4 |
| 2022-04-01 | 2023-04-01 | 2023-07-01 | 139 | 0.034 | 39 | 0.033 | 1.3 | or_min_atr=0.15 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 |
| 2022-07-01 | 2023-07-01 | 2023-10-01 | 104 | 0.090 | 33 | -0.171 | -5.6 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 |
| 2022-10-01 | 2023-10-01 | 2024-01-01 | 110 | -0.024 | 22 | 0.129 | 2.8 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 |
| 2023-01-01 | 2024-01-01 | 2024-04-01 | 110 | 0.013 | 23 | 0.377 | 8.7 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 |
| 2023-04-01 | 2024-04-01 | 2024-07-01 | 103 | 0.131 | 13 | -0.226 | -2.9 | or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4 |
| 2023-07-01 | 2024-07-01 | 2024-10-01 | 91 | 0.054 | 16 | 0.203 | 3.2 | or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4 |
| 2023-10-01 | 2024-10-01 | 2025-01-01 | 74 | 0.193 | 22 | -0.048 | -1.1 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 |
| 2024-01-01 | 2025-01-01 | 2025-04-01 | 80 | 0.174 | 34 | -0.115 | -3.9 | or_min_atr=0.25 or_max_atr=0.6 target_r=1.5 cpr_max_pct=0.4 |
| 2024-04-01 | 2025-04-01 | 2025-07-01 | 102 | -0.004 | 24 | 0.212 | 5.1 | or_min_atr=0.25 or_max_atr=0.6 target_r=2.0 cpr_max_pct=0.6 |
| 2024-07-01 | 2025-07-01 | 2025-10-01 | 99 | 0.090 | 32 | 0.169 | 5.4 | or_min_atr=0.25 or_max_atr=0.6 target_r=1.5 cpr_max_pct=0.4 |
| 2024-10-01 | 2025-10-01 | 2026-01-01 | 123 | 0.106 | 45 | 0.083 | 3.7 | or_min_atr=0.25 or_max_atr=0.6 target_r=1.5 cpr_max_pct=0.8 |
| 2025-01-01 | 2026-01-01 | 2026-04-01 | 149 | 0.126 | 27 | 0.236 | 6.4 | or_min_atr=0.2 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 |
| 2025-04-01 | 2026-04-01 | 2026-07-01 | 113 | 0.237 | 24 | -0.234 | -5.6 | or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4 |
| 2025-07-01 | 2026-07-01 | 2026-10-01 | 162 | 0.137 | 44 | -0.184 | -8.1 | or_min_atr=0.15 or_max_atr=0.7 target_r=2.0 cpr_max_pct=0.6 |
| 2025-10-01 | 2026-10-01 | 2027-01-01 | 109 | 0.072 | 7 | 0.673 | 4.7 | or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 |

### Pooled out-of-sample
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| OOS cost 0 pts | 451 | 0.063 | 43.2% | 28.3 | 14.4 | 1.15 | 4.0 |
| OOS cost 3 pts | 451 | 0.018 | 43.0% | 7.9 | 16.5 | 1.04 | 4.0 |
| OOS cost 6 pts | 451 | -0.028 | 42.4% | -12.5 | 20.3 | 0.94 | 4.0 |
| OOS cost 10 pts | 451 | -0.088 | 41.9% | -39.8 | 46.1 | 0.83 | 4.0 |
- bootstrap 95% CI of mean R (net 3 pts): [-0.084, 0.117]
- distinct parameter sets chosen across windows: 9 of 16

## Like-for-like: fixed spec params vs walk-forward, same OOS windows (net 3 pts)
- OOS windows: 949 sessions, 2023-01-02 .. 2026-11-11
| set | n | avg R | 95% CI | win % | total R | max DD R |
|---|---|---|---|---|---|---|
| fixed spec params | 556 | 0.011 | [-0.071, 0.091] | 44.4% | 6.3 | 19.5 |
| walk-forward (re-chosen) | 451 | 0.018 | [-0.084, 0.117] | 43.0% | 7.9 | 16.5 |
- difference walk-forward minus fixed: 0.006R, 95% CI [-0.136, 0.138]
- parameter selection added measurable value: **no** (CI of the difference includes zero)

## Slice analysis (exploratory; 23 slices examined, Holm-adjusted; full sample, net 3 pts)
| dimension | slice | n | mean R | rest mean R | p raw | p Holm | significant |
|---|---|---|---|---|---|---|---|
| weekday | Fri | 142 | 0.176 | -0.045 | 0.028 | 0.652 | no |
| weekday | Mon | 132 | -0.017 | 0.006 | 0.819 | 1.000 | no |
| weekday | Thu | 132 | -0.078 | 0.021 | 0.328 | 1.000 | no |
| weekday | Tue | 133 | -0.009 | 0.004 | 0.894 | 1.000 | no |
| weekday | Wed | 131 | -0.077 | 0.021 | 0.325 | 1.000 | no |
| side | LONG | 335 | -0.049 | 0.053 | 0.201 | 1.000 | no |
| side | SHORT | 335 | 0.053 | -0.049 | 0.201 | 1.000 | no |
| year | 2022 | 114 | -0.045 | 0.011 | 0.591 | 1.000 | no |
| year | 2023 | 149 | -0.117 | 0.036 | 0.118 | 1.000 | no |
| year | 2024 | 126 | 0.088 | -0.018 | 0.309 | 1.000 | no |
| year | 2025 | 165 | 0.071 | -0.021 | 0.325 | 1.000 | no |
| year | 2026 | 116 | 0.009 | 0.000 | 0.930 | 1.000 | no |
| signal_hour | 10 | 226 | -0.026 | 0.016 | 0.610 | 1.000 | no |
| signal_hour | 11 | 9 | 0.014 | 0.002 | 0.978 | 1.000 | no |
| signal_hour | 9 | 435 | 0.016 | -0.025 | 0.621 | 1.000 | no |
| or_atr_tercile | T1 | 223 | -0.069 | 0.037 | 0.221 | 1.000 | no |
| or_atr_tercile | T2 | 223 | 0.089 | -0.042 | 0.119 | 1.000 | no |
| or_atr_tercile | T3 | 224 | -0.015 | 0.010 | 0.763 | 1.000 | no |
| cpr_width_tercile | T1 | 223 | 0.031 | -0.013 | 0.615 | 1.000 | no |
| cpr_width_tercile | T2 | 223 | 0.021 | -0.008 | 0.741 | 1.000 | no |
| cpr_width_tercile | T3 | 224 | -0.046 | 0.026 | 0.393 | 1.000 | no |
| gap_sign | gap_down_or_flat | 252 | 0.002 | 0.002 | 0.997 | 1.000 | no |
| gap_sign | gap_up | 418 | 0.002 | 0.002 | 0.997 | 1.000 | no |
- **No slice is significant after multiplicity** (23 looks). Weekday, side, year and hour differences are consistent with noise. No slice may be used as a filter in this strategy.

## Regime check: rolling 50-trade hit rate vs a stationary binomial
- trades 670, hit rate 43.7%, overlapping windows 621
- observed rolling range: 28% .. 62%
- simulated 95% band for the minimum: 20% .. 34%; for the maximum: 54% .. 68%
- observed range outside the band: **no**. No regime change is supported: the swings are what a constant hit rate produces.

## Go-live gates
| gate | result | detail |
|---|---|---|
| 1 walk-forward OOS net 3 pts: n>=100, avg R>=0.10, CI low>0 | **FAIL** | n=451 avgR=0.018 CI95=[-0.084, 0.117] |
| 2 robustness: avg R>0 at 6 pts; >=60% grid cells positive; stable params | **FAIL** | avgR@6pts=-0.028 grid positive=58/81 (72%) distinct WF param sets=9/16 |
| 3 OOS max drawdown <= 12R | **FAIL** | maxDD=16.5R = Rs 32,943 = 22.0% of Rs 150,000 |
| 4 paper phase: >=30 sessions with alerts + journal, realised vs backtest R within tolerance | **PENDING** | PENDING - paper phase not started |
| 5 live one lot only for >=20 sessions before any size change | **PENDING** | PENDING - after gate 4 |

## Verdict: **FAIL**
- like-for-like: fixed 0.011R vs walk-forward 0.018R, difference CI [-0.136, 0.138]; selection added value: no
- slices significant after multiplicity: 0 of 23
- regime change supported: no
- data 2022-01 .. 2026-11 is CONSUMED for this strategy family (see hypotheses/ledger.md)

- wrote reports/orb_cpr_nifty_trades.csv (670 rows), reports/orb_cpr_nifty_oos_trades.csv (451 rows); elapsed 19s
