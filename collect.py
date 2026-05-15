"""
collect.py — Data collection entry point.

Connects to Breeze and PostgreSQL, then runs all day collecting:
  • Spot ticks + 1m candles     (NIFTY, BANKNIFTY, FINNIFTY + optional large-caps)
  • Futures ticks + 1m candles  (near-month + next-month per symbol)
  • Option chain snapshots       (full chain, all near expiries, every 5 min)
  • Market depth snapshots       (5-level bid/ask, every 5 min)
  • PCR snapshots                (computed from chain OI per expiry)
  • Historical OHLCV backfill    (1m / 5m / 1d, past 30 days, on startup)
  • Daily IV summary             (ATM IV, IV Rank, IV Percentile, at 15:30)

Usage:
    python collect.py
    python collect.py --symbols NIFTY BANKNIFTY FINNIFTY
    python collect.py --no-futures --no-depth --backfill-days 7
    python collect.py --chain-interval 180 --equity-symbols RELIANCE TCS
"""

import argparse
import logging
import sys
from pathlib import Path

Path("logs").mkdir(exist_ok=True)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("logs/collector.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NSE Tick Data Collector — Breeze → PostgreSQL",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--symbols", nargs="+", default=["NIFTY", "BANKNIFTY", "FINNIFTY"],
                   help="Index symbols (spot + option chain)")
    p.add_argument("--equity-symbols", nargs="+",
                   default=["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"],
                   help="Large-cap equity symbols for spot ticks")
    p.add_argument("--futures-symbols", nargs="+", default=None,
                   help="Futures symbols (defaults to same as --symbols)")
    p.add_argument("--chain-interval", type=int, default=300,
                   help="Option chain snapshot interval (seconds)")
    p.add_argument("--chain-full", action="store_true", default=True,
                   help="Store full chain (all strikes)")
    p.add_argument("--chain-depth", type=int, default=15,
                   help="ATM ± N strikes (only when --no-chain-full)")
    p.add_argument("--no-futures", action="store_true",
                   help="Disable futures WebSocket collection")
    p.add_argument("--no-depth", action="store_true",
                   help="Disable market depth snapshots")
    p.add_argument("--no-historical", action="store_true",
                   help="Skip historical OHLCV backfill on startup")
    p.add_argument("--backfill-days", type=int, default=30,
                   help="Days of history to backfill on startup")
    p.add_argument("--spot-batch", type=float, default=1.0,
                   help="Spot tick flush interval (seconds)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    from collector import CollectorConfig, DataCollectorRunner

    futures_syms = args.futures_symbols or args.symbols

    cfg = CollectorConfig(
        symbols             = args.symbols,
        equity_symbols      = args.equity_symbols,
        futures_symbols     = [] if args.no_futures else futures_syms,
        chain_interval_sec  = args.chain_interval,
        chain_full          = args.chain_full,
        chain_atm_depth     = args.chain_depth,
        collect_depth       = not args.no_depth,
        collect_historical  = not args.no_historical,
        backfill_days       = args.backfill_days,
        spot_batch_sec      = args.spot_batch,
    )

    log.info("Starting collector — symbols: %s  futures: %s  depth: %s  backfill: %s",
             cfg.symbols, cfg.futures_symbols or "disabled",
             cfg.collect_depth, cfg.collect_historical)

    runner = DataCollectorRunner(cfg)
    try:
        runner.connect()
        runner.run()
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — shutting down.")
    except Exception as exc:
        log.critical("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
