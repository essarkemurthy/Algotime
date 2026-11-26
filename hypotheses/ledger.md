# Strategy hypothesis ledger

Rules (set 2026-11-12):

1. A new idea starts as `hypotheses/<id>.md` (copy `TEMPLATE.md`) stating the economic reason, exact
   rules, parameters, and the data it will be tested on. It is committed BEFORE anything is run and
   nothing is implemented until the owner approves the file.
2. Data that has been sliced for a strategy family is **consumed** for that family: it may not be used
   to validate a variant. Variants are tested on data not used here, with their own walk-forward.
3. Every variant tried is counted below. The evidence bar rises with the count: the walk-forward
   out-of-sample CI lower bound must clear `0 + 0.02R x (variants already tried in the family)`
   in addition to the standard gates.
4. Exploratory slices (weekday, side, year, hour, ...) are reported with Holm-adjusted p-values
   and never become filters.

## Data availability (checked 2026-11-12)

Breeze `get_historical_data_v2` serves NIFTY 1-minute bars back to at least 2015-01-05 (375 rows per
session returned for 2015, 2017, 2019, 2020, 2021 probes). Pre-2022 data is therefore available as
a fresh test set, with the caveat that 2015-2019 index microstructure (tick size, lot sizes, weekly
expiries from 2019 only) differs from today. A forward held-out period via paper trading remains
the final arbiter (gate 4).

## Families

| family | id | status | data consumed | variants tried | verdict file |
|---|---|---|---|---|---|
| ORB-CPR NIFTY | ORB-CPR-15 (spec of 2026-11-12) | **FAIL**, frozen | nifty_1m 2022-01-03 .. 2026-11-11 (full sample: baseline, 81-cell grid, 16 walk-forward windows, 23 slices) | 1 (spec params; the grid was examined for robustness only) | reports/orb_cpr_nifty_verdict_2026-11-12.md |

| NIFTY intraday long premium | LSTR-0920 (2026-11-20) | DRAFT, awaiting owner approval | none yet (NIFTY ATM weekly option 1m bars, earliest Breeze date .. 2026-11-19, reserved) | 0 | — |
| NIFTY overnight short premium | SOVN-1520 (2026-11-20) | DRAFT, PARKED (margin, short-side engine) | none (shares the LSTR-0920 fetch) | 0 | — |
| NIFTY intraday level system (pivots, CPR, Camarilla) | PCL-15 (owner spec of 2026-11-26) | DRAFT, awaiting owner approval | none yet (nifty_1m 2015-01-05 .. 2021-12-31 reserved as the fresh test set; 2022-2026 confirmation-only because it shares the ORB-CPR gap/OR filters) | 0 | — |
| NIFTY opening-range breakout (variant 2) | ORBX-15 (2026-11-26): ORB + ADX ≥ 20 + RSI side, same exits as ORB-CPR-15 | DRAFT, awaiting owner approval; bar raised to CI lower bound > 0.02 R | none yet (nifty_1m 2015-01-05 .. 2021-12-31 reserved, shared fetch with PCL-15; 2022-2026 confirmation-only) | 0 (family total 1) | — |

No further ORB-CPR variant may be validated on 2022-2026 NIFTY data.

## Evidence reviews

- 2026-11-20 `evidence_options_2026-11-20.md`: SEBI FY25/FY26 loss studies, Bhat-Pandey-Rao (2024) and
  Muravyev-Ni (2020) day/night option-return asymmetry, retail 920-straddle claims, expiry calendar and
  Jan-2026 lot sizes. Conclusion: directional intraday option buying on an unvalidated signal (the
  current engine) and intraday short premium are both ruled out; the two hypotheses above are what the
  evidence leaves standing.
