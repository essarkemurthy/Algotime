#!/usr/bin/env python3
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import psycopg2

conn = psycopg2.connect(os.environ["DB_URL"])
cur = conn.cursor()

cur.execute("""
    SELECT symbol,
           bool_or(interval='1d')  AS has_1d,
           bool_or(interval='30m') AS has_30m,
           bool_or(interval='5m')  AS has_5m,
           bool_or(interval='1m')  AS has_1m
    FROM candles
    GROUP BY symbol
    ORDER BY symbol
""")
rows = cur.fetchall()
conn.close()

print(f"Total symbols in DB: {len(rows)}")
print()
print(f"{'SYMBOL':<18} {'1d':<5} {'30m':<5} {'5m':<5} {'1m':<5}")
print("-" * 42)
for sym, d, t, f, m in rows:
    mark = lambda x: "YES" if x else "NO "
    print(f"{sym:<18} {mark(d):<5} {mark(t):<5} {mark(f):<5} {mark(m):<5}")

print()
print("=" * 42)
print("SYMBOLS WITH COMPLETE DATA (all 4 intervals)")
print("=" * 42)
complete = [sym for sym,d,t,f,m in rows if all([d,t,f,m])]
print(f"Count: {len(complete)}")
for s in complete:
    print(f"  {s}")

print()
print("=" * 42)
print("SYMBOLS WITH MISSING INTERVALS")
print("=" * 42)
missing = [(sym,d,t,f,m) for sym,d,t,f,m in rows if not all([d,t,f,m])]
print(f"Count: {len(missing)}")
for sym, d, t, f, m in missing:
    gaps = [iv for iv,flag in [("1d",d),("30m",t),("5m",f),("1m",m)] if not flag]
    present = [iv for iv,flag in [("1d",d),("30m",t),("5m",f),("1m",m)] if flag]
    print(f"  {sym:<18} has: {', '.join(present):<20}  missing: {', '.join(gaps)}")
