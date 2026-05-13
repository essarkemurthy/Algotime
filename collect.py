"""
collect.py — Data collection entry point.

Connects to Breeze, streams NIFTY + BANKNIFTY spot ticks via WebSocket,
snapshots the full option chain every 5 minutes, and writes everything to
PostgreSQL. Self-terminates at 15:35 IST.

Usage:
    python collect.py
    python collect.py --symbols NIFTY BANKNIFTY --chain-interval 300
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure runtime directories exist
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
    p = argparse.ArgumentParser(description="NSE Tick Data Collector — Breeze → PostgreSQL")
    p.add_argument(
        "--symbols", nargs="+", default=["NIFTY", "BANKNIFTY"],
        help="Underlying symbols to collect (default: NIFTY BANKNIFTY)",
    )
    p.add_argument(
        "--chain-interval", type=int, default=300,
        help="Option chain snapshot interval in seconds (default: 300 = 5 min)",
    )
    p.add_argument(
        "--chain-depth", type=int, default=10,
        help="ATM ± N strikes to capture per snapshot (default: 10)",
    )
    p.add_argument(
        "--spot-batch", type=float, default=1.0,
        help="Spot tick flush interval in seconds (default: 1.0)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    from collector import CollectorConfig, DataCollectorRunner

    cfg = CollectorConfig(
        symbols            = args.symbols,
        chain_interval_sec = args.chain_interval,
        chain_atm_depth    = args.chain_depth,
        spot_batch_sec     = args.spot_batch,
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
