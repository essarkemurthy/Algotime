"""
main.py — CLI entry point for the NSE Options Algo Engine.

Usage:
    python main.py                                      # defaults
    python main.py --strategy iron_condor --lots 2
    python main.py --help
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure runtime directories exist before anything imports from trade_engine
Path("data").mkdir(exist_ok=True)
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
        logging.FileHandler("logs/options_engine.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

from trade_engine import EngineConfig, OptionsAlgoEngine
from trade_engine.risk import StopLossManager


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NSE Options Algo Engine (Breeze Connect / ICICI Direct)"
    )
    p.add_argument("--strategy",     default="bull_put_spread",
                   choices=["bull_put_spread", "iron_condor"],
                   help="Options strategy to run (default: bull_put_spread)")
    p.add_argument("--expiry-type",  default="weekly",
                   choices=["weekly", "monthly"],
                   help="Expiry type (default: weekly)")
    p.add_argument("--underlying",   default="NIFTY",
                   help="Index or stock symbol (default: NIFTY)")
    p.add_argument("--lots",         default=1,    type=int,
                   help="Number of lots to trade (default: 1)")
    p.add_argument("--lot-size",     default=50,   type=int,
                   help="Lot size for the underlying (default: 50 for NIFTY)")
    p.add_argument("--spread-width", default=100,  type=int,
                   help="Points between short and long strike (default: 100)")
    p.add_argument("--delta",        default=0.25, type=float,
                   help="Target |delta| for short strikes (default: 0.25)")
    p.add_argument("--min-iv-rank",  default=40.0, type=float,
                   help="Minimum IV rank to enter a trade (default: 40)")
    p.add_argument("--sl-mult",      default=2.0,  type=float,
                   help="Stop-loss multiplier: exit when debit = N × credit (default: 2)")
    p.add_argument("--profit-pct",   default=0.50, type=float,
                   help="Profit target as fraction of max profit (default: 0.5)")
    p.add_argument("--poll",         default=300,  type=int,
                   help="Monitor poll interval in seconds (default: 300)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    log  = logging.getLogger(__name__)

    cfg = EngineConfig(
        underlying           = args.underlying,
        strategy             = args.strategy,
        expiry_type          = args.expiry_type,
        num_lots             = args.lots,
        lot_size             = args.lot_size,
        spread_width         = args.spread_width,
        short_delta_target   = args.delta,
        min_iv_rank          = args.min_iv_rank,
        stop_loss_multiplier = args.sl_mult,
        profit_target_pct    = args.profit_pct,
    )

    engine = OptionsAlgoEngine(cfg)
    try:
        engine.connect()
        entered = engine.run_entry_scan()
        if entered:
            engine.run_monitor_loop(poll_seconds=args.poll)
        else:
            log.info("No trade taken today.")
    except KeyboardInterrupt:
        log.info("Interrupted by user — attempting to flatten open position.")
        if engine.position and engine.position.is_open and engine.router:
            StopLossManager(engine.session, engine.router, cfg).force_flatten(engine.position)
    except Exception as exc:
        log.critical("Unhandled exception: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        engine.disconnect()


if __name__ == "__main__":
    main()
