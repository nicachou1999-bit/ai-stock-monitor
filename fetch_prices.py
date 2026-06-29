import requests
import json
from datetime import datetime
import pytz

STOCKS = {
    "^TWII":     {"name": "加權指數", "type": "index"},
    "2330.TW":   {"name": "台積電",  "type": "core",    "cheap": 1800,  "fair": 2200,  "rich": 2700},
    "6669.TW":   {"name": "緯穎",    "type": "observe", "cheap": 3600,  "fair": 5000,  "rich": 6500},
    "5274.TWO":  {"name": "信驊",    "type": "observe", "cheap": 7500,  "fair": 10000, "rich": 13000},
    "3017.TW":   {"name": "奇鋐",    "type": "observe", "cheap": 1900,  "fair": 2600,  "rich": 3200},
    "3533.TW":   {"name": "嘉澤",    "type": "observe", "cheap": 1500,  "fair": 2100,  "rich": 2850},
    "3711.TW":   {"name": "日月光",  "type": "observe", "cheap": 380,   "fair": 520,   "rich": 720},
    "2308.TW":   {"name": "台達電",  "type": "observe", "cheap": 1050,  "fair": 1500,  "rich": 2000},
    "00662.TW":  {"name": "00662",   "type": "etf"},
    "006208.TW": {"name": "006208",  "type": "etf"},
    "00919.TW":  {"name": "00919",   "type": "etf"},
    "00878.TW":  {"name": "00878",   "type": "etf"},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

def get_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        prev  = meta.get("previousClose") or price
        pct   = round((price - prev) / prev * 100, 2) if prev else 0
        return {"price": round(price, 2), "pct": pct}
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return {"price": None, "pct": 0}

def get_zone(price, info):
    if not price or "cheap" not in info:
        return info["type"]  # "etf" or "index"
    c, f, r = info["cheap"], info["fair"], info["rich"]
    if price <= c: return "buy"
    if price <= f: return "fair"
    if price <= r: return "watch"
    return "expensive"

tw = pytz.timezone("Asia/Taipei")
now = datetime.now(tw).strftime("%Y-%m-%d %H:%M")
output = {"updated": now, "data": {}}

for symbol, info in STOCKS.items():
    p = get_price(symbol)
    entry = {**info, **p, "zone": get_zone(p["price"], info)}
    output["data"][symbol] = entry
    if p["price"]:
        print(f"  {info['name']:8s}: {p['price']:>10,.2f}  ({p['pct']:+.2f}%)  {entry['zone']}")

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\ndata.json updated at {now}")
