# orbx_nifty verdict 2026-11-26 (commit 2d71f38)

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
