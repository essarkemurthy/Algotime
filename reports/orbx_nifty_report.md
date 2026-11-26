# orbx_nifty backtest  2015-01-01 -> 2021-12-31  (generated 2026-11-26 12:03 IST, commit 2d71f38)
- ledger rising bar: OOS CI lower bound must exceed 0.02 R

- 1-minute rows: 637,670; valid sessions (>= 70 five-minute bars, weekdays): 1690 (2015-01-01 .. 2021-12-31); sessions with features: 1676
- params: bar_minutes=5, or_minutes=15, session_open=09:15:00, signal_start=09:30:00, signal_end=11:00:00, time_exit=15:15:00, atr_period=14, adx_period=14, rsi_period=14, adx_min=20.0, rsi_line=50.0, stop_atr_cap=0.5, target_r=1.5, be_trigger_r=1.0, cost_points=3.0, min_session_bars=70, exclude_weekends=True

## Day-filter funnel and data sanity
| step | sessions |
|---|---|
| sessions in 1m data | 1701 |
| - weekend special sessions | 4 |
| - fewer than 70 bars of 5 min | 7 |
| = valid sessions | 1690 |
| - no features (warm-up) | 14 |
| = evaluable sessions | 1676 |
| - skip no_opening_range | 0 |
| - skip no_breakout | 189 |
| - skip adx_undefined | 0 |
| - skip adx_below_min | 180 |
| - skip rsi_wrong_side | 121 |
| - skip no_next_bar | 0 |
| - skip no_features | 14 |
| = trades taken | 1186 |

- survivors of every filter == trades: **NO** (1172 vs 1186)
- duplicate 1-minute timestamps: 0
- valid sessions whose first 5m bar is not 09:15: 0
- weekend special sessions excluded: 4  ['2015-02-28', '2016-10-30', '2019-10-27', '2020-11-14']
- weekday sessions excluded for < 70 five-minute bars: 7  ['2015-11-11', '2017-07-10', '2018-11-07', '2020-03-13', '2020-03-23', '2021-01-11', '2021-02-24']
- trades by year: {2015: 168, 2016: 157, 2017: 152, 2018: 175, 2019: 175, 2020: 174, 2021: 185}

## Baseline (default params) and cost sensitivity
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| cost 0 pts | 1186 | 0.056 | 42.4% | 66.1 | 21.2 | 1.12 | 2.1 |
| cost 3 pts | 1186 | -0.037 | 41.7% | -43.5 | 59.5 | 0.93 | 2.1 |
| cost 6 pts | 1186 | -0.129 | 40.5% | -153.1 | 158.7 | 0.77 | 2.1 |
| cost 10 pts | 1186 | -0.252 | 39.4% | -299.2 | 302.0 | 0.60 | 2.1 |

Skips: adx_below_min=180, no_breakout=189, no_features=14, rsi_wrong_side=121; signal days=1186 of 1690

## By year (net 3 pts; descriptive, see slice table for significance)
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| 2015 | 168 | -0.004 | 45.2% | -0.7 | 15.1 | 0.99 | 5.3 |
| 2016 | 157 | -0.048 | 39.5% | -7.5 | 17.5 | 0.90 | 2.3 |
| 2017 | 152 | 0.006 | 48.0% | 0.9 | 10.7 | 1.01 | 3.6 |
| 2018 | 175 | -0.065 | 40.6% | -11.4 | 23.4 | 0.87 | 1.8 |
| 2019 | 175 | -0.064 | 38.3% | -11.1 | 20.6 | 0.88 | -0.0 |
| 2020 | 174 | 0.012 | 42.5% | 2.0 | 17.6 | 1.02 | 3.8 |
| 2021 | 185 | -0.085 | 38.9% | -15.7 | 28.2 | 0.84 | -1.2 |

## Exit reasons (net 3 pts; conditioned on outcome, descriptive only)
| reason | n | avg R |
|---|---|---|
| stop | 507 | -1.096 |
| target | 328 | 1.402 |
| time | 249 | 0.250 |
| be_stop | 102 | -0.098 |

Target and stop buckets are positive/negative by construction and the time-exit bucket is selected on having avoided both; none of these is evidence for a variant.

## Parameter grid (full sample, net 3 pts; for robustness only, not selection)
- cells: 8; positive avg R: 0 (0%); grid = {'or_minutes': (15, 30), 'adx_min': (20.0, 25.0), 'rsi_line': (50.0, 55.0)}
| params | n | avg R | total R | max DD R |
|---|---|---|---|---|
| or_minutes=30 adx_min=20.0 rsi_line=55.0 | 977 | -0.006 | -5.9 | 43.1 |
| or_minutes=30 adx_min=20.0 rsi_line=50.0 | 968 | -0.009 | -8.5 | 43.2 |
| or_minutes=30 adx_min=25.0 rsi_line=55.0 | 790 | -0.026 | -20.4 | 48.5 |
| or_minutes=15 adx_min=25.0 rsi_line=55.0 | 989 | -0.027 | -26.4 | 40.0 |
| or_minutes=15 adx_min=20.0 rsi_line=55.0 | 1209 | -0.029 | -35.6 | 50.9 |
| or_minutes=15 adx_min=25.0 rsi_line=50.0 | 968 | -0.030 | -29.3 | 48.0 |
| or_minutes=30 adx_min=25.0 rsi_line=50.0 | 781 | -0.032 | -24.7 | 55.3 |
| or_minutes=15 adx_min=20.0 rsi_line=50.0 | 1186 | -0.037 | -43.5 | 59.5 |

## Walk-forward (12m in-sample / 3m out-of-sample, step 3m)
  WF 2015-01-01..2016-01-01 -> OOS to 2016-04-01: IS n=101 avgR=0.177 | OOS n=24 avgR=0.263 | or_minutes=30 adx_min=25.0 rsi_line=50.0
  WF 2015-04-01..2016-04-01 -> OOS to 2016-07-01: IS n=104 avgR=0.245 | OOS n=22 avgR=-0.197 | or_minutes=30 adx_min=25.0 rsi_line=50.0
  WF 2015-07-01..2016-07-01 -> OOS to 2016-10-01: IS n=94 avgR=0.134 | OOS n=28 avgR=0.026 | or_minutes=30 adx_min=25.0 rsi_line=50.0
  WF 2015-10-01..2016-10-01 -> OOS to 2017-01-01: IS n=97 avgR=0.124 | OOS n=20 avgR=0.094 | or_minutes=30 adx_min=25.0 rsi_line=55.0
  WF 2016-01-01..2017-01-01 -> OOS to 2017-04-01: IS n=93 avgR=0.106 | OOS n=23 avgR=-0.340 | or_minutes=30 adx_min=25.0 rsi_line=55.0
  WF 2016-04-01..2017-04-01 -> OOS to 2017-07-01: IS n=119 avgR=-0.043 | OOS n=37 avgR=-0.168 | or_minutes=15 adx_min=25.0 rsi_line=55.0
  WF 2016-07-01..2017-07-01 -> OOS to 2017-10-01: IS n=101 avgR=-0.106 | OOS n=30 avgR=0.228 | or_minutes=30 adx_min=25.0 rsi_line=55.0
  WF 2016-10-01..2017-10-01 -> OOS to 2018-01-01: IS n=124 avgR=-0.014 | OOS n=34 avgR=-0.150 | or_minutes=15 adx_min=25.0 rsi_line=50.0
  WF 2017-01-01..2018-01-01 -> OOS to 2018-04-01: IS n=152 avgR=0.006 | OOS n=42 avgR=0.037 | or_minutes=15 adx_min=20.0 rsi_line=50.0
  WF 2017-04-01..2018-04-01 -> OOS to 2018-07-01: IS n=139 avgR=0.072 | OOS n=38 avgR=-0.340 | or_minutes=30 adx_min=20.0 rsi_line=50.0
  WF 2017-07-01..2018-07-01 -> OOS to 2018-10-01: IS n=147 avgR=0.055 | OOS n=34 avgR=-0.103 | or_minutes=15 adx_min=25.0 rsi_line=55.0
  WF 2017-10-01..2018-10-01 -> OOS to 2019-01-01: IS n=144 avgR=-0.023 | OOS n=38 avgR=-0.133 | or_minutes=15 adx_min=25.0 rsi_line=55.0
  WF 2018-01-01..2019-01-01 -> OOS to 2019-04-01: IS n=140 avgR=-0.033 | OOS n=33 avgR=-0.212 | or_minutes=15 adx_min=25.0 rsi_line=50.0
  WF 2018-04-01..2019-04-01 -> OOS to 2019-07-01: IS n=177 avgR=-0.096 | OOS n=43 avgR=0.090 | or_minutes=15 adx_min=20.0 rsi_line=55.0
  WF 2018-07-01..2019-07-01 -> OOS to 2019-10-01: IS n=171 avgR=-0.007 | OOS n=49 avgR=-0.199 | or_minutes=15 adx_min=20.0 rsi_line=50.0
  WF 2018-10-01..2019-10-01 -> OOS to 2020-01-01: IS n=174 avgR=-0.017 | OOS n=42 avgR=0.015 | or_minutes=15 adx_min=20.0 rsi_line=55.0
  WF 2019-01-01..2020-01-01 -> OOS to 2020-04-01: IS n=173 avgR=-0.022 | OOS n=40 avgR=0.182 | or_minutes=15 adx_min=20.0 rsi_line=55.0
  WF 2019-04-01..2020-04-01 -> OOS to 2020-07-01: IS n=172 avgR=0.024 | OOS n=42 avgR=0.007 | or_minutes=15 adx_min=20.0 rsi_line=55.0
  WF 2019-07-01..2020-07-01 -> OOS to 2020-10-01: IS n=171 avgR=0.003 | OOS n=43 avgR=0.054 | or_minutes=15 adx_min=20.0 rsi_line=55.0
  WF 2019-10-01..2020-10-01 -> OOS to 2021-01-01: IS n=164 avgR=0.063 | OOS n=51 avgR=-0.186 | or_minutes=15 adx_min=20.0 rsi_line=50.0
  WF 2020-01-01..2021-01-01 -> OOS to 2021-04-01: IS n=178 avgR=0.024 | OOS n=47 avgR=0.044 | or_minutes=15 adx_min=20.0 rsi_line=55.0
  WF 2020-04-01..2021-04-01 -> OOS to 2021-07-01: IS n=150 avgR=0.032 | OOS n=37 avgR=0.112 | or_minutes=30 adx_min=20.0 rsi_line=55.0
  WF 2020-07-01..2021-07-01 -> OOS to 2021-10-01: IS n=150 avgR=0.079 | OOS n=41 avgR=-0.122 | or_minutes=30 adx_min=20.0 rsi_line=55.0
  WF 2020-10-01..2021-10-01 -> OOS to 2022-01-01: IS n=160 avgR=-0.017 | OOS n=39 avgR=-0.014 | or_minutes=30 adx_min=20.0 rsi_line=55.0

| IS from | IS to | OOS to | IS n | IS avg R | OOS n | OOS avg R | OOS total R | params |
|---|---|---|---|---|---|---|---|---|
| 2015-01-01 | 2016-01-01 | 2016-04-01 | 101 | 0.177 | 24 | 0.263 | 6.3 | or_minutes=30 adx_min=25.0 rsi_line=50.0 |
| 2015-04-01 | 2016-04-01 | 2016-07-01 | 104 | 0.245 | 22 | -0.197 | -4.3 | or_minutes=30 adx_min=25.0 rsi_line=50.0 |
| 2015-07-01 | 2016-07-01 | 2016-10-01 | 94 | 0.134 | 28 | 0.026 | 0.7 | or_minutes=30 adx_min=25.0 rsi_line=50.0 |
| 2015-10-01 | 2016-10-01 | 2017-01-01 | 97 | 0.124 | 20 | 0.094 | 1.9 | or_minutes=30 adx_min=25.0 rsi_line=55.0 |
| 2016-01-01 | 2017-01-01 | 2017-04-01 | 93 | 0.106 | 23 | -0.340 | -7.8 | or_minutes=30 adx_min=25.0 rsi_line=55.0 |
| 2016-04-01 | 2017-04-01 | 2017-07-01 | 119 | -0.043 | 37 | -0.168 | -6.2 | or_minutes=15 adx_min=25.0 rsi_line=55.0 |
| 2016-07-01 | 2017-07-01 | 2017-10-01 | 101 | -0.106 | 30 | 0.228 | 6.8 | or_minutes=30 adx_min=25.0 rsi_line=55.0 |
| 2016-10-01 | 2017-10-01 | 2018-01-01 | 124 | -0.014 | 34 | -0.150 | -5.1 | or_minutes=15 adx_min=25.0 rsi_line=50.0 |
| 2017-01-01 | 2018-01-01 | 2018-04-01 | 152 | 0.006 | 42 | 0.037 | 1.6 | or_minutes=15 adx_min=20.0 rsi_line=50.0 |
| 2017-04-01 | 2018-04-01 | 2018-07-01 | 139 | 0.072 | 38 | -0.340 | -12.9 | or_minutes=30 adx_min=20.0 rsi_line=50.0 |
| 2017-07-01 | 2018-07-01 | 2018-10-01 | 147 | 0.055 | 34 | -0.103 | -3.5 | or_minutes=15 adx_min=25.0 rsi_line=55.0 |
| 2017-10-01 | 2018-10-01 | 2019-01-01 | 144 | -0.023 | 38 | -0.133 | -5.1 | or_minutes=15 adx_min=25.0 rsi_line=55.0 |
| 2018-01-01 | 2019-01-01 | 2019-04-01 | 140 | -0.033 | 33 | -0.212 | -7.0 | or_minutes=15 adx_min=25.0 rsi_line=50.0 |
| 2018-04-01 | 2019-04-01 | 2019-07-01 | 177 | -0.096 | 43 | 0.090 | 3.9 | or_minutes=15 adx_min=20.0 rsi_line=55.0 |
| 2018-07-01 | 2019-07-01 | 2019-10-01 | 171 | -0.007 | 49 | -0.199 | -9.8 | or_minutes=15 adx_min=20.0 rsi_line=50.0 |
| 2018-10-01 | 2019-10-01 | 2020-01-01 | 174 | -0.017 | 42 | 0.015 | 0.6 | or_minutes=15 adx_min=20.0 rsi_line=55.0 |
| 2019-01-01 | 2020-01-01 | 2020-04-01 | 173 | -0.022 | 40 | 0.182 | 7.3 | or_minutes=15 adx_min=20.0 rsi_line=55.0 |
| 2019-04-01 | 2020-04-01 | 2020-07-01 | 172 | 0.024 | 42 | 0.007 | 0.3 | or_minutes=15 adx_min=20.0 rsi_line=55.0 |
| 2019-07-01 | 2020-07-01 | 2020-10-01 | 171 | 0.003 | 43 | 0.054 | 2.3 | or_minutes=15 adx_min=20.0 rsi_line=55.0 |
| 2019-10-01 | 2020-10-01 | 2021-01-01 | 164 | 0.063 | 51 | -0.186 | -9.5 | or_minutes=15 adx_min=20.0 rsi_line=50.0 |
| 2020-01-01 | 2021-01-01 | 2021-04-01 | 178 | 0.024 | 47 | 0.044 | 2.1 | or_minutes=15 adx_min=20.0 rsi_line=55.0 |
| 2020-04-01 | 2021-04-01 | 2021-07-01 | 150 | 0.032 | 37 | 0.112 | 4.1 | or_minutes=30 adx_min=20.0 rsi_line=55.0 |
| 2020-07-01 | 2021-07-01 | 2021-10-01 | 150 | 0.079 | 41 | -0.122 | -5.0 | or_minutes=30 adx_min=20.0 rsi_line=55.0 |
| 2020-10-01 | 2021-10-01 | 2022-01-01 | 160 | -0.017 | 39 | -0.014 | -0.5 | or_minutes=30 adx_min=20.0 rsi_line=55.0 |

### Pooled out-of-sample
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| OOS cost 0 pts | 877 | 0.035 | 42.3% | 30.6 | 23.1 | 1.08 | 1.5 |
| OOS cost 3 pts | 877 | -0.044 | 41.6% | -38.8 | 56.1 | 0.91 | 1.5 |
| OOS cost 6 pts | 877 | -0.123 | 40.7% | -108.3 | 116.2 | 0.77 | 1.5 |
| OOS cost 10 pts | 877 | -0.229 | 39.1% | -200.8 | 206.9 | 0.62 | 1.5 |
- bootstrap 95% CI of mean R (net 3 pts): [-0.112, 0.024]
- distinct parameter sets chosen across windows: 8 of 24

## Like-for-like: fixed spec params vs walk-forward, same OOS windows (net 3 pts)
- OOS windows: 1444 sessions, 2016-01-04 .. 2021-12-31
| set | n | avg R | 95% CI | win % | total R | max DD R |
|---|---|---|---|---|---|---|
| fixed spec params | 1018 | -0.042 | [-0.108, 0.023] | 41.2% | -42.8 | 55.8 |
| walk-forward (re-chosen) | 877 | -0.044 | [-0.112, 0.024] | 41.6% | -38.8 | 56.1 |
- difference walk-forward minus fixed: -0.002R, 95% CI [-0.098, 0.093]
- parameter selection added measurable value: **no** (CI of the difference includes zero)

## Slice analysis (exploratory; 30 slices examined, Holm-adjusted; full sample, net 3 pts)
| dimension | slice | n | mean R | rest mean R | p raw | p Holm | significant |
|---|---|---|---|---|---|---|---|
| year | 2015 | 168 | -0.004 | -0.042 | 0.680 | 1.000 | no |
| year | 2016 | 157 | -0.048 | -0.035 | 0.889 | 1.000 | no |
| year | 2017 | 152 | 0.006 | -0.043 | 0.591 | 1.000 | no |
| year | 2018 | 175 | -0.065 | -0.032 | 0.698 | 1.000 | no |
| year | 2019 | 175 | -0.064 | -0.032 | 0.719 | 1.000 | no |
| year | 2020 | 174 | 0.012 | -0.045 | 0.528 | 1.000 | no |
| year | 2021 | 185 | -0.085 | -0.028 | 0.498 | 1.000 | no |
| side | LONG | 600 | -0.120 | 0.049 | 0.006 | 0.183 | no |
| side | SHORT | 586 | 0.049 | -0.120 | 0.006 | 0.183 | no |
| adx_at_entry | 20-25 | 381 | -0.042 | -0.034 | 0.913 | 1.000 | no |
| adx_at_entry | 25-30 | 231 | 0.002 | -0.046 | 0.548 | 1.000 | no |
| adx_at_entry | 30+ | 574 | -0.049 | -0.025 | 0.703 | 1.000 | no |
| rsi_at_entry | 40-50 | 222 | 0.031 | -0.052 | 0.287 | 1.000 | no |
| rsi_at_entry | 50-60 | 117 | -0.154 | -0.024 | 0.224 | 1.000 | no |
| rsi_at_entry | <40 | 364 | 0.060 | -0.080 | 0.039 | 1.000 | no |
| rsi_at_entry | >60 | 483 | -0.112 | 0.015 | 0.042 | 1.000 | no |
| or_atr_tercile | T1 | 395 | -0.104 | -0.003 | 0.137 | 1.000 | no |
| or_atr_tercile | T2 | 395 | -0.037 | -0.036 | 0.992 | 1.000 | no |
| or_atr_tercile | T3 | 396 | 0.031 | -0.070 | 0.113 | 1.000 | no |
| gap_vs_side | against | 481 | -0.031 | -0.041 | 0.879 | 1.000 | no |
| gap_vs_side | with | 705 | -0.041 | -0.031 | 0.879 | 1.000 | no |
| weekday | Fri | 236 | -0.032 | -0.038 | 0.947 | 1.000 | no |
| weekday | Mon | 230 | 0.069 | -0.062 | 0.090 | 1.000 | no |
| weekday | Thu | 239 | 0.032 | -0.054 | 0.270 | 1.000 | no |
| weekday | Tue | 238 | -0.102 | -0.020 | 0.297 | 1.000 | no |
| weekday | Wed | 243 | -0.144 | -0.009 | 0.073 | 1.000 | no |
| expiry_day | expiry | 134 | 0.004 | -0.042 | 0.643 | 1.000 | no |
| expiry_day | other | 1052 | -0.042 | 0.004 | 0.643 | 1.000 | no |
| signal_hour | first_hour | 931 | -0.028 | -0.069 | 0.573 | 1.000 | no |
| signal_hour | later | 255 | -0.069 | -0.028 | 0.573 | 1.000 | no |
- **No slice is significant after multiplicity** (30 looks). Weekday, side, year and hour differences are consistent with noise. No slice may be used as a filter in this strategy.

## Regime check: rolling 50-trade hit rate vs a stationary binomial
- trades 1186, hit rate 41.7%, overlapping windows 1137
- observed rolling range: 22% .. 58%
- simulated 95% band for the minimum: 18% .. 30%; for the maximum: 54% .. 68%
- observed range outside the band: **no**. No regime change is supported: the swings are what a constant hit rate produces.

## Go-live gates
| gate | result | detail |
|---|---|---|
| 1 walk-forward OOS net 3 pts: n>=100, avg R>=0.10, CI low>0.02 | **FAIL** | n=877 avgR=-0.044 CI95=[-0.112, 0.024] |
| 2 robustness: avg R>0 at 6 pts; >=60% grid cells positive; stable params | **FAIL** | avgR@6pts=-0.123 grid positive=0/8 (0%) distinct WF param sets=8/24 |
| 3 OOS max drawdown <= 12R | **FAIL** | maxDD=56.1R = Rs 112,146 = 74.8% of Rs 150,000 |
| 4 paper phase: >=30 sessions with alerts + journal, realised vs backtest R within tolerance | **PENDING** | PENDING - paper phase not started |
| 5 live one lot only for >=20 sessions before any size change | **PENDING** | PENDING - after gate 4 |

## Verdict: **FAIL**
- like-for-like: fixed -0.042R vs walk-forward -0.044R, difference CI [-0.098, 0.093]; selection added value: no
- slices significant after multiplicity: 0 of 30
- regime change supported: no
- data 2015-01-01 .. 2021-12-31 is CONSUMED for this strategy family (see hypotheses/ledger.md)

- wrote reports/orbx_nifty_trades.csv (1186 rows), reports/orbx_nifty_oos_trades.csv (877 rows); elapsed 17s
