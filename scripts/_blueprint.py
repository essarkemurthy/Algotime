import psycopg2, os
from dotenv import load_dotenv
load_dotenv('D:/repos/Algotime/.env')

url = os.environ['DB_URL']
# parse url for display
import re
m = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', url)
user, pwd, host, port, dbname = m.groups() if m else ('?','?','?','?','?')

conn = psycopg2.connect(url)
cur  = conn.cursor()

cur.execute('SELECT current_database(), version()')
db_name, ver = cur.fetchone()

cur.execute('SELECT pg_size_pretty(pg_database_size(current_database()))')
db_size = cur.fetchone()[0]

cur.execute('SELECT pg_size_pretty(pg_total_relation_size(%s))', ('candles',))
candles_size = cur.fetchone()[0]

cur.execute('SELECT COUNT(*), COUNT(DISTINCT symbol), COUNT(DISTINCT interval) FROM candles')
total_rows, sym_count, iv_count = cur.fetchone()

print("=" * 70)
print("DATABASE BLUEPRINT")
print("=" * 70)
print(f"  Database name : {db_name}")
print(f"  Host          : {host}")
print(f"  Port          : {port}")
print(f"  User          : {user}")
print(f"  DB size       : {db_size}")
print(f"  candles table : {candles_size}")
print(f"  Total candles : {total_rows:,}")
print(f"  Symbols       : {sym_count}")
print(f"  Intervals     : {iv_count}")
print()

# Per-symbol summary
print("=" * 70)
print("DATA INVENTORY — by Symbol")
print("=" * 70)
cur.execute("""
    SELECT symbol,
           STRING_AGG(DISTINCT interval, ', ' ORDER BY interval) as ivs,
           COUNT(*) as rows,
           MIN(ts)::date as from_dt,
           MAX(ts)::date as to_dt
    FROM candles
    GROUP BY symbol
    ORDER BY symbol
""")
rows = cur.fetchall()
print(f"{'SYMBOL':<16} {'INTERVALS':<22} {'ROWS':>8}  {'FROM':<12} {'TO':<12} HISTORY")
print("-" * 80)
for r in rows:
    days = (r[4] - r[3]).days if r[3] and r[4] else 0
    mo   = round(days / 30.4, 1)
    print(f"{r[0]:<16} {r[1]:<22} {r[2]:>8}  {str(r[3]):<12} {str(r[4]):<12} {mo} months")

print()

# Per-interval detail
print("=" * 70)
print("DATA INVENTORY — by Symbol x Interval (full detail)")
print("=" * 70)
cur.execute("""
    SELECT symbol, interval, COUNT(*) as rows,
           MIN(ts)::date as from_dt, MAX(ts)::date as to_dt
    FROM candles
    GROUP BY symbol, interval
    ORDER BY symbol, interval
""")
rows = cur.fetchall()
print(f"{'SYMBOL':<16} {'INTV':<6} {'ROWS':>7}  {'FROM':<12} {'TO':<12} HISTORY")
print("-" * 70)
for r in rows:
    days = (r[4] - r[3]).days if r[3] and r[4] else 0
    mo   = round(days / 30.4, 1)
    print(f"{r[0]:<16} {r[1]:<6} {r[2]:>7}  {str(r[3]):<12} {str(r[4]):<12} {mo} mo")

conn.close()
