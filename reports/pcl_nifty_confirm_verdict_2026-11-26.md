# pcl_nifty_confirm verdict 2026-11-26 (commit 2d71f38)

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
