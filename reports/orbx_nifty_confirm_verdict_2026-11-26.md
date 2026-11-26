# orbx_nifty_confirm verdict 2026-11-26 (commit 2d71f38)

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
