import json
from pathlib import Path
data = json.load(open('d:/repos/Algotime/data/symbols.json'))
nse = [d for d in data if d['exchange']=='NSE' and d['product_type']=='Equity']
skip = ('ETF','FUND','BOND','WARRANT','RIGHTS','ENTITL','SCHEME','OFS')

searches = [
    ('IRCTC',       ['RAILWAY CATERING','IRCTC']),
    ('IRFC',        ['RAILWAY FINANCE','IRFC']),
    ('ZOMATO',      ['ZOMATO']),
    ('LTTS',        ['L&T TECHNOLOGY','LT TECHNOLOGY SERV']),
    ('LTIM',        ['LTIMINDTREE','LTI MINDTREE','LARSEN TOUBRO INFO']),
]
for label, kws in searches:
    found = False
    for kw in kws:
        hits = [d for d in nse if kw.upper() in d.get('company_name','').upper()
                and not any(x in d.get('company_name','').upper() for x in skip)]
        if hits:
            h = hits[0]
            print(f"{label:<16} {h['stock_code']:<10} {h['company_name']}")
            found = True
            break
    if not found:
        print(f"{label:<16} NOT FOUND")
