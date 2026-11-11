"""
strategies — pure, I/O-free trading-strategy logic shared by the backtest CLI
(`python -m strategies.backtest <name>`) and the live signal runners.

Rule: a strategy module holds features + per-bar evaluation only. Data access,
notifications and journaling live in the callers, so backtest and live code
execute the very same signal function.
"""
