"""trade_engine/option_strategies.py — Multi-leg option strategy builders.

Each builder returns a dict with:
  legs          — list of Leg dicts (action, right, strike, product, qty)
  description   — human-readable label
  max_profit    — theoretical max profit per lot (before actual premiums)
  max_loss      — theoretical max loss per lot (before actual premiums)
  break_even_lower / break_even_upper — indicative strikes
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Leg:
    action:  str            # buy | sell
    product: str            # options | futures | cash
    right:   Optional[str]  # CE | PE | None
    strike:  Optional[int]  # None for futures/cash
    qty:     int
    label:   str            # display label

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ── Strike step & lot-size tables ────────────────────────────────────────────

STRIKE_STEPS: dict = {
    "NIFTY":      50,  "BANKNIFTY":  100, "FINNIFTY":   50,
    "MIDCPNIFTY": 25,  "SENSEX":     100,
    "RELIANCE":   50,  "TCS":        50,  "HDFCBANK":   10,
    "INFY":       20,  "ICICIBANK":  10,  "SBIN":       5,
    "BHARTIARTL": 10,  "KOTAKBANK":  10,  "AXISBANK":   10,
    "LT":         50,  "WIPRO":      5,   "MARUTI":     100,
    "NTPC":       5,   "ONGC":       5,   "TATAMOTORS": 10,
}

LOT_SIZES: dict = {
    "NIFTY":      75,  "BANKNIFTY":  30,  "FINNIFTY":   40,
    "MIDCPNIFTY": 50,  "SENSEX":     20,
    "RELIANCE":   250, "TCS":        150, "HDFCBANK":   550,
    "INFY":       300, "ICICIBANK":  700, "SBIN":       1500,
    "BHARTIARTL": 1851,"KOTAKBANK":  400, "AXISBANK":   625,
    "LT":         375, "WIPRO":      3000,"MARUTI":     15,
    "NTPC":       2700,"ONGC":       1925,"TATAMOTORS": 1425,
}


def _atm(spot: float, step: int) -> int:
    return round(spot / step) * step


# ── 1. Iron Condor ────────────────────────────────────────────────────────────

def iron_condor(spot: float, step: int, lots: int, lot_size: int,
                short_steps: int = 2, width_steps: int = 2) -> dict:
    """
    Sell OTM call spread + sell OTM put spread.
    short_steps : distance (in strike steps) of short strikes from ATM
    width_steps : distance between short and long strikes (defines max loss)
    Net credit strategy — max profit = credit collected.
    """
    atm = _atm(spot, step)
    qty = lots * lot_size

    sp = atm - short_steps * step          # short put
    lp = sp  - width_steps * step          # long  put
    sc = atm + short_steps * step          # short call
    lc = sc  + width_steps * step          # long  call

    legs = [
        Leg("sell", "options", "PE", sp, qty, f"Sell {sp}PE"),
        Leg("buy",  "options", "PE", lp, qty, f"Buy  {lp}PE"),
        Leg("sell", "options", "CE", sc, qty, f"Sell {sc}CE"),
        Leg("buy",  "options", "CE", lc, qty, f"Buy  {lc}CE"),
    ]
    return dict(
        legs=legs, atm=atm,
        break_even_lower=sp, break_even_upper=sc,
        max_profit_unit=None,  # = net credit (known after fills)
        max_loss_unit=width_steps * step,
        description=f"Iron Condor {lp}P/{sp}P/{sc}C/{lc}C ×{lots}L",
        strikes=[lp, sp, sc, lc],
    )


# ── 2. Bull Call Spread ───────────────────────────────────────────────────────

def bull_call_spread(spot: float, step: int, lots: int, lot_size: int,
                     width_steps: int = 2) -> dict:
    """
    Buy lower-strike CE + sell higher-strike CE.
    Debit strategy — bullish view, defined risk/reward.
    Max profit = spread width − debit paid.
    """
    atm = _atm(spot, step)
    qty = lots * lot_size
    bs  = atm                              # buy  strike (ATM)
    ss  = atm + width_steps * step         # sell strike (OTM)

    legs = [
        Leg("buy",  "options", "CE", bs, qty, f"Buy  {bs}CE"),
        Leg("sell", "options", "CE", ss, qty, f"Sell {ss}CE"),
    ]
    return dict(
        legs=legs, atm=atm,
        break_even_lower=None, break_even_upper=ss,
        max_profit_unit=width_steps * step,
        max_loss_unit=None,  # = debit paid
        description=f"Bull Call Spread {bs}CE/{ss}CE ×{lots}L",
        strikes=[bs, ss],
    )


# ── 3. Bear Put Spread ────────────────────────────────────────────────────────

def bear_put_spread(spot: float, step: int, lots: int, lot_size: int,
                    width_steps: int = 2) -> dict:
    """
    Buy higher-strike PE + sell lower-strike PE.
    Debit strategy — bearish view, defined risk/reward.
    Max profit = spread width − debit paid.
    """
    atm = _atm(spot, step)
    qty = lots * lot_size
    bs  = atm                              # buy  strike (ATM)
    ss  = atm - width_steps * step         # sell strike (OTM)

    legs = [
        Leg("buy",  "options", "PE", bs, qty, f"Buy  {bs}PE"),
        Leg("sell", "options", "PE", ss, qty, f"Sell {ss}PE"),
    ]
    return dict(
        legs=legs, atm=atm,
        break_even_lower=ss, break_even_upper=None,
        max_profit_unit=width_steps * step,
        max_loss_unit=None,
        description=f"Bear Put Spread {bs}PE/{ss}PE ×{lots}L",
        strikes=[ss, bs],
    )


# ── 4. Covered Call ───────────────────────────────────────────────────────────

def covered_call(spot: float, step: int, lots: int, lot_size: int,
                 otm_steps: int = 2) -> dict:
    """
    Buy underlying (futures for indices) + sell OTM call.
    Generates premium income; caps upside above the call strike.
    """
    atm = _atm(spot, step)
    qty = lots * lot_size
    cs  = atm + otm_steps * step           # call strike

    legs = [
        Leg("buy",  "futures", None, None, qty, "Buy  Futures"),
        Leg("sell", "options", "CE", cs,   qty, f"Sell {cs}CE"),
    ]
    return dict(
        legs=legs, atm=atm,
        break_even_lower=None, break_even_upper=cs,
        max_profit_unit=otm_steps * step,  # approximate (futures gain to strike)
        max_loss_unit=None,                # theoretically unlimited downside
        description=f"Covered Call  Fut + {cs}CE ×{lots}L",
        strikes=[atm, cs],
    )


# ── 5. Long Straddle ──────────────────────────────────────────────────────────

def long_straddle(spot: float, step: int, lots: int, lot_size: int) -> dict:
    """
    Buy ATM call + buy ATM put.
    Profits from a large move in either direction.
    Max loss = total debit paid.
    """
    atm = _atm(spot, step)
    qty = lots * lot_size

    legs = [
        Leg("buy", "options", "CE", atm, qty, f"Buy  {atm}CE"),
        Leg("buy", "options", "PE", atm, qty, f"Buy  {atm}PE"),
    ]
    return dict(
        legs=legs, atm=atm,
        break_even_lower=None,  # = atm - total_debit (known after fills)
        break_even_upper=None,  # = atm + total_debit
        max_profit_unit=None,   # unlimited
        max_loss_unit=None,     # = debit paid
        description=f"Long Straddle  {atm}CE + {atm}PE ×{lots}L",
        strikes=[atm],
    )


# ── Registry ──────────────────────────────────────────────────────────────────

STRATEGY_BUILDERS = {
    "iron_condor":      iron_condor,
    "bull_call_spread": bull_call_spread,
    "bear_put_spread":  bear_put_spread,
    "covered_call":     covered_call,
    "long_straddle":    long_straddle,
}

STRATEGY_NAMES = {
    "iron_condor":      "Iron Condor",
    "bull_call_spread": "Bull Call Spread",
    "bear_put_spread":  "Bear Put Spread",
    "covered_call":     "Covered Call",
    "long_straddle":    "Long Straddle",
}

# Strategy symbols for which historical data is most useful
STRATEGY_SYMBOLS = [
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "AXISBANK", "LT", "WIPRO",
]
