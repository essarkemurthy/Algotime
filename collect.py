"""
collect.py — Data collection entry point.

Connects to Breeze and PostgreSQL, then runs all day collecting:
  • Spot ticks + 1m candles         (4 indices + 25 large-cap equities)
  • Futures ticks + 1m candles      (near/next/far-month per symbol)
  • Option chain snapshots           (full chain, all expiries, every 5 min)
  • Equity option chain snapshots    (top 10 stocks, 3 monthly expiries)
  • Market depth snapshots           (5-level bid/ask, every 5 min)
  • PCR snapshots                    (computed from chain OI per expiry)
  • Historical OHLCV backfill        (1m/5m/15m/30m/1d, on startup)
  • Daily IV summary                 (ATM IV, IV Rank, IV Percentile, at 15:30)

Usage:
    python collect.py
    python collect.py --symbols NIFTY BANKNIFTY
    python collect.py --no-futures --no-depth --backfill-days 7
    python collect.py --chain-interval 180 --chain-weekly-count 4
    python collect.py --backfill-days-daily 365 --historical-intervals 1minute 1day
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

    # ── Symbol selection ───────────────────────────────────────────────────────
    p.add_argument("--symbols", nargs="+",
                   default=["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"],
                   help="Index symbols (spot ticks + option chains)")
    p.add_argument("--equity-symbols", nargs="+", default=None,
                   help="Equity symbols for spot ticks (default: top 25 Nifty 50)")
    p.add_argument("--futures-symbols", nargs="+", default=None,
                   help="Futures symbols (default: 4 indices + top 5 equities)")
    p.add_argument("--futures-num-expiries", type=int, default=3,
                   help="Number of monthly futures expiries to subscribe (near/next/far)")

    # ── Option chain ───────────────────────────────────────────────────────────
    p.add_argument("--chain-interval", type=int, default=300,
                   help="Option chain snapshot interval (seconds)")
    p.add_argument("--chain-full", action="store_true", default=True,
                   help="Store full chain (all strikes)")
    p.add_argument("--chain-depth", type=int, default=20,
                   help="ATM ± N strikes (only when --no-chain-full)")
    p.add_argument("--chain-weekly-count", type=int, default=8,
                   help="Number of upcoming weekly expiries to collect for weekly-expiry symbols")
    p.add_argument("--chain-monthly-count", type=int, default=3,
                   help="Extra monthly expiries beyond the weekly window")

    # ── Historical backfill ────────────────────────────────────────────────────
    p.add_argument("--no-historical", action="store_true",
                   help="Skip historical OHLCV backfill on startup")
    p.add_argument("--backfill-days", type=int, default=90,
                   help="Days of intraday history to backfill (1m/5m/15m/30m)")
    p.add_argument("--backfill-days-daily", type=int, default=730,
                   help="Days of daily candle history to backfill (~2 years)")
    p.add_argument("--historical-intervals", nargs="+",
                   default=["1minute", "5minute", "15minute", "30minute", "1day"],
                   choices=["1minute", "5minute", "15minute", "30minute", "1day"],
                   help="Breeze intervals to backfill")

    # ── Feature toggles ────────────────────────────────────────────────────────
    p.add_argument("--no-futures", action="store_true",
                   help="Disable futures WebSocket collection")
    p.add_argument("--no-depth", action="store_true",
                   help="Disable market depth snapshots")

    # ── Tuning ────────────────────────────────────────────────────────────────
    p.add_argument("--spot-batch", type=float, default=1.0,
                   help="Spot tick flush interval (seconds)")

    return p.parse_args()


def main() -> None:
    args = parse_args()

    from collector import CollectorConfig, DataCollectorRunner

    cfg_kwargs = dict(
        symbols             = args.symbols,
        chain_interval_sec  = args.chain_interval,
        chain_full          = args.chain_full,
        chain_atm_depth     = args.chain_depth,
        chain_weekly_count  = args.chain_weekly_count,
        chain_monthly_count = args.chain_monthly_count,
        collect_depth       = not args.no_depth,
        collect_historical  = not args.no_historical,
        backfill_days       = args.backfill_days,
        backfill_days_daily = args.backfill_days_daily,
        historical_intervals= args.historical_intervals,
        futures_num_expiries= args.futures_num_expiries,
        spot_batch_sec      = args.spot_batch,
    )

    # Only override list fields if the user explicitly passed them
    if args.equity_symbols is not None:
        cfg_kwargs["equity_symbols"] = args.equity_symbols
    if args.futures_symbols is not None:
        cfg_kwargs["futures_symbols"] = [] if args.no_futures else args.futures_symbols
    elif args.no_futures:
        cfg_kwargs["futures_symbols"] = []

    cfg = CollectorConfig(**cfg_kwargs)

    log.info(
        "Starting collector — symbols: %s  futures: %s  "
        "intervals: %s  backfill: %dd intraday / %dd daily  depth: %s",
        cfg.symbols,
        cfg.futures_symbols or "disabled",
        cfg.historical_intervals,
        cfg.backfill_days,
        cfg.backfill_days_daily,
        cfg.collect_depth,
    )

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
