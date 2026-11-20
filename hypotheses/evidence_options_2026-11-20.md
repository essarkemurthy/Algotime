# Evidence review: intraday index options, 2026-11-20

Why this file exists: the options paper engine has lost ₹1,12,495 over 13 trades (7.7% hit rate) by buying
ATM options on the volume-less VWAP_TREND index signal. Before any new options strategy is coded, this is
what the published evidence says, with the source quality graded. Each claim carries its source; claims
without a verifiable number are marked as such.

## 1. Where the money goes (regulator data)

| finding | number | source | grade |
|---|---|---|---|
| Individual F&O traders who lost money, FY25 | 91% of ~96 lakh traders; net loss ₹1.05 lakh crore | SEBI study, Jul 2025 (Business Standard, Moneylife) | A (regulator) |
| Same, FY26 | 87.7%; net loss ₹91,685 crore | SEBI study, Nov 2026 (Business Today, Policy Edge) | A |
| Share of individual losses coming from options | 92% | SEBI FY26 study (Policy Edge) | A |
| Share of individuals who are predominantly option **buyers** | 97% | SEBI FY26 behavioural study (Policy Edge) | A |
| Repeat losers | 90-92% of two-year losers lose again in year three | SEBI FY26 (Business Today) | A |

Reading: the crowd that loses is the crowd that buys options intraday and directionally. Our current
engine is a member of that crowd.

## 2. Academic results on when option returns are positive

| finding | source | grade |
|---|---|---|
| S&P 500 options: delta-hedged option returns are **negative overnight and positive intraday**; sellers earn their premium at night | Muravyev & Ni, *J. Financial Economics* 2020 | A (peer-reviewed) |
| NIFTY (NSE, 2017-2020): same sign pattern for **short** Nifty option strategies: positive, significant overnight returns, negative intraday returns; the variance risk premium is mainly compensation for overnight risk; the gap shrinks as moneyness/maturity rise and weakens on jump days | Bhat, Pandey & Nageswara Rao, *J. Futures Markets* 44(8) 2024, DOI 10.1002/fut.22512 | A |
| Straddle intraday returns show the same intraday seasonality as the underlying (CBOE 2010-2018) | Zhang, Notre Dame working paper 2025 | B (working paper) |
| 0DTE SPX: variance risk premia driven by high-frequency intraday returns; index 0DTE VRP small (SPX mean 0.0028/day) | Almeida et al. (Derivatives 2025 conf.); OptionMetrics 0DTE note | B |
| Short-term VRP in SPX has become concentrated in calendar patterns (1-DTE put writes 2018-2025) | OptionMetrics note 2025 | B (vendor research) |

Reading: the only peer-reviewed NIFTY result says a **short** option position makes money **overnight**
and loses **intraday**. Equivalently, a **long** position (what our engine can do) has positive expected
return **intraday** and negative overnight. The sizes of those returns, net of Indian retail costs, are
not reported in the abstracts and must be measured on our data.

## 3. Retail "920 straddle" family (intraday short premium)

| claim | source | grade |
|---|---|---|
| 9:20 short straddle, Bank Nifty 2017-2023, 25-70% leg stops: "60-80% annualised" | Medium posts (amit179) | D (self-reported, no costs, survivorship) |
| Edge has decayed as sellers crowded in; "straddlers are being gamed" | marketcalls.in | C (commentary) |
| 9:30 NIFTY short strangle, 40 parameter sets, tight 0.5% stop: **every variant lost** | Medium (stackademic) | C (single author, but a negative result) |
| NIFTY intraday iron fly: expectancy −₹295/day, profit factor 0.47 | TradesViz backtest page | C (vendor, parameters fixed by vendor) |
| Short-straddle margin now ₹1.6-2.3 lakh per NIFTY lot (65) incl. expiry-day ELM | Aliceblue 2026 guide, broker calculators | B |

Reading: consistent with the academic result. Intraday short premium is at best crowded and marginal,
needs ₹1.6 lakh+ margin per lot, and is unfundable on an account with ₹7,900 usable.

## 4. Market structure facts that any backtest must get right

| fact | source |
|---|---|
| NIFTY weekly expiry **Tuesday** (from the 2-Sep-2025 series; Thursday before); SENSEX weekly **Thursday**; one weekly index per exchange since 20-Nov-2024; holiday → previous trading day | NSE/BSE circulars via Business Standard, Zerodha support |
| Lot sizes from the Jan-2026 series: NIFTY 65, BANKNIFTY 30, FINNIFTY 60, MIDCPNIFTY 120, SENSEX 20 | NSE circular via Kotak, HDFC Sky, Zerodha (fixed in code 2026-11-20) |
| Breeze historical option candles: NIFTY only (others live-only) | this repo, memory note |
| Breeze is a single-session API: a history fetch must run inside the app's session or while the app is down | this repo, memory note |

## 5. What this rules out and what it leaves

Ruled out by evidence:
- Directional intraday option buying on an unvalidated index signal (current engine). Negative in theory
  (no edge in the signal) and in our record (−₹1.12 lakh).
- Intraday short straddle/strangle for this account: academic sign is negative intraday, retail evidence
  mixed-to-negative after costs, margin unfundable.

Left standing, each as a pre-registered hypothesis in this folder:
- **LSTR-0920**: long ATM straddle, buy after the open, sell before the close, no directional view. Tests
  the Bhat-Pandey-Rao intraday sign directly, fits the long-only engine, defined risk = premium paid.
- **SOVN-1520**: short ATM straddle overnight (sell 15:20, buy back 09:20). The documented positive side of
  the same asymmetry. Parked: needs ₹1.6 lakh+ margin per lot, a short-side engine, and gap-risk limits.

Neither is "expected to work". Each is a claim with a bar to clear on data that nobody in this repo has
looked at for this purpose.

## Sources

- SEBI FY25 study coverage: https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html ; https://moneylife.in/article/91-percentage-of-retail-traders-lost-money-in-derivatives-losses-in-fo-surged-41-percentage-to-rs105-lakh-crore-in-fy25-sebi-study/77613.html
- SEBI FY26 coverage: https://www.businesstoday.in/personal-finance/story/87-7-of-fo-traders-lost-money-in-fy26-despite-sebi-curbs-why-retail-investors-keep-losing-567419-2026-11-14 ; https://www.policyedge.in/p/nearly-9-in-10-individual-fo-traders-lost-money-as-participation-fell-18-sebi-studies
- Bhat, Pandey, Nageswara Rao (2024): https://ideas.repec.org/a/wly/jfutmk/v44y2024i8p1320-1337.html
- Muravyev & Ni (2020): https://ideas.repec.org/a/eee/jfinec/v136y2020i1p219-238.html
- Zhang (2025) intraday option seasonality: https://www3.nd.edu/~zda/IntraOption.pdf
- 0DTE VRP: https://fmai.memberclicks.net/assets/docs/Derivatives2025/Almeida.pdf ; https://optionmetrics.com/?p=3155 ; https://optionmetrics.com/?p=2992
- 920 straddle family: https://medium.com/@amit179.iitk2/the-920-short-straddle-intraday-trading-strategy-ba2f1082c57f ; https://www.marketcalls.in/futures-and-options/is-the-920-straddle-no-more-working.html ; https://blog.stackademic.com/i-backtested-the-9-30-nifty-short-strangle-40-different-ways-every-single-one-lost-money-513911e32f24 ; https://www.tradesviz.com/options-backtests/nifty-iron-fly/
- Expiry days: https://www.business-standard.com/amp/markets/news/nse-bids-adieu-to-thursday-expiry-as-dates-swap-come-into-effect-explained-125082800635_1.html ; https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/weekly-expiries-discontinued-for-certain-index-derivatives
- Lot sizes: https://hdfcsky.com/news/nse-revises-market-lot-sizes-for-major-index-derivatives-effective-january-2026 ; https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/lot-size-for-index-derivatives
- Margin: https://aliceblueonline.com/blog/fo-margin-requirements-india-2026
