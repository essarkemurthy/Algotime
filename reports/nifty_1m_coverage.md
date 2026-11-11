# nifty_1m coverage  2022-01-01 -> 2026-11-12

- NSE sessions (from NIFTY daily series): **1205**
- sessions with 1-minute bars: **1200**
- missing sessions: **5**  [datetime.date(2022, 3, 29), datetime.date(2022, 3, 30), datetime.date(2022, 3, 31), datetime.date(2022, 6, 14), datetime.date(2022, 10, 24)]
- special/partial sessions (< 70 bars, excluded by the strategy): **0**
- short sessions (70..369 bars): **6**  [(datetime.date(2022, 3, 7), 336), (datetime.date(2023, 11, 12), 106), (datetime.date(2024, 3, 2), 212), (datetime.date(2024, 5, 18), 241), (datetime.date(2024, 11, 1), 248), (datetime.date(2026, 11, 8), 76)]
- dates in nifty_1m with no daily bar (special sessions outside the daily series): **0**
- sessions with missing minutes inside the day: **224**  worst [(datetime.date(2025, 7, 11), 90), (datetime.date(2026, 11, 8), 83), (datetime.date(2025, 6, 20), 80), (datetime.date(2025, 7, 4), 80), (datetime.date(2022, 3, 7), 47), (datetime.date(2024, 11, 1), 17), (datetime.date(2026, 11, 9), 10), (datetime.date(2026, 10, 26), 10), (datetime.date(2026, 10, 29), 10), (datetime.date(2026, 10, 27), 9)]
- Breeze calls this run: 27
