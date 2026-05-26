import json
from pathlib import Path
data = json.load(open('d:/repos/Algotime/data/symbols.json'))
nse = [d for d in data if d['exchange']=='NSE' and d['product_type']=='Equity']

for kw in ['IRFC','RAIL FINANCE','ZOMATO','ETERNAL','BLINKIT',
           'LTIMINDTREE','MINDTREE','LT INFOTECH','LARSEN INFO',
           'LT TECH','TECHNO ELECTRIC','L&T TECH']:
    hits = [d for d in nse if kw.upper() in d.get('company_name','').upper()
            or kw.upper() in d.get('stock_code','').upper()]
    for h in hits[:3]:
        cn = h['company_name']
        sc = h['stock_code']
        print(f"  [{kw}]  {sc:<10} {cn}")
