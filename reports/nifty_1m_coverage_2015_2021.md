# nifty_1m coverage  2015-01-01 -> 2021-12-31

- NSE sessions (from NIFTY daily series): **1734**
- sessions with 1-minute bars: **1701**
- missing sessions: **33**  [datetime.date(2016, 1, 1), datetime.date(2016, 3, 14), datetime.date(2016, 5, 18), datetime.date(2016, 5, 19), datetime.date(2016, 5, 23), datetime.date(2016, 6, 29), datetime.date(2016, 8, 2), datetime.date(2016, 10, 3), datetime.date(2016, 10, 28), datetime.date(2016, 11, 3), datetime.date(2016, 11, 9), datetime.date(2016, 11, 21), datetime.date(2017, 1, 9), datetime.date(2017, 1, 11), datetime.date(2017, 1, 20), datetime.date(2017, 1, 23), datetime.date(2017, 1, 24), datetime.date(2017, 1, 25), datetime.date(2017, 1, 30), datetime.date(2017, 1, 31)]
- special/partial sessions (< 70 bars, excluded by the strategy): **5**  [(datetime.date(2016, 10, 30), 63), (datetime.date(2018, 11, 7), 62), (datetime.date(2019, 10, 27), 62), (datetime.date(2020, 11, 14), 62), (datetime.date(2021, 2, 24), 56)]
- short sessions (70..369 bars): **6**  [(datetime.date(2015, 2, 16), 351), (datetime.date(2015, 11, 11), 140), (datetime.date(2017, 7, 10), 208), (datetime.date(2020, 3, 13), 325), (datetime.date(2020, 3, 23), 326), (datetime.date(2021, 1, 11), 272)]
- dates in nifty_1m with no daily bar (special sessions outside the daily series): **0**
- sessions with missing minutes inside the day: **906**  worst [(datetime.date(2021, 2, 24), 328), (datetime.date(2017, 7, 10), 167), (datetime.date(2020, 3, 13), 58), (datetime.date(2020, 3, 23), 57), (datetime.date(2015, 2, 16), 25), (datetime.date(2019, 10, 27), 10), (datetime.date(2018, 11, 27), 10), (datetime.date(2020, 11, 14), 10), (datetime.date(2018, 11, 29), 10), (datetime.date(2018, 11, 7), 8)]
- Breeze calls this run: 0

