import os, sys
sys.path.insert(0, 'd:/repos/Algotime')
from dotenv import load_dotenv
load_dotenv('d:/repos/Algotime/.env')
from breeze_connect import BreezeConnect

api = BreezeConnect(api_key=os.environ['BREEZE_API_KEY'])
try:
    api.generate_session(
        api_secret=os.environ['BREEZE_API_SECRET'],
        session_token=os.environ['BREEZE_SESSION_TOKEN'])
    resp = api.get_historical_data_v2(
        interval='1day',
        from_date='2026-05-23T00:00:00.000Z',
        to_date='2026-05-24T23:59:59.000Z',
        stock_code='NIFTY', exchange_code='NSE', product_type='cash',
        expiry_date='', right='', strike_price='')
    recs = resp.get('Success') or []
    status = resp.get('Status')
    print(f'Session OK  Status={status}  Records={len(recs)}')
    if recs:
        last = recs[-1]
        print(f'Latest candle: {last.get("datetime")}  close={last.get("close")}')
except Exception as e:
    print(f'Session FAILED: {e}')
