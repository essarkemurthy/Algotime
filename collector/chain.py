import logging
import time
from datetime import date, datetime
from types import SimpleNamespace
from typing import List, Optional

import numpy as np
import pandas as pd

from trade_engine.greeks import GreeksEngine
from trade_engine.symbols import SymbolBuilder, all_expiries, monthly_expiries

from .config import CollectorConfig
from .store import DataStore

log = logging.getLogger(__name__)


class ChainSnapshotCollector:
    """
    Polls the Breeze REST API every chain_interval_sec (driven by runner schedule).

    For each index symbol:
      - Fetches the full option chain for ALL upcoming expiries
        (8 weekly Thursdays + extra monthly expiries beyond that window)
      - Stores full chain with bid/ask and enriched Greeks
      - Computes and stores PCR per expiry

    For each equity option symbol:
      - Fetches monthly option chain (3 nearest monthly expiries)
      - Same storage as index chains
    """

    def __init__(self, api, cfg: CollectorConfig, store: DataStore) -> None:
        self._api   = api
        self._cfg   = cfg
        self._store = store
        self._ge    = GreeksEngine(SimpleNamespace(risk_free_rate=cfg.risk_free_rate))

    def run_once(self) -> None:
        ts = datetime.now().astimezone()

        # Index option chains — all upcoming expiries
        for symbol in self._cfg.symbols:
            expiries = all_expiries(
                expiry_type=self._cfg.expiry_type(symbol),
                weekly_n=self._cfg.chain_weekly_count,
                monthly_n=self._cfg.chain_monthly_count,
            )
            for expiry in expiries:
                try:
                    self._snapshot(symbol, expiry, ts,
                                   is_index=True,
                                   exchange=self._cfg.nfo_exchange)
                    time.sleep(0.3)   # gentle rate limiting between REST calls
                except Exception as exc:
                    log.error("Chain snapshot failed %s %s: %s",
                              symbol, expiry, exc, exc_info=True)

        # Equity option chains — 3 monthly expiries each
        for symbol in self._cfg.equity_option_symbols:
            expiries = monthly_expiries(3)
            for expiry in expiries:
                try:
                    self._snapshot(symbol, expiry, ts,
                                   is_index=False,
                                   exchange=self._cfg.nfo_exchange)
                    time.sleep(0.3)
                except Exception as exc:
                    log.error("Equity chain snapshot failed %s %s: %s",
                              symbol, expiry, exc, exc_info=True)

    # ── internals ─────────────────────────────────────────────────────────────

    def _snapshot(self, symbol: str, expiry: date, ts: datetime,
                  is_index: bool, exchange: str) -> None:
        spot  = self._get_spot(symbol, exchange if not is_index else self._cfg.nse_exchange)
        chain = self._fetch_chain(symbol, expiry, exchange)
        if chain.empty:
            log.debug("Empty chain for %s %s — expiry may not be listed.", symbol, expiry)
            return

        # Optionally restrict to ATM ± depth
        if not self._cfg.chain_full:
            atm   = _nearest_strike(spot, chain)
            step  = self._cfg.strike_step(symbol)
            depth = self._cfg.chain_atm_depth
            lo, hi = atm - depth * step, atm + depth * step
            chain = chain[(chain["strike_price"] >= lo) &
                          (chain["strike_price"] <= hi)].copy()

        enriched = self._ge.enrich_chain(chain, spot, expiry)
        rows     = _build_rows(enriched, symbol, expiry, ts)
        if rows:
            self._store.insert_chain_snapshots(rows)

        self._record_pcr(symbol, expiry, ts, chain)

        atm = _nearest_strike(spot, chain)
        log.info("Chain: %-12s  expiry=%s  rows=%d  atm=%d  spot=%.2f",
                 symbol, expiry, len(rows), atm, spot)

    def _get_spot(self, symbol: str, exchange: str) -> float:
        resp = self._api.get_quotes(
            stock_code=symbol,
            exchange_code=exchange,
            expiry_date="",
            product_type="cash",
            right="",
            strike_price="",
        )
        if resp.get("Status") != 200 or not resp.get("Success"):
            raise RuntimeError(f"Spot fetch failed for {symbol}: {resp}")
        return float(resp["Success"][0]["ltp"])

    def _fetch_chain(self, symbol: str, expiry: date, exchange: str) -> pd.DataFrame:
        resp = self._api.get_option_chain_quotes(
            stock_code=symbol,
            exchange_code=exchange,
            product_type="options",
            expiry_date=SymbolBuilder.breeze_dt(expiry),
            right="others",
            strike_price="0",
        )
        if resp.get("Status") != 200:
            return pd.DataFrame()
        success = resp.get("Success") or []
        if not success:
            return pd.DataFrame()
        df = pd.DataFrame(success)
        df["strike_price"]     = df["strike_price"].astype(float).astype(int)
        df["ltp"]              = pd.to_numeric(df["ltp"],              errors="coerce")
        df["open_interest"]    = pd.to_numeric(df["open_interest"],    errors="coerce")
        df["volume"]           = pd.to_numeric(df["volume"],           errors="coerce")
        df["best_bid_price"]   = pd.to_numeric(df.get("best_bid_price",   0), errors="coerce")
        df["best_offer_price"] = pd.to_numeric(df.get("best_offer_price", 0), errors="coerce")
        df["right"]            = df["right"].str.lower().str.strip()
        return df.dropna(subset=["ltp"]).reset_index(drop=True)

    def _record_pcr(self, symbol: str, expiry: date, ts: datetime,
                    chain: pd.DataFrame) -> None:
        call_oi = int(chain.loc[chain["right"].str.startswith("c"), "open_interest"]
                      .fillna(0).sum())
        put_oi  = int(chain.loc[chain["right"].str.startswith("p"), "open_interest"]
                      .fillna(0).sum())
        pcr = round(put_oi / call_oi, 4) if call_oi > 0 else None
        try:
            self._store.insert_pcr_snapshot({
                "ts": ts, "symbol": symbol, "expiry": expiry,
                "call_oi": call_oi, "put_oi": put_oi, "pcr": pcr,
            })
        except Exception as exc:
            log.error("PCR insert failed %s %s: %s", symbol, expiry, exc)


# ── helpers ───────────────────────────────────────────────────────────────────

def _nearest_strike(spot: float, chain: pd.DataFrame) -> int:
    available = chain["strike_price"].unique()
    return int(min(available, key=lambda s: abs(s - spot)))


def _nan_or(val) -> Optional[float]:
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _build_rows(df: pd.DataFrame, symbol: str, expiry: date,
                ts: datetime) -> List[dict]:
    rows = []
    for row in df.itertuples():
        right = "CE" if str(row.right).startswith("c") else "PE"
        rows.append({
            "ts":     ts,
            "symbol": symbol,
            "expiry": expiry,
            "strike": int(row.strike_price),
            "right":  right,
            "ltp":    _nan_or(row.ltp),
            "bid":    _nan_or(getattr(row, "best_bid_price",   None)),
            "ask":    _nan_or(getattr(row, "best_offer_price", None)),
            "oi":     int(row.open_interest) if _nan_or(row.open_interest) is not None else None,
            "volume": int(row.volume)        if _nan_or(row.volume)        is not None else None,
            "iv":     _nan_or(getattr(row, "iv",    None)),
            "delta":  _nan_or(getattr(row, "delta", None)),
            "gamma":  _nan_or(getattr(row, "gamma", None)),
            "theta":  _nan_or(getattr(row, "theta", None)),
            "vega":   _nan_or(getattr(row, "vega",  None)),
        })
    return rows
