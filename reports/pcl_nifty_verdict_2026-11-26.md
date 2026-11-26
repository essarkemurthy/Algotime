# pcl_nifty verdict 2026-11-26 (commit 2d71f38)

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
