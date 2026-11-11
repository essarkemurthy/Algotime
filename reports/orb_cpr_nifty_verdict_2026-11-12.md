# orb_cpr_nifty verdict 2026-11-12 (commit 9397e18)

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
