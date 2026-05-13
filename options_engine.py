"""
options_engine.py — Production Options Algo Engine
Breeze Connect (ICICI Direct) · NSE/NFO · Weekly + Monthly Expiry

Install deps:
    pip install breeze-connect py_vollib py_vollib_vectorized breeze-strategies

Env vars required:
    BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN
"""

import os
import time
import logging
from datetime import date, datetime, timedelta, time as time_t
from dataclasses import dataclass, field
from typing import Optional, Literal

import numpy as np
import pandas as pd
from breeze_connect import BreezeConnect
from py_vollib.black_scholes.implied_volatility import implied_volatility as _bs_iv
from py_vollib.black_scholes.greeks.analytical import (
    delta as _delta,
    gamma as _gamma,
    theta as _theta,
    vega as _vega,
)
from py_vollib_vectorized import vectorized_implied_volatility as _vec_iv

try:
    from breeze_strategies import BreezeStrategies as _BreezeStrategies
    _STRAT_AVAIL = True
except ImportError:
    _STRAT_AVAIL = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.FileHandler("options_engine.log"), logging.StreamHandler()],
)
log = logging.getLogger("options_engine")


# ── NSE symbol encoding ───────────────────────────────────────────────────────
# Weekly month codes: Jan-Sep = 1-9, Oct = O, Nov = N, Dec = D
_WEEK_MONTH = {1:"1",2:"2",3:"3",4:"4",5:"5",6:"6",7:"7",8:"8",9:"9",
               10:"O",11:"N",12:"D"}
_MON3 = {1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",
         7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}


# ── TAB 1 · CONFIGURATION ─────────────────────────────────────────────────────
@dataclass
class EngineConfig:
    # Credentials — never hardcode; read from env
    api_key: str        = field(default_factory=lambda: os.environ["BREEZE_API_KEY"])
    api_secret: str     = field(default_factory=lambda: os.environ["BREEZE_API_SECRET"])
    session_token: str  = field(default_factory=lambda: os.environ["BREEZE_SESSION_TOKEN"])

    # Instrument
    underlying: str     = "NIFTY"
    exchange: str       = "NFO"
    lot_size: int       = 50      # NIFTY lot size — verify with SEBI circular
    num_lots: int       = 1
    strike_step: int    = 50      # minimum strike interval on chain

    # Strategy
    strategy: Literal["bull_put_spread", "iron_condor"] = "bull_put_spread"
    expiry_type: Literal["weekly", "monthly"]            = "weekly"
    short_delta_target: float = 0.25   # target abs-delta for short strikes
    spread_width: int         = 100    # points between short and long strike
    min_credit_pct: float     = 0.25   # min credit as % of spread width

    # Risk
    stop_loss_multiplier: float = 2.0  # exit when debit-to-close = N × entry credit
    profit_target_pct: float    = 0.50 # exit when P&L = N × max_profit
    max_portfolio_delta: float  = 5.0  # emergency exit threshold (lot-adjusted)

    # Greeks / IV
    risk_free_rate: float   = 0.065  # 91-day T-bill proxy
    iv_rank_lookback: int   = 252    # trading days for IV rank window
    min_iv_rank: float      = 40.0   # skip entry below this rank
    iv_history_file: str    = "iv_history.csv"

    # Timing (IST)
    entry_time:  time_t = field(default_factory=lambda: time_t(9, 30))
    cutoff_time: time_t = field(default_factory=lambda: time_t(15, 0))
    exit_time:   time_t = field(default_factory=lambda: time_t(15, 15))


# ── TAB 2 · SESSION ───────────────────────────────────────────────────────────
class BreezeSession:
    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self._api: Optional[BreezeConnect] = None

    @property
    def api(self) -> BreezeConnect:
        if self._api is None:
            raise RuntimeError("Call connect() first.")
        return self._api

    def connect(self) -> None:
        self._api = BreezeConnect(api_key=self.cfg.api_key)
        self._api.generate_session(
            api_secret=self.cfg.api_secret,
            session_token=self.cfg.session_token,
        )
        log.info("Breeze session established.")

    def disconnect(self) -> None:
        if self._api:
            try:
                self._api.ws_disconnect()
            except Exception:
                pass
            self._api = None
            log.info("Breeze session closed.")

    def __enter__(self) -> "BreezeSession":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    def get_spot(self) -> float:
        resp = self.api.get_quotes(
            stock_code=self.cfg.underlying,
            exchange_code="NSE",
            expiry_date="",
            product_type="cash",
            right="",
            strike_price="",
        )
        if resp.get("Status") != 200:
            raise RuntimeError(f"Spot fetch failed: {resp}")
        return float(resp["Success"][0]["ltp"])


# ── TAB 3 · MARKET DATA ───────────────────────────────────────────────────────
class SymbolBuilder:
    @staticmethod
    def weekly(underlying: str, expiry: date, strike: int, right: Literal["CE","PE"]) -> str:
        """e.g. NIFTY2341319500CE — year(2) + single-char month + day(2) + strike + type"""
        yy = expiry.strftime("%y")
        m  = _WEEK_MONTH[expiry.month]
        dd = f"{expiry.day:02d}"
        return f"{underlying}{yy}{m}{dd}{strike}{right}"

    @staticmethod
    def monthly(underlying: str, expiry: date, strike: int, right: Literal["CE","PE"]) -> str:
        """e.g. NIFTY23APR19500CE"""
        yy = expiry.strftime("%y")
        m  = _MON3[expiry.month]
        return f"{underlying}{yy}{m}{strike}{right}"

    @staticmethod
    def build(underlying: str, expiry: date, strike: int,
              right: Literal["CE","PE"], expiry_type: Literal["weekly","monthly"]) -> str:
        return (SymbolBuilder.weekly(underlying, expiry, strike, right)
                if expiry_type == "weekly"
                else SymbolBuilder.monthly(underlying, expiry, strike, right))

    @staticmethod
    def breeze_dt(d: date) -> str:
        """ISO datetime string Breeze expects for expiry/validity fields."""
        return datetime(d.year, d.month, d.day, 6).isoformat(timespec="milliseconds") + "Z"


def _last_thursday(year: int, month: int) -> date:
    """Last Thursday of given month (NSE monthly expiry rule)."""
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    last_day = first_next - timedelta(days=1)
    days_back = (last_day.weekday() - 3) % 7  # Thursday = 3
    return last_day - timedelta(days=days_back)


def nearest_weekly_expiry(today: date | None = None) -> date:
    today = today or date.today()
    days = (3 - today.weekday()) % 7  # Thursday = 3
    if days == 0 and datetime.now().time() > time_t(15, 30):
        days = 7
    return today + timedelta(days=days)


def nearest_monthly_expiry(today: date | None = None) -> date:
    today = today or date.today()
    this_exp = _last_thursday(today.year, today.month)
    if this_exp > today:
        return this_exp
    m, y = (today.month % 12) + 1, today.year + (1 if today.month == 12 else 0)
    return _last_thursday(y, m)


class OptionChainFetcher:
    def __init__(self, session: BreezeSession) -> None:
        self.session = session

    def fetch(self, expiry: date, right: str = "others") -> pd.DataFrame:
        cfg = self.session.cfg
        resp = self.session.api.get_option_chain_quotes(
            stock_code=cfg.underlying,
            exchange_code=cfg.exchange,
            product_type="options",
            expiry_date=SymbolBuilder.breeze_dt(expiry),
            right=right,
            strike_price="0",
        )
        if resp.get("Status") != 200:
            raise RuntimeError(f"Chain fetch failed: {resp}")
        df = pd.DataFrame(resp["Success"])
        df["strike_price"]  = df["strike_price"].astype(float).astype(int)
        df["ltp"]           = pd.to_numeric(df["ltp"],           errors="coerce")
        df["open_interest"] = pd.to_numeric(df["open_interest"], errors="coerce")
        df["volume"]        = pd.to_numeric(df["volume"],        errors="coerce")
        df["right"]         = df["right"].str.lower().str.strip()
        return df.dropna(subset=["ltp"]).reset_index(drop=True)

    def atm_strike(self, spot: float, chain: pd.DataFrame) -> int:
        step = self.session.cfg.strike_step
        rounded = round(spot / step) * step
        available = chain["strike_price"].unique()
        atm = int(min(available, key=lambda s: abs(s - rounded)))
        log.info("Spot %.2f → ATM %d", spot, atm)
        return atm


# ── TAB 4 · GREEKS & IV RANK ──────────────────────────────────────────────────
class GreeksEngine:
    def __init__(self, cfg: EngineConfig) -> None:
        self.r = cfg.risk_free_rate

    def tte(self, expiry: date) -> float:
        """Time to expiry as fraction of year (calendar days)."""
        return max((expiry - date.today()).days, 1) / 365.0

    def iv(self, price: float, spot: float, strike: int,
           expiry: date, right: Literal["CE","PE"]) -> Optional[float]:
        flag = "c" if right == "CE" else "p"
        try:
            v = _bs_iv(price, spot, strike, self.tte(expiry), self.r, flag)
            return float(v) if v and 0 < v < 5 else None
        except Exception:
            return None

    def greeks(self, iv: float, spot: float, strike: int,
               expiry: date, right: Literal["CE","PE"]) -> dict:
        flag = "c" if right == "CE" else "p"
        t, r = self.tte(expiry), self.r
        return {
            "delta": _delta(flag, spot, strike, t, r, iv),
            "gamma": _gamma(flag, spot, strike, t, r, iv),
            "theta": _theta(flag, spot, strike, t, r, iv) / 365,  # per-day
            "vega":  _vega(flag, spot, strike, t, r, iv) / 100,   # per 1% IV move
        }

    def enrich_chain(self, chain: pd.DataFrame, spot: float, expiry: date) -> pd.DataFrame:
        """Add iv / delta / gamma / theta / vega columns via vectorized IV then row Greeks."""
        df = chain.copy()
        t  = self.tte(expiry)
        flags = np.where(df["right"].str.startswith("c"), "c", "p")

        try:
            ivs = _vec_iv(
                df["ltp"].values.astype(float),
                np.full(len(df), spot),
                df["strike_price"].values.astype(float),
                np.full(len(df), t),
                np.full(len(df), self.r),
                flags,
                q=np.zeros(len(df)),
                return_as="numpy",
                on_error="ignore",
            )
            df["iv"] = np.where((ivs > 0) & (ivs < 5), ivs, np.nan)
        except Exception as exc:
            log.warning("Vectorized IV error (%s) — row-by-row fallback.", exc)
            df["iv"] = [
                self.iv(row.ltp, spot, row.strike_price, expiry,
                        "CE" if row.right.startswith("c") else "PE")
                for row in df.itertuples()
            ]

        for col in ("delta", "gamma", "theta", "vega"):
            df[col] = np.nan

        valid_mask = df["iv"].notna()
        for idx in df[valid_mask].index:
            row = df.loc[idx]
            r_str = "CE" if str(row["right"]).startswith("c") else "PE"
            try:
                g = self.greeks(float(row["iv"]), spot, int(row["strike_price"]), expiry, r_str)
                for col, val in g.items():
                    df.at[idx, col] = val
            except Exception:
                pass

        return df


class IVRankCalc:
    """Rolling ATM IV history → IV Rank and IV Percentile."""

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg

    def _load(self) -> pd.DataFrame:
        p = self.cfg.iv_history_file
        if not os.path.exists(p):
            return pd.DataFrame(columns=["date", "atm_iv"])
        return pd.read_csv(p, parse_dates=["date"])

    def record(self, atm_iv: float) -> None:
        df  = self._load()
        today = date.today().isoformat()
        if not df.empty and df.iloc[-1]["date"].date() == date.today():
            df.at[df.index[-1], "atm_iv"] = atm_iv
        else:
            df = pd.concat([df, pd.DataFrame([{"date": today, "atm_iv": atm_iv}])],
                           ignore_index=True)
        df.tail(self.cfg.iv_rank_lookback * 2).to_csv(self.cfg.iv_history_file, index=False)

    def rank(self, current_iv: float) -> float:
        """IV Rank 0–100: position of current IV between 1-year low and high."""
        df = self._load().tail(self.cfg.iv_rank_lookback)
        if len(df) < 10:
            log.warning("IV history has %d rows — rank unreliable.", len(df))
        lo, hi = df["atm_iv"].min(), df["atm_iv"].max()
        return 50.0 if hi == lo else float((current_iv - lo) / (hi - lo) * 100)

    def percentile(self, current_iv: float) -> float:
        df = self._load().tail(self.cfg.iv_rank_lookback)
        return 50.0 if df.empty else float((df["atm_iv"] < current_iv).mean() * 100)


# ── TAB 5 · STRATEGY EXECUTION ────────────────────────────────────────────────
@dataclass
class Leg:
    action:      Literal["buy", "sell"]
    right:       Literal["CE", "PE"]
    strike:      int
    expiry:      date
    symbol:      str
    quantity:    int
    entry_price: float = 0.0
    order_id:    str   = ""


@dataclass
class Position:
    legs:       list
    net_credit: float     # total premium collected (positive = credit received)
    max_risk:   float     # maximum possible loss
    max_profit: float     # = net_credit for credit spreads
    strategy:   str
    entry_time: datetime  = field(default_factory=datetime.now)
    is_open:    bool      = True


class OrderRouter:
    def __init__(self, session: BreezeSession) -> None:
        self.session = session

    def place(self, leg: Leg) -> str:
        cfg = self.session.cfg
        resp = self.session.api.place_order(
            stock_code=cfg.underlying,
            exchange_code=cfg.exchange,
            product="options",
            action=leg.action,
            order_type="market",
            stoploss="0",
            quantity=str(leg.quantity),
            price="0",
            validity="day",
            validity_date=SymbolBuilder.breeze_dt(date.today()),
            disclosed_quantity="0",
            expiry_date=SymbolBuilder.breeze_dt(leg.expiry),
            right="call" if leg.right == "CE" else "put",
            strike_price=str(leg.strike),
        )
        if resp.get("Status") != 200:
            raise RuntimeError(f"Order failed for {leg.symbol}: {resp}")
        oid = resp["Success"]["order_id"]
        log.info("ORDER %s %s %s %d → id=%s", leg.action.upper(), leg.right, leg.symbol, leg.strike, oid)
        return oid

    def execute(self, legs: list) -> None:
        for leg in legs:
            leg.order_id = self.place(leg)
            time.sleep(0.2)


def _chain_ltp(chain: pd.DataFrame, strike: int, right_lower: str) -> float:
    rows = chain[(chain["strike_price"] == strike) & (chain["right"] == right_lower)]
    if rows.empty:
        raise ValueError(f"No chain row for strike={strike} right={right_lower}")
    return float(rows["ltp"].iloc[0])


def _closest_delta_strike(df: pd.DataFrame, target: float) -> int:
    col = (df["delta"].abs() - target).abs()
    return int(df.loc[col.idxmin(), "strike_price"])


class BullPutSpread:
    """Sell OTM put / buy further OTM put. Defined-risk credit spread."""

    def __init__(self, session: BreezeSession, router: OrderRouter, cfg: EngineConfig):
        self.session, self.router, self.cfg = session, router, cfg

    def enter(self, chain: pd.DataFrame, spot: float,
              expiry: date, atm: int) -> Optional[Position]:
        cfg = self.cfg
        puts_below = chain[(chain["right"] == "put") &
                           (chain["strike_price"] < atm) &
                           chain["delta"].notna()].copy()
        if puts_below.empty:
            log.warning("No OTM puts with delta — skipping BPS entry.")
            return None

        short_s = _closest_delta_strike(puts_below, cfg.short_delta_target)
        long_s  = short_s - cfg.spread_width

        short_p = _chain_ltp(chain, short_s, "put")
        long_p  = _chain_ltp(chain, long_s,  "put") if long_s in chain["strike_price"].values else 0.0
        credit  = short_p - long_p

        if credit < cfg.spread_width * cfg.min_credit_pct:
            log.info("BPS credit %.2f below min — skipping.", credit)
            return None

        qty = cfg.lot_size * cfg.num_lots
        legs = [
            Leg("sell", "PE", short_s, expiry,
                SymbolBuilder.build(cfg.underlying, expiry, short_s, "PE", cfg.expiry_type),
                qty, short_p),
            Leg("buy",  "PE", long_s,  expiry,
                SymbolBuilder.build(cfg.underlying, expiry, long_s,  "PE", cfg.expiry_type),
                qty, long_p),
        ]
        self.router.execute(legs)
        pos = Position(legs, credit * qty, (cfg.spread_width - credit) * qty,
                       credit * qty, "bull_put_spread")
        log.info("BPS entered: sell %dPE / buy %dPE | credit=%.2f max_risk=%.2f",
                 short_s, long_s, pos.net_credit, pos.max_risk)
        return pos


class IronCondor:
    """Bull Put Spread + Bear Call Spread. Collects premium from both sides."""

    def __init__(self, session: BreezeSession, router: OrderRouter, cfg: EngineConfig):
        self.session, self.router, self.cfg = session, router, cfg

    def enter(self, chain: pd.DataFrame, spot: float,
              expiry: date, atm: int) -> Optional[Position]:
        cfg = self.cfg
        puts  = chain[(chain["right"] == "put")  & (chain["strike_price"] < atm) & chain["delta"].notna()]
        calls = chain[(chain["right"] == "call") & (chain["strike_price"] > atm) & chain["delta"].notna()]
        if puts.empty or calls.empty:
            log.warning("Insufficient chain data for Iron Condor.")
            return None

        ps = _closest_delta_strike(puts,  cfg.short_delta_target)
        pl = ps - cfg.spread_width
        cs = _closest_delta_strike(calls, cfg.short_delta_target)
        cl = cs + cfg.spread_width

        ps_p = _chain_ltp(chain, ps, "put")
        pl_p = _chain_ltp(chain, pl, "put")  if pl in chain["strike_price"].values else 0.0
        cs_p = _chain_ltp(chain, cs, "call")
        cl_p = _chain_ltp(chain, cl, "call") if cl in chain["strike_price"].values else 0.0
        credit = (ps_p - pl_p) + (cs_p - cl_p)

        if credit < cfg.spread_width * cfg.min_credit_pct:
            log.info("IC credit %.2f below min — skipping.", credit)
            return None

        qty  = cfg.lot_size * cfg.num_lots
        et   = cfg.expiry_type
        legs = [
            Leg("sell","PE", ps, expiry, SymbolBuilder.build(cfg.underlying,expiry,ps,"PE",et), qty, ps_p),
            Leg("buy", "PE", pl, expiry, SymbolBuilder.build(cfg.underlying,expiry,pl,"PE",et), qty, pl_p),
            Leg("sell","CE", cs, expiry, SymbolBuilder.build(cfg.underlying,expiry,cs,"CE",et), qty, cs_p),
            Leg("buy", "CE", cl, expiry, SymbolBuilder.build(cfg.underlying,expiry,cl,"CE",et), qty, cl_p),
        ]
        self.router.execute(legs)
        pos = Position(legs, credit * qty, (cfg.spread_width - credit) * qty,
                       credit * qty, "iron_condor")
        log.info("IC entered: puts %d/%d calls %d/%d | credit=%.2f",
                 ps, pl, cs, cl, pos.net_credit)
        return pos


# ── TAB 6 · RISK MANAGEMENT / AUTO STOP-LOSS ─────────────────────────────────
class StopLossManager:
    """
    Monitors open positions. Triggers exit on:
      • Debit-to-close ≥ N × entry credit  (stop-loss)
      • P&L ≥ profit_target_pct × max_profit
      • Net portfolio delta breach
      • Force-flatten at exit_time
    """

    def __init__(self, session: BreezeSession, router: OrderRouter, cfg: EngineConfig):
        self.session, self.router, self.cfg = session, router, cfg

    def close_cost(self, position: Position) -> float:
        """Current debit to close all legs at market. Positive = costs money."""
        total = 0.0
        for leg in position.legs:
            resp = self.session.api.get_quotes(
                stock_code=self.session.cfg.underlying,
                exchange_code=self.session.cfg.exchange,
                expiry_date=SymbolBuilder.breeze_dt(leg.expiry),
                product_type="options",
                right="call" if leg.right == "CE" else "put",
                strike_price=str(leg.strike),
            )
            if resp.get("Status") != 200:
                log.warning("Quote failed for %s — using 0.", leg.symbol)
                continue
            ltp  = float(resp["Success"][0]["ltp"])
            sign = 1 if leg.action == "sell" else -1  # buy back shorts (+), sell longs (−)
            total += sign * ltp * leg.quantity
        return total

    def net_pnl(self, position: Position) -> float:
        return position.net_credit - self.close_cost(position)

    def _exit(self, position: Position, reason: str) -> None:
        log.warning("EXIT triggered — %s", reason)
        close_legs = [
            Leg("buy" if l.action == "sell" else "sell",
                l.right, l.strike, l.expiry, l.symbol, l.quantity)
            for l in position.legs
        ]
        self.router.execute(close_legs)
        position.is_open = False
        log.info("Position closed. %s", reason)

    def _net_delta(self, position: Position, chain: pd.DataFrame) -> float:
        total = 0.0
        for leg in position.legs:
            r = chain[(chain["strike_price"] == leg.strike) &
                      (chain["right"] == ("call" if leg.right == "CE" else "put"))]
            if r.empty or r["delta"].isna().all():
                continue
            raw_d = float(r["delta"].iloc[0])
            # short position flips the sign relative to raw (long) delta
            sign  = -1 if leg.action == "sell" else 1
            total += sign * raw_d * leg.quantity
        return total

    def check(self, position: Position, enriched_chain: pd.DataFrame) -> bool:
        """Returns True if position was closed."""
        if not position.is_open:
            return False

        cc   = self.close_cost(position)
        pnl  = position.net_credit - cc

        # Stop-loss: debit-to-close ≥ multiplier × original credit
        if cc >= self.cfg.stop_loss_multiplier * position.net_credit:
            self._exit(position, f"stop_loss cc={cc:.2f} limit={self.cfg.stop_loss_multiplier * position.net_credit:.2f}")
            return True

        # Profit target
        profit_target = self.cfg.profit_target_pct * position.max_profit
        if pnl >= profit_target:
            self._exit(position, f"profit_target pnl={pnl:.2f} target={profit_target:.2f}")
            return True

        # Delta breach
        nd = self._net_delta(position, enriched_chain)
        if abs(nd) > self.cfg.max_portfolio_delta:
            self._exit(position, f"delta_breach net_delta={nd:.2f}")
            return True

        log.info("Monitor OK | P&L=%.2f | close_cost=%.2f | net_delta=%.2f", pnl, cc, nd)
        return False

    def force_flatten(self, position: Position) -> None:
        if position.is_open:
            self._exit(position, "force_flatten_eod")


# ── MAIN ORCHESTRATOR ─────────────────────────────────────────────────────────
class OptionsAlgoEngine:
    """
    Daily flow:
        engine.connect()
        entered = engine.run_entry_scan()
        if entered:
            engine.run_monitor_loop()
        engine.disconnect()
    """

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg            = cfg
        self.session        = BreezeSession(cfg)
        self.router:   Optional[OrderRouter]       = None
        self.fetcher:  Optional[OptionChainFetcher] = None
        self.ge             = GreeksEngine(cfg)
        self.iv_rank        = IVRankCalc(cfg)
        self.position: Optional[Position]          = None

    def connect(self) -> None:
        self.session.connect()
        self.router  = OrderRouter(self.session)
        self.fetcher = OptionChainFetcher(self.session)

    def disconnect(self) -> None:
        self.session.disconnect()

    # ── entry ─────────────────────────────────────────────────────────────────
    def run_entry_scan(self) -> bool:
        now = datetime.now().time()
        if not (self.cfg.entry_time <= now <= self.cfg.cutoff_time):
            log.info("Outside entry window — no scan.")
            return False

        spot   = self.session.get_spot()
        expiry = (nearest_weekly_expiry() if self.cfg.expiry_type == "weekly"
                  else nearest_monthly_expiry())
        log.info("Underlying=%.2f  Expiry=%s", spot, expiry)

        chain = self.fetcher.fetch(expiry)
        atm   = self.fetcher.atm_strike(spot, chain)

        # ATM IV from ATM call price
        atm_calls = chain[(chain["strike_price"] == atm) & (chain["right"] == "call")]
        if atm_calls.empty:
            log.warning("ATM call not in chain — aborting.")
            return False

        atm_iv = self.ge.iv(float(atm_calls["ltp"].iloc[0]), spot, atm, expiry, "CE")
        if atm_iv is None:
            log.warning("ATM IV calculation failed — aborting.")
            return False

        self.iv_rank.record(atm_iv)
        ivr = self.iv_rank.rank(atm_iv)
        log.info("ATM IV=%.1f%%  IV Rank=%.1f", atm_iv * 100, ivr)

        if ivr < self.cfg.min_iv_rank:
            log.info("IV Rank %.1f < min %.1f — low-vol, no trade.", ivr, self.cfg.min_iv_rank)
            return False

        enriched = self.ge.enrich_chain(chain, spot, expiry)

        if self.cfg.strategy == "bull_put_spread":
            self.position = BullPutSpread(self.session, self.router, self.cfg).enter(enriched, spot, expiry, atm)
        else:
            self.position = IronCondor(self.session, self.router, self.cfg).enter(enriched, spot, expiry, atm)

        return self.position is not None

    # ── monitor ───────────────────────────────────────────────────────────────
    def run_monitor_loop(self, poll_seconds: int = 300) -> None:
        if not self.position:
            log.info("No open position.")
            return

        slm    = StopLossManager(self.session, self.router, self.cfg)
        expiry = self.position.legs[0].expiry

        while True:
            if datetime.now().time() >= self.cfg.exit_time:
                slm.force_flatten(self.position)
                break
            try:
                spot     = self.session.get_spot()
                chain    = self.fetcher.fetch(expiry)
                enriched = self.ge.enrich_chain(chain, spot, expiry)
                if slm.check(self.position, enriched):
                    break
            except Exception as exc:
                log.error("Monitor error: %s", exc, exc_info=True)

            time.sleep(poll_seconds)


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cfg = EngineConfig(
        underlying="NIFTY",
        lot_size=50,
        num_lots=1,
        strategy="bull_put_spread",   # change to "iron_condor" when ready
        expiry_type="weekly",
        short_delta_target=0.25,
        spread_width=100,
        min_iv_rank=40.0,
        stop_loss_multiplier=2.0,
        profit_target_pct=0.50,
    )
    engine = OptionsAlgoEngine(cfg)
    try:
        engine.connect()
        if engine.run_entry_scan():
            engine.run_monitor_loop(poll_seconds=300)
    except KeyboardInterrupt:
        log.info("Interrupted — flattening position.")
        if engine.position and engine.position.is_open and engine.router:
            StopLossManager(engine.session, engine.router, cfg).force_flatten(engine.position)
    finally:
        engine.disconnect()
