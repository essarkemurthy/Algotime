# orb_cpr_nifty backtest  2022-01-01 -> 2026-11-12  (generated 2026-11-12 00:44 IST)

- 1-minute rows: 457,431; valid sessions (>= 70 five-minute bars): 1195 (2022-01-03 .. 2026-11-11); sessions with features: 1181
- params: bar_minutes=5, or_minutes=15, session_open=09:15:00, signal_start=09:30:00, signal_end=11:00:00, time_exit=15:15:00, atr_period=14, gap_atr_max=1.0, or_min_atr=0.2, or_max_atr=0.6, cpr_max_pct=0.6, stop_atr_cap=0.5, target_r=1.5, be_trigger_r=1.0, cost_points=3.0, min_session_bars=70, max_chase_atr=0.1

## Baseline (default params) and cost sensitivity
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| cost 0 pts | 670 | 0.047 | 44.0% | 31.2 | 16.8 | 1.11 | 3.6 |
| cost 3 pts | 670 | 0.002 | 43.7% | 1.3 | 25.3 | 1.00 | 3.6 |
| cost 6 pts | 670 | -0.043 | 43.3% | -28.5 | 39.0 | 0.91 | 3.6 |
| cost 10 pts | 670 | -0.102 | 42.7% | -68.4 | 74.0 | 0.80 | 3.6 |

Skips: cpr_too_wide=31, gap_too_large=37, no_breakout=270, no_features=14, or_too_large=37, or_too_small=136; signal days=670 of 1195

## By year (net 3 pts)
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| 2022 | 114 | -0.045 | 40.4% | -5.1 | 9.8 | 0.90 | 0.6 |
| 2023 | 149 | -0.117 | 38.3% | -17.5 | 19.5 | 0.79 | -3.1 |
| 2024 | 127 | 0.078 | 44.9% | 10.0 | 8.9 | 1.18 | 10.9 |
| 2025 | 165 | 0.071 | 46.1% | 11.7 | 6.5 | 1.17 | 3.6 |
| 2026 | 115 | 0.020 | 49.6% | 2.3 | 19.0 | 1.05 | 6.9 |

## Exit reasons (net 3 pts)
| reason | n | avg R |
|---|---|---|
| stop | 275 | -1.047 |
| time | 186 | 0.334 |
| target | 158 | 1.452 |
| be_stop | 51 | -0.047 |
| LONG | 335 | -0.049 |
| SHORT | 335 | 0.053 |

## Parameter grid (full sample, net 3 pts; for robustness only, not selection)
- cells: 81; positive avg R: 58 (72%); grid = {'or_min_atr': (0.15, 0.2, 0.25), 'or_max_atr': (0.5, 0.6, 0.7), 'target_r': (1.0, 1.5, 2.0), 'cpr_max_pct': (0.4, 0.6, 0.8)}
| params | n | avg R | total R | max DD R |
|---|---|---|---|---|
| or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 | 457 | 0.071 | 32.4 | 9.6 |
| or_min_atr=0.25 or_max_atr=0.6 target_r=2.0 cpr_max_pct=0.4 | 489 | 0.067 | 32.8 | 10.2 |
| or_min_atr=0.25 or_max_atr=0.7 target_r=2.0 cpr_max_pct=0.4 | 500 | 0.063 | 31.5 | 10.2 |
| or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4 | 457 | 0.063 | 28.6 | 11.0 |
| or_min_atr=0.25 or_max_atr=0.6 target_r=1.5 cpr_max_pct=0.4 | 489 | 0.059 | 28.7 | 11.5 |
| or_min_atr=0.25 or_max_atr=0.7 target_r=1.5 cpr_max_pct=0.4 | 500 | 0.054 | 26.8 | 11.5 |
| or_min_atr=0.25 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.6 | 487 | 0.045 | 21.9 | 10.6 |
| or_min_atr=0.25 or_max_atr=0.6 target_r=2.0 cpr_max_pct=0.6 | 523 | 0.043 | 22.3 | 11.2 |

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
  WF 2025-01-01..2026-01-01 -> OOS to 2026-04-01: IS n=149 avgR=0.126 | OOS n=26 avgR=0.291 | or_min_atr=0.2 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4
  WF 2025-04-01..2026-04-01 -> OOS to 2026-07-01: IS n=112 avgR=0.228 | OOS n=24 avgR=-0.234 | or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4
  WF 2025-07-01..2026-07-01 -> OOS to 2026-10-01: IS n=163 avgR=0.136 | OOS n=44 avgR=-0.184 | or_min_atr=0.15 or_max_atr=0.7 target_r=2.0 cpr_max_pct=0.6
  WF 2025-10-01..2026-10-01 -> OOS to 2027-01-01: IS n=135 avgR=0.057 | OOS n=11 avgR=0.598 | or_min_atr=0.2 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4

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
| 2025-01-01 | 2026-01-01 | 2026-04-01 | 149 | 0.126 | 26 | 0.291 | 7.6 | or_min_atr=0.2 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 |
| 2025-04-01 | 2026-04-01 | 2026-07-01 | 112 | 0.228 | 24 | -0.234 | -5.6 | or_min_atr=0.25 or_max_atr=0.5 target_r=1.5 cpr_max_pct=0.4 |
| 2025-07-01 | 2026-07-01 | 2026-10-01 | 163 | 0.136 | 44 | -0.184 | -8.1 | or_min_atr=0.15 or_max_atr=0.7 target_r=2.0 cpr_max_pct=0.6 |
| 2025-10-01 | 2026-10-01 | 2027-01-01 | 135 | 0.057 | 11 | 0.598 | 6.6 | or_min_atr=0.2 or_max_atr=0.5 target_r=2.0 cpr_max_pct=0.4 |

### Pooled out-of-sample
| set | n | avg R | win % | total R | max DD R | PF | avg pts |
|---|---|---|---|---|---|---|---|
| OOS cost 0 pts | 454 | 0.069 | 43.4% | 31.5 | 14.4 | 1.16 | 4.5 |
| OOS cost 3 pts | 454 | 0.024 | 43.2% | 11.0 | 16.5 | 1.05 | 4.5 |
| OOS cost 6 pts | 454 | -0.021 | 42.5% | -9.5 | 20.3 | 0.96 | 4.5 |
| OOS cost 10 pts | 454 | -0.081 | 42.1% | -36.9 | 44.8 | 0.84 | 4.5 |
- bootstrap 95% CI of mean R (net 3 pts): [-0.072, 0.121]
- distinct parameter sets chosen across windows: 9 of 16

## Go-live gates
| gate | result | detail |
|---|---|---|
| 1 walk-forward OOS net 3 pts: n>=100, avg R>=0.10, CI low>0 | **FAIL** | n=454 avgR=0.024 CI95=[-0.072, 0.121] |
| 2 robustness: avg R>0 at 6 pts; >=60% grid cells positive; stable params | **FAIL** | avgR@6pts=-0.021 grid positive=58/81 (72%) distinct WF param sets=9/16 |
| 3 OOS max drawdown <= 12R | **FAIL** | maxDD=16.5R = Rs 32,943 = 22.0% of Rs 150,000 |
| 4 paper phase: >=30 sessions with alerts + journal, realised vs backtest R within tolerance | **PENDING** | PENDING - paper phase not started |
| 5 live one lot only for >=20 sessions before any size change | **PENDING** | PENDING - after gate 4 |

- wrote reports/orb_cpr_nifty_trades.csv (670 rows), reports/orb_cpr_nifty_oos_trades.csv (454 rows); elapsed 20s
