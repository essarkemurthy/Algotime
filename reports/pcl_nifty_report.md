# pcl_nifty backtest  2015-01-01 -> 2021-12-31  (generated 2026-11-26 12:04 IST, commit 2d71f38)

- 1-minute rows: 637,670; valid sessions (>= 23 five-minute bars, weekdays): 1692 (2015-01-01 .. 2021-12-31); sessions with features: 1678
- params: bar_minutes=15, session_open=09:15:00, signal_start=09:30:00, signal_end=14:30:00, time_exit=15:00:00, atr_period=14, adx_period=14, rsi_period=14, gap_atr=1.0, or_atr=0.2, adx_min=20.0, rsi_mid=50.0, buffer_atr=0.15, round_step=100, merge_atr=0.05, risk_min_atr=0.1, risk_max_atr=1.0, rr_min=2.0, max_entries=2, cost_points=3.0, min_session_bars=23, exclude_weekends=True

## Day-filter funnel and data sanity
| step | sessions |
|---|---|
| sessions in 1m data | 1701 |
| - weekend special sessions | 4 |
| - fewer than 23 bars of 15 min | 7 |
| = valid sessions | 1692 |
| - no features (warm-up) | 14 |
| = evaluable sessions | 1678 |
| - skip no_signal | 767 |
| - skip rr_too_low | 775 |
| - skip risk_out_of_band | 1 |
| - skip no_level_below | 0 |
| - skip no_t2 | 603 |
| - skip no_next_bar | 0 |
| - skip no_features | 14 |
| = sessions with at least one trade | 352 |
| = trades taken | 419 |

- survivors of every filter == trades: **yes** (352 vs 419)
- duplicate 1-minute timestamps: 0
- valid sessions whose first 5m bar is not 09:15: 0
- weekend special sessions excluded: 4  ['2015-02-28', '2016-10-30', '2019-10-27', '2020-11-14']
- weekday sessions excluded for < 23 five-minute bars: 7  ['2015-11-11', '2017-07-10', '2018-11-07', '2020-03-13', '2020-03-23', '2021-01-11', '2021-02-24']
- trades by year: {2015: 44, 2016: 46, 2017: 43, 2018: 62, 2019: 64, 2020: 57, 2021: 103}

## Baseline (default params) and cost sensitivity
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| cost 0 pts | 419 | 0.018 | 45.8% | 7.6 | 19.3 | 1.04 | -0.1 |
| cost 3 pts | 419 | -0.105 | 41.5% | -44.2 | 57.8 | 0.78 | -0.1 |
| cost 6 pts | 419 | -0.229 | 36.5% | -95.9 | 103.9 | 0.59 | -0.1 |
| cost 10 pts | 419 | -0.394 | 31.3% | -164.9 | 166.9 | 0.41 | -0.1 |

Skips: no_features=14, no_signal=767, no_t2=603, risk_out_of_band=1, rr_too_low=775; signal days=419 of 1692

## By year (net 3 pts; descriptive, see slice table for significance)
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| 2015 | 44 | 0.291 | 50.0% | 12.8 | 2.7 | 1.88 | 9.3 |
| 2016 | 46 | -0.287 | 37.0% | -13.2 | 13.2 | 0.43 | -3.0 |
| 2017 | 43 | -0.108 | 39.5% | -4.7 | 10.7 | 0.80 | 2.3 |
| 2018 | 62 | -0.046 | 43.5% | -2.8 | 10.3 | 0.91 | 2.8 |
| 2019 | 64 | -0.154 | 40.6% | -9.9 | 13.2 | 0.62 | -0.8 |
| 2020 | 57 | -0.194 | 36.8% | -11.0 | 15.9 | 0.65 | -4.4 |
| 2021 | 103 | -0.149 | 42.7% | -15.4 | 18.1 | 0.69 | -2.8 |

## Exit reasons (net 3 pts; conditioned on outcome, descriptive only)
| reason | n | avg R |
|---|---|---|
| stop/stop | 154 | -1.125 |
| T1/trail | 127 | 0.171 |
| T1/time | 68 | 0.757 |
| time/time | 41 | 0.160 |
| T1/T2 | 29 | 1.701 |

Target and stop buckets are positive/negative by construction and the time-exit bucket is selected on having avoided both; none of these is evidence for a variant.

## Parameter grid (full sample, net 3 pts; for robustness only, not selection)
- cells: 36; positive avg R: 0 (0%); grid = {'gap_atr': (0.75, 1.0), 'or_atr': (0.15, 0.2, 0.25), 'adx_min': (20.0, 25.0), 'buffer_atr': (0.1, 0.15, 0.2)}
| params | n | avg R | total R | max DD R |
|---|---|---|---|---|
| gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2 | 212 | -0.048 | -10.1 | 19.7 |
| gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 | 265 | -0.052 | -13.9 | 20.8 |
| gap_atr=0.75 or_atr=0.15 adx_min=20.0 buffer_atr=0.2 | 334 | -0.058 | -19.2 | 30.5 |
| gap_atr=1.0 or_atr=0.15 adx_min=20.0 buffer_atr=0.2 | 334 | -0.058 | -19.2 | 30.5 |
| gap_atr=1.0 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 | 262 | -0.059 | -15.4 | 19.8 |
| gap_atr=1.0 or_atr=0.25 adx_min=25.0 buffer_atr=0.2 | 210 | -0.060 | -12.6 | 19.7 |
| gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2 | 302 | -0.075 | -22.6 | 30.0 |
| gap_atr=1.0 or_atr=0.2 adx_min=20.0 buffer_atr=0.2 | 302 | -0.075 | -22.6 | 30.0 |

## Walk-forward (12m in-sample / 3m out-of-sample, step 3m)
  WF 2015-01-01..2016-01-01 -> OOS to 2016-04-01: IS n=44 avgR=0.291 | OOS n=16 avgR=-0.497 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.15
  WF 2015-04-01..2016-04-01 -> OOS to 2016-07-01: IS n=53 avgR=0.096 | OOS n=15 avgR=0.103 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.15
  WF 2015-07-01..2016-07-01 -> OOS to 2016-10-01: IS n=42 avgR=0.038 | OOS n=4 avgR=-0.511 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2
  WF 2015-10-01..2016-10-01 -> OOS to 2017-01-01: IS n=38 avgR=-0.088 | OOS n=8 avgR=-0.417 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2
  WF 2016-01-01..2017-01-01 -> OOS to 2017-04-01: IS n=37 avgR=-0.205 | OOS n=2 avgR=0.649 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2
  WF 2016-04-01..2017-04-01 -> OOS to 2017-07-01: IS n=20 avgR=-0.038 | OOS n=9 avgR=-0.322 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2016-07-01..2017-07-01 -> OOS to 2017-10-01: IS n=20 avgR=-0.169 | OOS n=10 avgR=0.443 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2016-10-01..2017-10-01 -> OOS to 2018-01-01: IS n=23 avgR=0.138 | OOS n=6 avgR=-0.026 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2
  WF 2017-01-01..2018-01-01 -> OOS to 2018-04-01: IS n=26 avgR=0.176 | OOS n=5 avgR=-0.743 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2
  WF 2017-04-01..2018-04-01 -> OOS to 2018-07-01: IS n=31 avgR=-0.062 | OOS n=9 avgR=-0.330 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2017-07-01..2018-07-01 -> OOS to 2018-10-01: IS n=52 avgR=-0.050 | OOS n=15 avgR=0.286 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.15
  WF 2017-10-01..2018-10-01 -> OOS to 2019-01-01: IS n=54 avgR=0.018 | OOS n=10 avgR=0.321 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.15
  WF 2018-01-01..2019-01-01 -> OOS to 2019-04-01: IS n=53 avgR=0.036 | OOS n=18 avgR=-0.361 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.15
  WF 2018-04-01..2019-04-01 -> OOS to 2019-07-01: IS n=43 avgR=0.090 | OOS n=9 avgR=0.119 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2018-07-01..2019-07-01 -> OOS to 2019-10-01: IS n=43 avgR=0.184 | OOS n=17 avgR=-0.099 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2
  WF 2018-10-01..2019-10-01 -> OOS to 2020-01-01: IS n=35 avgR=0.070 | OOS n=7 avgR=0.105 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2
  WF 2019-01-01..2020-01-01 -> OOS to 2020-04-01: IS n=57 avgR=0.028 | OOS n=6 avgR=-0.139 | gap_atr=0.75 or_atr=0.15 adx_min=20.0 buffer_atr=0.2
  WF 2019-04-01..2020-04-01 -> OOS to 2020-07-01: IS n=50 avgR=-0.023 | OOS n=15 avgR=-0.065 | gap_atr=0.75 or_atr=0.15 adx_min=20.0 buffer_atr=0.2
  WF 2019-07-01..2020-07-01 -> OOS to 2020-10-01: IS n=74 avgR=-0.002 | OOS n=17 avgR=-0.372 | gap_atr=0.75 or_atr=0.15 adx_min=25.0 buffer_atr=0.1
  WF 2019-10-01..2020-10-01 -> OOS to 2021-01-01: IS n=77 avgR=-0.023 | OOS n=18 avgR=-0.227 | gap_atr=0.75 or_atr=0.2 adx_min=25.0 buffer_atr=0.1
  WF 2020-01-01..2021-01-01 -> OOS to 2021-04-01: IS n=75 avgR=-0.069 | OOS n=35 avgR=0.428 | gap_atr=0.75 or_atr=0.2 adx_min=25.0 buffer_atr=0.1
  WF 2020-04-01..2021-04-01 -> OOS to 2021-07-01: IS n=91 avgR=0.132 | OOS n=24 avgR=-0.130 | gap_atr=0.75 or_atr=0.15 adx_min=25.0 buffer_atr=0.1
  WF 2020-07-01..2021-07-01 -> OOS to 2021-10-01: IS n=95 avgR=0.064 | OOS n=20 avgR=-0.474 | gap_atr=0.75 or_atr=0.2 adx_min=25.0 buffer_atr=0.1
  WF 2020-10-01..2021-10-01 -> OOS to 2022-01-01: IS n=47 avgR=0.064 | OOS n=16 avgR=-0.160 | gap_atr=0.75 or_atr=0.15 adx_min=25.0 buffer_atr=0.2

| IS from | IS to | OOS to | IS n | IS avg R | OOS n | OOS avg R | OOS total R | params |
|---|---|---|---|---|---|---|---|---|
| 2015-01-01 | 2016-01-01 | 2016-04-01 | 44 | 0.291 | 16 | -0.497 | -8.0 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.15 |
| 2015-04-01 | 2016-04-01 | 2016-07-01 | 53 | 0.096 | 15 | 0.103 | 1.5 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.15 |
| 2015-07-01 | 2016-07-01 | 2016-10-01 | 42 | 0.038 | 4 | -0.511 | -2.0 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2 |
| 2015-10-01 | 2016-10-01 | 2017-01-01 | 38 | -0.088 | 8 | -0.417 | -3.3 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2 |
| 2016-01-01 | 2017-01-01 | 2017-04-01 | 37 | -0.205 | 2 | 0.649 | 1.3 | gap_atr=0.75 or_atr=0.2 adx_min=20.0 buffer_atr=0.2 |
| 2016-04-01 | 2017-04-01 | 2017-07-01 | 20 | -0.038 | 9 | -0.322 | -2.9 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2016-07-01 | 2017-07-01 | 2017-10-01 | 20 | -0.169 | 10 | 0.443 | 4.4 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2016-10-01 | 2017-10-01 | 2018-01-01 | 23 | 0.138 | 6 | -0.026 | -0.2 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2 |
| 2017-01-01 | 2018-01-01 | 2018-04-01 | 26 | 0.176 | 5 | -0.743 | -3.7 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2 |
| 2017-04-01 | 2018-04-01 | 2018-07-01 | 31 | -0.062 | 9 | -0.330 | -3.0 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2017-07-01 | 2018-07-01 | 2018-10-01 | 52 | -0.050 | 15 | 0.286 | 4.3 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.15 |
| 2017-10-01 | 2018-10-01 | 2019-01-01 | 54 | 0.018 | 10 | 0.321 | 3.2 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.15 |
| 2018-01-01 | 2019-01-01 | 2019-04-01 | 53 | 0.036 | 18 | -0.361 | -6.5 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.15 |
| 2018-04-01 | 2019-04-01 | 2019-07-01 | 43 | 0.090 | 9 | 0.119 | 1.1 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2018-07-01 | 2019-07-01 | 2019-10-01 | 43 | 0.184 | 17 | -0.099 | -1.7 | gap_atr=0.75 or_atr=0.25 adx_min=20.0 buffer_atr=0.2 |
| 2018-10-01 | 2019-10-01 | 2020-01-01 | 35 | 0.070 | 7 | 0.105 | 0.7 | gap_atr=0.75 or_atr=0.25 adx_min=25.0 buffer_atr=0.2 |
| 2019-01-01 | 2020-01-01 | 2020-04-01 | 57 | 0.028 | 6 | -0.139 | -0.8 | gap_atr=0.75 or_atr=0.15 adx_min=20.0 buffer_atr=0.2 |
| 2019-04-01 | 2020-04-01 | 2020-07-01 | 50 | -0.023 | 15 | -0.065 | -1.0 | gap_atr=0.75 or_atr=0.15 adx_min=20.0 buffer_atr=0.2 |
| 2019-07-01 | 2020-07-01 | 2020-10-01 | 74 | -0.002 | 17 | -0.372 | -6.3 | gap_atr=0.75 or_atr=0.15 adx_min=25.0 buffer_atr=0.1 |
| 2019-10-01 | 2020-10-01 | 2021-01-01 | 77 | -0.023 | 18 | -0.227 | -4.1 | gap_atr=0.75 or_atr=0.2 adx_min=25.0 buffer_atr=0.1 |
| 2020-01-01 | 2021-01-01 | 2021-04-01 | 75 | -0.069 | 35 | 0.428 | 15.0 | gap_atr=0.75 or_atr=0.2 adx_min=25.0 buffer_atr=0.1 |
| 2020-04-01 | 2021-04-01 | 2021-07-01 | 91 | 0.132 | 24 | -0.130 | -3.1 | gap_atr=0.75 or_atr=0.15 adx_min=25.0 buffer_atr=0.1 |
| 2020-07-01 | 2021-07-01 | 2021-10-01 | 95 | 0.064 | 20 | -0.474 | -9.5 | gap_atr=0.75 or_atr=0.2 adx_min=25.0 buffer_atr=0.1 |
| 2020-10-01 | 2021-10-01 | 2022-01-01 | 47 | 0.064 | 16 | -0.160 | -2.6 | gap_atr=0.75 or_atr=0.15 adx_min=25.0 buffer_atr=0.2 |

### Pooled out-of-sample
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| OOS cost 0 pts | 311 | 0.030 | 48.6% | 9.4 | 13.9 | 1.08 | 1.2 |
| OOS cost 3 pts | 311 | -0.087 | 43.1% | -27.1 | 30.7 | 0.81 | 1.2 |
| OOS cost 6 pts | 311 | -0.204 | 36.3% | -63.6 | 63.6 | 0.62 | 1.2 |
| OOS cost 10 pts | 311 | -0.361 | 32.2% | -112.2 | 112.2 | 0.44 | 1.2 |
- bootstrap 95% CI of mean R (net 3 pts): [-0.202, 0.034]
- distinct parameter sets chosen across windows: 9 of 24

## Like-for-like: fixed spec params vs walk-forward, same OOS windows (net 3 pts)
- OOS windows: 1446 sessions, 2016-01-04 .. 2021-12-31
| set | n | avg R | 95% CI | win % | total R | max DD R |
|---|---|---|---|---|---|---|
| fixed spec params | 375 | -0.152 | [-0.255, -0.046] | 40.5% | -57.0 | 57.0 |
| walk-forward (re-chosen) | 311 | -0.087 | [-0.202, 0.034] | 43.1% | -27.1 | 30.7 |
- difference walk-forward minus fixed: 0.065R, 95% CI [-0.084, 0.220]
- parameter selection added measurable value: **no** (CI of the difference includes zero)

## Slice analysis (exploratory; 31 slices examined, Holm-adjusted; full sample, net 3 pts)
| dimension | slice | n | mean R | rest mean R | p raw | p Holm | significant |
|---|---|---|---|---|---|---|---|
| year | 2015 | 44 | 0.291 | -0.152 | 0.016 | 0.498 | no |
| year | 2016 | 46 | -0.287 | -0.083 | 0.157 | 1.000 | no |
| year | 2017 | 43 | -0.108 | -0.105 | 0.986 | 1.000 | no |
| year | 2018 | 62 | -0.046 | -0.116 | 0.649 | 1.000 | no |
| year | 2019 | 64 | -0.154 | -0.097 | 0.620 | 1.000 | no |
| year | 2020 | 57 | -0.194 | -0.092 | 0.483 | 1.000 | no |
| year | 2021 | 103 | -0.149 | -0.091 | 0.594 | 1.000 | no |
| day_type | RANGE | 35 | 0.082 | -0.123 | 0.191 | 1.000 | no |
| day_type | TREND | 384 | -0.123 | 0.082 | 0.191 | 1.000 | no |
| side | LONG | 200 | -0.114 | -0.097 | 0.862 | 1.000 | no |
| side | SHORT | 219 | -0.097 | -0.114 | 0.862 | 1.000 | no |
| level_type | camarilla | 22 | 0.070 | -0.115 | 0.344 | 1.000 | no |
| level_type | pivot | 242 | -0.162 | -0.029 | 0.194 | 1.000 | no |
| level_type | round | 155 | -0.042 | -0.142 | 0.354 | 1.000 | no |
| bias_at_entry | -1 | 210 | -0.090 | -0.121 | 0.755 | 1.000 | no |
| bias_at_entry | 0 | 30 | 0.033 | -0.116 | 0.375 | 1.000 | no |
| bias_at_entry | 1 | 179 | -0.147 | -0.075 | 0.463 | 1.000 | no |
| weekday | Fri | 81 | -0.230 | -0.076 | 0.183 | 1.000 | no |
| weekday | Mon | 81 | 0.025 | -0.137 | 0.234 | 1.000 | no |
| weekday | Thu | 84 | -0.160 | -0.092 | 0.566 | 1.000 | no |
| weekday | Tue | 84 | -0.133 | -0.099 | 0.781 | 1.000 | no |
| weekday | Wed | 89 | -0.033 | -0.125 | 0.446 | 1.000 | no |
| expiry_day | expiry | 49 | -0.081 | -0.109 | 0.834 | 1.000 | no |
| expiry_day | other | 370 | -0.109 | -0.081 | 0.834 | 1.000 | no |
| gap_vs_side | against | 170 | -0.127 | -0.091 | 0.723 | 1.000 | no |
| gap_vs_side | with | 249 | -0.091 | -0.127 | 0.723 | 1.000 | no |
| or_atr_tercile | T1 | 140 | -0.158 | -0.079 | 0.428 | 1.000 | no |
| or_atr_tercile | T2 | 139 | -0.136 | -0.090 | 0.661 | 1.000 | no |
| or_atr_tercile | T3 | 140 | -0.023 | -0.147 | 0.263 | 1.000 | no |
| entry_seq | 1 | 352 | -0.074 | -0.269 | 0.123 | 1.000 | no |
| entry_seq | 2 | 67 | -0.269 | -0.074 | 0.123 | 1.000 | no |
- **No slice is significant after multiplicity** (31 looks). Weekday, side, year and hour differences are consistent with noise. No slice may be used as a filter in this strategy.

## Regime check: rolling 50-trade hit rate vs a stationary binomial
- trades 419, hit rate 41.5%, overlapping windows 370
- observed rolling range: 32% .. 50%
- simulated 95% band for the minimum: 20% .. 34%; for the maximum: 48% .. 64%
- observed range outside the band: **no**. No regime change is supported: the swings are what a constant hit rate produces.

## Go-live gates
| gate | result | detail |
|---|---|---|
| 1 walk-forward OOS net 3 pts: n>=100, avg R>=0.10, CI low>0 | **FAIL** | n=311 avgR=-0.087 CI95=[-0.202, 0.034] |
| 2 robustness: avg R>0 at 6 pts; >=60% grid cells positive; stable params | **FAIL** | avgR@6pts=-0.204 grid positive=0/36 (0%) distinct WF param sets=9/24 |
| 3 OOS max drawdown <= 12R | **FAIL** | maxDD=30.7R = Rs 61,333 = 40.9% of Rs 150,000 |
| 4 paper phase: >=30 sessions with alerts + journal, realised vs backtest R within tolerance | **PENDING** | PENDING - paper phase not started |
| 5 live one lot only for >=20 sessions before any size change | **PENDING** | PENDING - after gate 4 |

## Verdict: **FAIL**
- like-for-like: fixed -0.152R vs walk-forward -0.087R, difference CI [-0.084, 0.220]; selection added value: no
- slices significant after multiplicity: 0 of 31
- regime change supported: no
- data 2015-01-01 .. 2021-12-31 is CONSUMED for this strategy family (see hypotheses/ledger.md)

- wrote reports/pcl_nifty_trades.csv (419 rows), reports/pcl_nifty_oos_trades.csv (311 rows); elapsed 25s
