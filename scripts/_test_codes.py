import os, sys
from dotenv import load_dotenv
load_dotenv('d:/repos/Algotime/.env')
sys.path.insert(0, 'd:/repos/Algotime')
from breeze_connect import BreezeConnect
api = BreezeConnect(api_key=os.environ['BREEZE_API_KEY'])
api.generate_session(api_secret=os.environ['BREEZE_API_SECRET'], session_token=os.environ['BREEZE_SESSION_TOKEN'])

tests = [
    ('RELIND', 'NSE', 'RELIANCE'),
    ('HDFBAN', 'NSE', 'HDFCBANK'),
    ('INFTEC', 'NSE', 'INFY'),
    ('STABAN', 'NSE', 'SBIN'),
    ('COALIN', 'NSE', 'COALINDIA'),
]
for code, exch, label in tests:
    resp = api.get_historical_data_v2(
        interval='1day',
        from_date='2025-01-01T00:00:00.000Z',
        to_date='2025-01-10T23:59:59.000Z',
        stock_code=code, exchange_code=exch, product_type='cash',
        expiry_date='', right='', strike_price='')
    recs = resp.get('Success') or []
    status = resp.get('Status')
    sample = recs[0].get('close', '?') if recs else 'no data'
    print(f"{label:<14} {code:<8} Status={status} Records={len(recs)} close={sample}")
