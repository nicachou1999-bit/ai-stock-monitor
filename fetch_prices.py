import requests
import json
from datetime import datetime, timedelta
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
    "00662.TW":  {"name": "富邦NASDAQ",        "type": "etf"},
    "006208.TW": {"name": "富邦台50",           "type": "etf"},
    "00919.TW":  {"name": "群益台灣精選高息",   "type": "etf"},
    "00878.TW":  {"name": "國泰永續高股息",     "type": "etf"},
}

INDICATORS = {"^VIX": "vix", "^TNX": "yield10y", "TWD=X": "usdtwd"}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "application/json"}

def parse_int(s):
    try:
        return int(str(s).replace(',', ''))
    except:
        return 0

def get_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        prev  = meta.get("previousClose") or price
        pct   = round((price - prev) / prev * 100, 2) if prev else 0
        return {"price": round(price, 4), "pct": pct}
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return {"price": None, "pct": 0}

def get_zone(price, info):
    if not price or "cheap" not in info:
        return info["type"]
    c, f, r = info["cheap"], info["fair"], info["rich"]
    if price <= c: return "buy"
    if price <= f: return "fair"
    if price <= r: return "watch"
    return "expensive"

def get_twse_institutional(d8):
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={d8}&selectType=ALLBUT0999"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        data = r.json()
        if data.get('stat') != 'OK':
            return {}
        result = {}
        for row in data.get('data', []):
            code = row[0].strip()
            result[code] = {
                "foreign": parse_int(row[4]),
                "trust":   parse_int(row[10]),
                "dealer":  parse_int(row[11]),
                "total":   parse_int(row[18]),
            }
        print(f"  TWSE T86 {d8}: {len(result)} stocks")
        return result
    except Exception as e:
        print(f"  ERROR TWSE T86: {e}")
        return {}

def get_tpex_institutional(d_roc):
    url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&d={d_roc}&t=D&s=0,asc&o=json"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        data = r.json()
        rows = data.get('tables', [{}])[0].get('data', [])
        result = {}
        for row in rows:
            code = row[0].strip()
            result[code] = {
                "foreign": parse_int(row[4]),
                "trust":   parse_int(row[13]),
                "dealer":  parse_int(row[22]),
                "total":   parse_int(row[23]),
            }
        print(f"  TPEX {d_roc}: {len(result)} stocks")
        return result
    except Exception as e:
        print(f"  ERROR TPEX: {e}")
        return {}

def get_market_institutional(d8):
    url = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={d8}&type=day"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        data = r.json()
        if data.get('stat') != 'OK':
            return {}
        result = {}
        dealer_total = 0
        for row in data.get('data', []):
            name, net = row[0], parse_int(row[3])
            if '外資及陸資' in name:
                result['foreign'] = net
            elif name == '投信':
                result['trust'] = net
            elif '自營商' in name:
                dealer_total += net
        result['dealer'] = dealer_total
        result['total']  = result.get('foreign', 0) + result.get('trust', 0) + dealer_total
        return result
    except Exception as e:
        print(f"  ERROR BFI82U: {e}")
        return {}

# ---------- main ----------
tw      = pytz.timezone("Asia/Taipei")
now     = datetime.now(tw)
now_str = now.strftime("%Y-%m-%d %H:%M")

output = {"updated": now_str, "market": {}, "institutional_market": {}, "inst_date": "", "analysis": "", "data": {}}

print("Fetching prices...")
for symbol, info in STOCKS.items():
    p = get_price(symbol)
    entry = {**info, **p, "zone": get_zone(p["price"], info)}
    output["data"][symbol] = entry
    if p["price"]:
        print(f"  {info['name']:12s}: {p['price']:>10,.2f}  ({p['pct']:+.2f}%)  {entry['zone']}")

print("\nFetching market indicators...")
for symbol, key in INDICATORS.items():
    p = get_price(symbol)
    if p["price"]:
        output["market"][key] = round(p["price"], 3)
        print(f"  {key}: {p['price']}")

print("\nFetching institutional data...")
twse_inst = tpex_inst = mkt_inst = {}

for delta in range(0, 7):
    d = now - timedelta(days=delta)
    if d.weekday() >= 5:
        continue
    d8    = d.strftime("%Y%m%d")
    d_roc = f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"
    twse_inst = get_twse_institutional(d8)
    mkt_inst  = get_market_institutional(d8)
    tpex_inst = get_tpex_institutional(d_roc)
    if twse_inst:
        output["inst_date"] = d.strftime("%Y-%m-%d")
        break

for symbol, entry in output["data"].items():
    code = symbol.replace(".TWO", "").replace(".TW", "").replace("^", "")
    inst = tpex_inst.get(code) if ".TWO" in symbol else twse_inst.get(code)
    if inst:
        entry["institutional"] = {
            "foreign": round(inst["foreign"] / 1000),
            "trust":   round(inst["trust"]   / 1000),
            "dealer":  round(inst["dealer"]  / 1000),
            "total":   round(inst["total"]   / 1000),
        }
    else:
        entry["institutional"] = None

if mkt_inst:
    output["institutional_market"] = {
        "foreign": round(mkt_inst.get("foreign", 0) / 1e8),
        "trust":   round(mkt_inst.get("trust",   0) / 1e8),
        "dealer":  round(mkt_inst.get("dealer",  0) / 1e8),
        "total":   round(mkt_inst.get("total",   0) / 1e8),
    }
    m = output["institutional_market"]
    print(f"  大盤: 外資{m['foreign']:+d}億 投信{m['trust']:+d}億 自營{m['dealer']:+d}億")

try:
    with open("data.json", "r", encoding="utf-8") as f:
        existing = json.load(f)
        if existing.get("analysis"):
            output["analysis"] = existing["analysis"]
except:
    pass

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\ndata.json updated at {now_str}")
