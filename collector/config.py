import os
from dataclasses import dataclass, field
from datetime import time as time_t
from typing import Dict, List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class CollectorConfig:
    # ── Breeze credentials ────────────────────────────────────────────────────
    api_key: str       = field(default_factory=lambda: os.environ["BREEZE_API_KEY"])
    api_secret: str    = field(default_factory=lambda: os.environ["BREEZE_API_SECRET"])
    session_token: str = field(default_factory=lambda: os.environ["BREEZE_SESSION_TOKEN"])

    # ── PostgreSQL ─────────────────────────────────────────────────────────────
    db_url: str = field(default_factory=lambda: os.environ["DB_URL"])

    # ── NSE Index symbols (WebSocket spot + option chain) ─────────────────────
    symbols: List[str] = field(default_factory=lambda: [
        "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    ])

    # ── Equity symbols: spot ticks + candles (Nifty 50 top 25 by liquidity) ──
    equity_symbols: List[str] = field(default_factory=lambda: [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "SBIN", "BHARTIARTL", "KOTAKBANK", "AXISBANK",
        "LT", "ASIANPAINT", "MARUTI", "SUNPHARMA", "WIPRO",
        "ULTRACEMCO", "NESTLEIND", "POWERGRID", "NTPC", "COALINDIA",
        "ONGC", "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "ADANIENT",
    ])

    # ── Equity symbols that also have active option chains ────────────────────
    # These use monthly expiries; strike steps vary by stock price.
    equity_option_symbols: List[str] = field(default_factory=lambda: [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "SBIN", "BHARTIARTL", "AXISBANK", "LT", "WIPRO",
    ])
    equity_option_cfg: Dict[str, dict] = field(default_factory=lambda: {
        "RELIANCE":  {"strike_step": 50},
        "TCS":       {"strike_step": 50},
        "HDFCBANK":  {"strike_step": 10},
        "INFY":      {"strike_step": 20},
        "ICICIBANK": {"strike_step": 10},
        "SBIN":      {"strike_step": 5},
        "BHARTIARTL":{"strike_step": 10},
        "AXISBANK":  {"strike_step": 10},
        "LT":        {"strike_step": 50},
        "WIPRO":     {"strike_step": 5},
    })

    # ── Futures symbols (index + top equity futures) ───────────────────────────
    futures_symbols: List[str] = field(default_factory=lambda: [
        "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    ])
    futures_num_expiries: int = 3   # near-month + next-month + far-month

    # ── NSE ticker → Breeze internal code (cash + F&O feeds/historical) ────────
    # Breeze's WebSocket feeds and historical API use internal codes, not NSE
    # tickers. Symbols absent here use their ticker unchanged (e.g. NIFTY, TCS,
    # MARUTI, WIPRO, NTPC, ONGC). Verified live against get_stock_token_value.
    breeze_code_map: Dict[str, str] = field(default_factory=lambda: {
        # indices
        "BANKNIFTY": "CNXBAN", "FINNIFTY": "NIFFIN", "MIDCPNIFTY": "NIFSEL",
        # equities
        "RELIANCE": "RELIND", "HDFCBANK": "HDFBAN", "INFY": "INFTEC",
        "ICICIBANK": "ICIBAN", "HINDUNILVR": "HINLEV", "SBIN": "STABAN",
        "BHARTIARTL": "BHAAIR", "KOTAKBANK": "KOTMAH", "AXISBANK": "AXIBAN",
        "LT": "LARTOU", "ASIANPAINT": "ASIPAI", "SUNPHARMA": "SUNPHA",
        "ULTRACEMCO": "ULTCEM", "NESTLEIND": "NESIND", "POWERGRID": "POWGRI",
        "COALINDIA": "COALIN", "TATAMOTORS": "TATMOT", "TATASTEEL": "TATSTE",
        "JSWSTEEL": "JSWSTE", "ADANIENT": "ADAENT",
    })

    # ── Per-symbol option chain config ────────────────────────────────────────
    symbol_cfg: Dict[str, dict] = field(default_factory=lambda: {
        "NIFTY":      {"strike_step": 50,  "expiry_type": "weekly"},
        "BANKNIFTY":  {"strike_step": 100, "expiry_type": "weekly"},
        "FINNIFTY":   {"strike_step": 50,  "expiry_type": "weekly"},
        "MIDCPNIFTY": {"strike_step": 25,  "expiry_type": "weekly"},
    })

    # ── Option chain expiry window ─────────────────────────────────────────────
    # weekly_expiry_count: next N weekly Thursdays for weekly-expiry index symbols
    # monthly_expiry_count: extra monthly expiries beyond the weekly window
    # equity option chains always use 3 monthly expiries
    chain_weekly_count: int  = 8    # ~2 months of weekly options
    chain_monthly_count: int = 3    # additional months beyond the weekly window

    # ── Option chain collection ────────────────────────────────────────────────
    chain_interval_sec: int  = 300   # REST poll every 5 min
    chain_full: bool         = True  # True = all strikes, False = ATM ± chain_atm_depth
    chain_atm_depth: int     = 20    # used only when chain_full=False

    # ── Spot tick batching ─────────────────────────────────────────────────────
    spot_batch_sec: float = 1.0

    # ── Market depth snapshots ────────────────────────────────────────────────
    collect_depth: bool     = True
    depth_interval_sec: int = 300

    # ── Historical candle backfill ─────────────────────────────────────────────
    # Runs once on startup; fetches only the gap since last stored candle.
    collect_historical: bool        = True
    backfill_days: int              = 90    # 1m / 5m data window
    backfill_days_daily: int        = 730   # ~2 years of daily candles
    historical_intervals: List[str] = field(default_factory=lambda: [
        "1minute", "5minute", "30minute", "1day",
    ])

    # ── Greeks / IV ───────────────────────────────────────────────────────────
    risk_free_rate: float = 0.065   # 91-day T-bill proxy — update monthly

    # ── Exchange codes ────────────────────────────────────────────────────────
    nse_exchange: str = "NSE"
    nfo_exchange: str = "NFO"

    # ── Market timing (IST) ───────────────────────────────────────────────────
    market_open:  time_t = field(default_factory=lambda: time_t(9,  15))
    market_close: time_t = field(default_factory=lambda: time_t(15, 30))
    shutdown_at:  time_t = field(default_factory=lambda: time_t(15, 35))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def breeze_code(self, symbol: str) -> str:
        """NSE ticker → Breeze internal code for live feeds (identity if unmapped)."""
        return self.breeze_code_map.get(symbol, symbol)

    def strike_step(self, symbol: str) -> int:
        if symbol in self.symbol_cfg:
            return self.symbol_cfg[symbol].get("strike_step", 50)
        return self.equity_option_cfg.get(symbol, {}).get("strike_step", 50)

    def expiry_type(self, symbol: str) -> str:
        return self.symbol_cfg.get(symbol, {}).get("expiry_type", "monthly")

    @property
    def all_spot_symbols(self) -> List[str]:
        """All symbols needing WebSocket spot subscriptions."""
        return list(dict.fromkeys(self.symbols + self.equity_symbols))

    @property
    def all_chain_symbols(self) -> List[str]:
        """All symbols to collect option chains for (index + equity options)."""
        return list(dict.fromkeys(self.symbols + self.equity_option_symbols))
