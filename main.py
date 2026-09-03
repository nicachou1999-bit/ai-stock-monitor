#!/usr/bin/env python3
"""
AI 每日投資顧問系統 v5 - main.py
巴菲特存股觀念 | 動態觀察名單 | 估值三價燈號 | 市場溫度計 | 持倉追蹤
"""
import urllib.request, json, os, glob, datetime, argparse

# 台灣時間（UTC+8）
TW_TZ = datetime.timezone(datetime.timedelta(hours=8))
def now_tw():
    return datetime.datetime.now(TW_TZ)

try:
    from flow_data import fetch_sector_data, fetch_stock_margin_detail, auto_update_annual_div
    from flow_html import make_flow_section
except ImportError:
    def fetch_sector_data(): return []
    def fetch_stock_margin_detail(codes): return {}
    def auto_update_annual_div(f): return (None, None)
    def make_flow_section(*a, **kw): return ""

HEADERS         = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE  = os.path.join(SCRIPT_DIR, "watchlist.json")
CACHE_FILE      = os.path.join(SCRIPT_DIR, "last_data.json")
INDICATORS_FILE = os.path.join(SCRIPT_DIR, "last_indicators.json")
DASHBOARD_FILE  = os.path.join(SCRIPT_DIR, "dashboard.html")
RESEARCH_DIR    = os.path.join(SCRIPT_DIR, "research")
ANALYSIS_CACHE_FILE = os.path.join(SCRIPT_DIR, "analysis_cache.json")
os.makedirs(RESEARCH_DIR, exist_ok=True)


def inject_cached_analysis(html):
    """重新產生頁面時，把上次 Claude 寫的深度解讀重新塞回去，避免被清空成預留位置。"""
    if not os.path.exists(ANALYSIS_CACHE_FILE):
        return html
    try:
        with open(ANALYSIS_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        insight = cache.get("analysis")
        if not insight:
            return html
    except Exception:
        return html
    import re
    pattern = r'<div class="claude-insight[^"]*" id="claude-insight">.*?</div>'
    new_div = f'<div class="claude-insight visible" id="claude-insight">{insight}</div>'
    if re.search(pattern, html, re.DOTALL):
        return re.sub(pattern, new_div, html, count=1, flags=re.DOTALL)
    return html


# ── 觀察名單 ──────────────────────────────────────────────────────────────
def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        print(f"  警告：找不到 {WATCHLIST_FILE}")
        return {}
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        wl = json.load(f)
    return wl.get("stocks", {})


# ── 研究報告 ──────────────────────────────────────────────────────────────
def find_research_files():
    mapping = {}
    for fpath in glob.glob(os.path.join(RESEARCH_DIR, "*.html")):
        fname = os.path.basename(fpath)
        parts = fname.rsplit("-", 1)
        if len(parts) == 2:
            raw = parts[0]
            rel = f"research/{fname}"
            if raw not in mapping or fname > os.path.basename(mapping[raw]):
                mapping[raw] = rel
    return mapping



# ── 技術指標計算 ──────────────────────────────────────────────────────────
def calc_technicals(closes, price):
    """回傳 (ma20, bias, rsi14)"""
    ma20 = round(sum(closes[-20:]) / 20, 2) if len(closes) >= 20 else None
    bias = round((price - ma20) / ma20 * 100, 2) if ma20 and price else None
    rsi = None
    if len(closes) >= 15:
        diffs = [closes[i] - closes[i-1] for i in range(len(closes)-14, len(closes))]
        gains = sum(d for d in diffs if d > 0) / 14
        losses = sum(-d for d in diffs if d < 0) / 14
        rsi = round(100 - 100 / (1 + gains / losses), 1) if losses > 0 else 100.0
    return ma20, bias, rsi

def get_batch_prices(cheap, fair):
    """分批進場觸發價（估值區間錨定，非短波低點）"""
    if not cheap or not fair:
        return None
    mid = (cheap + fair) / 2
    return [
        round(fair, 0),           # 第1批：合理布局上限
        round(mid, 0),            # 第2批：估值中點
        round(cheap, 0),          # 第3批：積極買進
        round(cheap * 0.88, 0),   # 第4批：深度折價 -12%
    ]

_BATCH_LABELS = ["合理布局", "估值中點", "積極買進", "深度折價"]

# ── 股價抓取 ──────────────────────────────────────────────────────────────
def fetch_price(ticker, cfg):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=60d"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    result = data["chart"]["result"][0]
    meta   = result["meta"]
    price  = meta.get("regularMarketPrice")
    closes = [c for c in result["indicators"]["quote"][0].get("close", []) if c is not None]
    prev   = closes[-2] if len(closes) >= 2 else meta.get("chartPreviousClose")
    change = round(price - prev, 2) if price and prev else None
    pct    = round(change / prev * 100, 2) if change and prev else None
    ma20, bias, rsi = calc_technicals(closes, price) if price else (None, None, None)
    return {
        "ticker":       ticker,
        "name":         cfg["name"],
        "type":         cfg.get("type", "core"),
        "grade":        cfg.get("grade", ""),
        "thesis":       cfg.get("thesis", ""),
        "category":     cfg.get("category", ""),
        "cheap":        cfg.get("cheap"),
        "fair":         cfg.get("fair"),
        "rich":         cfg.get("rich"),
        "annual_div":         cfg.get("annual_div"),
        "benchmark_pe":       cfg.get("benchmark_pe"),
        "research_conclusion": cfg.get("research_conclusion"),
        "last_researched":    cfg.get("last_researched"),
        "nav_trend":          cfg.get("nav_trend"),
        "payout_quality":     cfg.get("payout_quality"),
        "fill_rate_1y":       cfg.get("fill_rate_1y"),
        "div_history":        cfg.get("div_history"),
        "etf_research_conclusion": cfg.get("etf_research_conclusion"),
        "etf_last_researched":     cfg.get("etf_last_researched"),
        "price":        price,
        "prev":         round(prev, 2) if prev else None,
        "change":       change,
        "pct":          pct,
        "w52_high":     meta.get("fiftyTwoWeekHigh"),
        "w52_low":      meta.get("fiftyTwoWeekLow"),
        "ma20":         ma20,
        "bias":         bias,
        "rsi":          rsi,
    }

def fetch_all(tickers):
    results = {}
    for ticker, cfg in tickers.items():
        try:
            results[ticker] = fetch_price(ticker, cfg)
            p = results[ticker]
            print(f"  OK  {cfg['name']:6s}: {p['price']:>12,.2f}  ({p['pct']:+.2f}%)")
        except Exception as e:
            print(f"  NG  {cfg['name']:6s}: {e}")
            results[ticker] = {
                "ticker": ticker, "name": cfg["name"], "type": cfg.get("type","core"),
                "grade": cfg.get("grade",""), "thesis": cfg.get("thesis",""),
                "category": cfg.get("category",""),
                "cheap": cfg.get("cheap"), "fair": cfg.get("fair"), "rich": cfg.get("rich"),
                "annual_div": cfg.get("annual_div"), "benchmark_pe": cfg.get("benchmark_pe"),
                "research_conclusion": cfg.get("research_conclusion"),
                "last_researched": cfg.get("last_researched"),
                "nav_trend": cfg.get("nav_trend"),
                "payout_quality": cfg.get("payout_quality"),
                "fill_rate_1y": cfg.get("fill_rate_1y"),
                "div_history": cfg.get("div_history"),
                "etf_research_conclusion": cfg.get("etf_research_conclusion"),
                "etf_last_researched": cfg.get("etf_last_researched"),
                "price": None, "prev": None, "change": None, "pct": None,
                "w52_high": None, "w52_low": None,
                "ma20": None, "bias": None, "rsi": None,
            }
    return results


# ── 市場溫度計 ────────────────────────────────────────────────────────────
def fetch_market_indicators():
    results = {}
    def pn(s):
        try: return int(str(s).replace(",","").replace(" ",""))
        except: return 0

    # Yahoo Finance: VIX / 10Y / USD/TWD
    for key, ticker, name in [
        ("VIX",    "^VIX",  "VIX 恐慌指數"),
        ("TNX",    "^TNX",  "美10年債殖利率"),
        ("USDTWD", "TWD=X", "美元／台幣"),
    ]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read())
            res = d["chart"]["result"][0]
            price  = res["meta"].get("regularMarketPrice")
            closes = [c for c in res["indicators"]["quote"][0].get("close", []) if c is not None]
            prev   = closes[-2] if len(closes) >= 2 else None
            pct    = round((price - prev) / prev * 100, 2) if price and prev else None
            results[key] = {"name": name, "value": price, "pct": pct}
        except:
            results[key] = {"name": name, "value": None, "pct": None}

    # TWSE 三大法人買賣超
    try:
        url = "https://www.twse.com.tw/fund/BFI82U?response=json&dayDate=&type=day"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        foreign = invest = dealer = total = None
        for row in d.get("data", []):
            n, net = row[0], pn(row[3]) if len(row) > 3 else 0
            if "外資及陸資(不含外資自營商)" in n: foreign = net
            elif "投信" in n:                     invest  = net
            elif "自營商(自行買賣)" in n:          dealer  = net
            elif "合計" in n:                     total   = net
        results["INST"] = {
            "name": "三大法人買賣超",
            "date": d.get("date", ""),
            "foreign": foreign, "invest": invest,
            "dealer": dealer,   "total":  total,
        }
    except:
        results["INST"] = {"name":"三大法人買賣超","date":"",
                           "foreign":None,"invest":None,"dealer":None,"total":None}



    # TWSE 融資餘額
    try:
        url = "https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date=&selectType=ALL"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        today = prev_ = None
        for t in d.get("tables", []):
            for row in t.get("data", []):
                if row[0] == "融資金額(仟元)":
                    prev_  = pn(row[4])
                    today  = pn(row[5])
                    break
        results["MARGIN"] = {
            "name": "融資餘額",
            "date": d.get("date", ""),
            "today": today, "prev": prev_,
            "change": (today - prev_) if today and prev_ else None,
        }
    except:
        results["MARGIN"] = {"name":"融資餘額","date":"","today":None,"prev":None,"change":None}

    return results

def calc_market_temp(ind):
    vix     = (ind.get("VIX")    or {}).get("value")
    foreign = (ind.get("INST")   or {}).get("foreign") or 0
    mchg    = (ind.get("MARGIN") or {}).get("change")  or 0
    danger = 0
    if vix and vix < 15:                      danger += 1
    if foreign < -15_000_000_000:             danger += 1   # 外資賣超 150億+
    if mchg > 8_000_000_000:                  danger += 1   # 融資增加 80億+
    cool = 0
    if vix and vix > 25:                      cool += 1
    if foreign < -10_000_000_000:             cool += 1
    if danger >= 2:
        return "🔴", "過熱警示", "#ef4444", "多項指標顯示市場情緒過熱，不宜追高，存股族按兵不動等回調"
    if cool >= 1:
        return "🟢", "留意買點", "#10b981", "恐慌訊號出現，價值投資人可對照估值燈號伺機布局"
    return "🟡", "正常觀察", "#f59e0b", "市場正常運行，按估值燈號紀律操作即可"


# ── 估值邏輯 ──────────────────────────────────────────────────────────────
def calc_signal(pct):
    if pct is None: return "T2", "震盪", "#f59e0b"
    if pct >  1.0:  return "T1", "主升", "#10b981"
    if pct < -1.0:  return "T3", "退潮", "#ef4444"
    return "T2", "震盪", "#f59e0b"

def get_zone(price, cheap, fair, rich):
    if not price or not cheap: return "none", "待研究", "#94a3b8"
    if price <= cheap: return "z1", "積極買進", "#10b981"
    if price <= fair:  return "z2", "合理布局", "#34d399"
    if price <= rich:  return "z3", "謹慎觀察", "#f59e0b"
    return "z4", "偏貴等待", "#ef4444"

def get_bar_data(price, cheap, fair, rich):
    if not cheap: return (25, 25, 25, 25, 50)
    bar_min = cheap * 0.80
    bar_max = rich  * 1.20
    span    = bar_max - bar_min
    w1 = round((cheap - bar_min) / span * 100, 1)
    w2 = round((fair  - cheap)   / span * 100, 1)
    w3 = round((rich  - fair)    / span * 100, 1)
    w4 = round(100 - w1 - w2 - w3, 1)
    marker = round(max(2, min(98, (price - bar_min) / span * 100)), 1) if price else 50
    return (w1, w2, w3, w4, marker)


# ── 今日建議 ──────────────────────────────────────────────────────────────
def build_advisor(signal, data):
    buy_z, fair_z = [], []
    for v in data.values():
        if v["type"] != "core" or not v.get("price"): continue
        zid, _, _ = get_zone(v["price"], v["cheap"], v["fair"], v["rich"])
        if   zid == "z1": buy_z.append(v["name"])
        elif zid == "z2": fair_z.append(v["name"])
    if signal == "T1":
        if buy_z:
            return f"大盤偏多。{' / '.join(buy_z)} 進入積極買進區，符合「以合理價格買入優質企業」原則，可分批布局。"
        elif fair_z:
            return f"大盤偏多。{' / '.join(fair_z)} 在合理估值區，是逐步建倉的時機，可小量布局。"
        else:
            return "大盤偏多，但核心標的估值偏高，耐心等待回檔至合理區間再出手。不追高，是價值投資最重要的紀律。"
    elif signal == "T3":
        if buy_z:
            return f"大盤退潮，{' / '.join(buy_z)} 已進入超值買進區——這正是長期投資人分批建倉的時機。「別人恐懼時我貪婪。」"
        else:
            return "大盤退潮，繼續觀察等待。現金是最好的武器，等候估值燈號轉綠再出手。"
    else:
        if buy_z:
            return f"市場震盪，{' / '.join(buy_z)} 估值已到積極買進區，可小量分批布局。"
        elif fair_z:
            return f"市場震盪，{' / '.join(fair_z)} 處於合理估值區，可考慮逐步建立基礎部位。"
        else:
            return "市場震盪，核心標的估值偏高，耐心等候回調。現金等候，不追高是最好的策略。"


# ── 風險提醒 ──────────────────────────────────────────────────────────────
def build_warnings(signal, data):
    warnings = []
    if signal == "T3":
        warnings.append(("danger","大盤退潮訊號","指數跌幅超過1%——長期存股者無需恐慌，暫緩新增部位，等信號好轉"))
    rich_list, crash_list = [], []
    for v in data.values():
        if v["type"] != "core" or not v.get("price"): continue
        zid, _, _ = get_zone(v["price"], v["cheap"], v["fair"], v["rich"])
        if zid == "z4": rich_list.append(v["name"])
        if v.get("pct") and v["pct"] <= -5:
            crash_list.append(f"{v['name']}({v['pct']:+.1f}%)")
        if zid == "z1":
            warnings.append(("ok", f"買進機會：{v['name']}",
                             f"{v['name']} 進入積極買進區間，符合長期布局標準"))
    if rich_list:
        warnings.append(("warn","估值偏高，暫停加碼",
                         f"{' / '.join(rich_list)} 超過偏貴區間——此時不宜新建部位，耐心等候估值回落至合理區"))
    if crash_list:
        warnings.append(("ok","今日大跌，留意機會",
                         f"{' / '.join(crash_list)} 單日跌幅 ≥5%——若基本面未變，回檔往往是布局機會"))
    if not warnings:
        warnings.append(("info","目前無重大風險警示","市場整體穩定，繼續觀察估值燈號，等候進場時機"))
    return warnings


# ── 市場深度觀察 ──────────────────────────────────────────────────────────
def build_deep_analysis(signal, data):
    valuation_stocks = [v for v in data.values() if v["type"] == "core" and v.get("price")]
    all_stocks       = [v for v in data.values() if v["type"] in ("core","observe") and v.get("price")]
    down5    = [v for v in valuation_stocks if v.get("pct") and v["pct"] <= -5]
    up3      = [v for v in valuation_stocks if v.get("pct") and v["pct"] >= 3]
    twii_pct = data.get("^TWII", {}).get("pct") or 0
    twii_abs = abs(twii_pct)
    n_down5  = len(down5)
    if n_down5 >= 2 and twii_abs < 2.0:
        pattern       = "板塊輪出 / 類股換手"
        pattern_color = "#f59e0b"
        pattern_desc  = (f"今日 {n_down5} 檔個股跌幅超過5%，但加權指數僅波動 {twii_abs:.1f}%。"
                         "資金在族群之間換手，非系統性賣壓。")
    elif twii_pct < -2 and n_down5 >= 3:
        pattern       = "全面下殺 / 系統性賣壓"
        pattern_color = "#ef4444"
        pattern_desc  = (f"大盤跌幅 {twii_pct:.2f}%，{n_down5} 檔個股跌逾5%。"
                         "留意是否有系統性風險觸發（Fed政策、地緣政治、財報雷）。")
    elif len(up3) >= 2 and twii_abs < 1.0:
        pattern       = "個股補漲 / 標的輪動"
        pattern_color = "#10b981"
        pattern_desc  = (f"{len(up3)} 檔個股逆勢上漲超過3%，市場呈現輪動格局。精選標的仍有表現空間。")
    else:
        pattern       = "正常震盪整理"
        pattern_color = "#94a3b8"
        pattern_desc  = "市場整體在正常波動範圍內，持續觀察估值燈號，按計劃操作。"
    rich_stocks = [v["name"] for v in valuation_stocks
                   if get_zone(v["price"],v["cheap"],v["fair"],v["rich"])[0] == "z4"]
    buy_stocks  = [v["name"] for v in valuation_stocks
                   if get_zone(v["price"],v["cheap"],v["fair"],v["rich"])[0] == "z1"]
    context = ("AI基礎建設長期需求穩固——TSMC產能能見度至2030年，全球CSP年度AI資本支出持續擴張。"
               "市場波動在預期範圍內，按估值燈號分批操作即可。")
    if buy_stocks:
        buffett_advice = (f"{' / '.join(buy_stocks)} 目前在積極買進區，符合「以合理價格買入優質企業，然後長期持有」的原則。"
                          "可分批建倉——分散時間成本比等完美低點更重要。")
    elif rich_stocks:
        buffett_advice = (f"{' / '.join(rich_stocks[:3])} 估值偏高，現在不是新建部位的時機。"
                          "耐心等候回調至合理區間，現金是最好的護城河。")
    else:
        buffett_advice = ("核心標的估值合理，是逐步建倉的時機。定期定額、分批布局，讓時間和複利做工。")
    return {"pattern": pattern, "pattern_color": pattern_color, "pattern_desc": pattern_desc,
            "context": context, "buffett_advice": buffett_advice}


# ── 月度報告 ──────────────────────────────────────────────────────────────
def read_monthly_report():
    import re
    month = now_tw().strftime('%Y-%m')
    for p in [os.path.normpath(os.path.join(SCRIPT_DIR,'..', f'monthly-report-{month}.md')),
              os.path.join(SCRIPT_DIR, f'monthly-report-{month}.md')]:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return month, _md_to_html(f.read())
    return None, None

def _md_to_html(text):
    import re
    out = []
    for line in text.split('\n'):
        s = line.rstrip()
        if s.startswith('# '):   out.append(f'<div class="mr-h1">{s[2:]}</div>')
        elif s.startswith('## '): out.append(f'<div class="mr-h2">{s[3:]}</div>')
        elif s.startswith('### '):out.append(f'<div class="mr-h3">{s[4:]}</div>')
        elif s.startswith('- '):
            body = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', s[2:])
            out.append(f'<div class="mr-li">&#x2022; {body}</div>')
        elif s == '':             out.append('<div class="mr-gap"></div>')
        else:
            body = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', s)
            out.append(f'<div class="mr-p">{body}</div>')
    return '\n'.join(out)



# ── 今日結論 ──────────────────────────────────────────────────────────────
def build_daily_conclusion(data):
    rows = []
    for v in data.values():
        if v["type"] != "core" or not v.get("price"):
            continue
        price  = v["price"]
        cheap  = v.get("cheap")
        fair   = v.get("fair")
        rich   = v.get("rich")
        rsi    = v.get("rsi")
        bias   = v.get("bias")
        name   = v["name"]
        if not cheap:
            continue

        zid, zlabel, _ = get_zone(price, cheap, fair, rich)
        rsi_ok  = rsi is not None and rsi <= 40
        bias_ok = bias is not None and bias <= -5

        # 決定行動
        if zid == "z1" and (rsi_ok or bias_ok):
            action, ac = "🟢 強烈買進", "#10b981"
            detail = f"估值積極買進區 + {'RSI超賣' if rsi_ok else '乖離超賣'}"
        elif zid == "z1":
            action, ac = "🟢 可以布局", "#10b981"
            detail = f"估值已到積極買進區，分批買進"
        elif zid == "z2" and (rsi_ok or bias_ok):
            action, ac = "🟡 加碼機會", "#f59e0b"
            detail = f"合理估值 + 技術超賣，可小量加碼"
        elif zid == "z2":
            action, ac = "🟡 持有觀察", "#f59e0b"
            detail = "估值合理，持有即可，等更好價位"
        elif zid in ("z3","z4") and (rsi_ok or bias_ok):
            action, ac = "⚪ 技術超賣但估值偏高", "#94a3b8"
            detail = "技術面跌深，但估值仍偏貴，僅持有者繼續抱"
        else:
            action, ac = "🔴 暫停加碼", "#ef4444"
            detail = f"估值偏高（{zlabel}），新資金等待"

        # 今日建議掛單價（最近一批觸發價）
        batches = get_batch_prices(cheap, fair) or []
        next_trigger = next((b for b in batches if b >= price * 0.98), None)
        if next_trigger and next_trigger <= price * 1.02:
            order_str = f"可掛 ≤ {next_trigger:,.0f}"
        elif next_trigger:
            order_str = f"距觸發 {(next_trigger-price)/price*100:+.1f}%（{next_trigger:,.0f}）"
        else:
            order_str = "已超過所有觸發價，暫停"

        rsi_str  = f"{rsi:.0f}" if rsi is not None else "N/A"
        bias_str = f"{bias:+.1f}%" if bias is not None else "N/A"
        rows.append((name, action, ac, detail, order_str, rsi_str, bias_str))

    return rows

# ── HTML 生成 ─────────────────────────────────────────────────────────────
def generate_html(data, signal, signal_label, signal_color, advisor, warnings, deep,
                  data_time, generated_at, research_map, indicators, monthly=None):

    conclusion_rows = build_daily_conclusion(data)

    def fp(p):     return f"{p:,.0f}" if p else "N/A"
    def fpct(p):
        if p is None: return "N/A"
        return ("+" if p >= 0 else "") + f"{p:.2f}%"
    def pc(p):     return "#94a3b8" if p is None else ("#10b981" if p >= 0 else "#ef4444")
    def arr(p):    return "-" if p is None else ("▲" if p >= 0 else "▼")
    def fmt_b(n):  # 格式化億元
        if n is None: return "N/A"
        b = n / 100_000_000
        sign = "+" if b >= 0 else ""
        return f"{sign}{b:,.1f}億"

    twii      = data.get("^TWII", {})
    core_stks = [v for v in data.values() if v["type"] == "core"]
    obs_stks  = [v for v in data.values() if v["type"] == "observe"]

    # ── 股票卡片生成器 ──
    def make_card(s):
        price  = s.get("price")
        cheap, fair, rich = s.get("cheap"), s.get("fair"), s.get("rich")
        zid, zlabel, zcolor = get_zone(price, cheap, fair, rich)
        w1, w2, w3, w4, mpos = get_bar_data(price, cheap, fair, rich)
        grade = s.get("grade","")
        gc    = "#10b981" if grade == "A" else ("#f59e0b" if grade == "B" else "#94a3b8")
        chg_abs = ""
        if s.get("change") is not None:
            sign = "+" if s["change"] >= 0 else ""
            chg_abs = f"({sign}{s['change']:,.0f})"
        ticker_key = s["ticker"].replace(".TW","").replace(".TWO","")
        research_link = ""
        if ticker_key in research_map:
            research_link = f'<a class="research-link" href="{research_map[ticker_key]}">📄 研究報告</a>'
        # 估值條（observe股無估值則顯示待研究標籤）
        if cheap and fair and rich:
            bar_html = (
                f'<div class="zone-bar-wrap">'
                f'<div class="zone-bar">'
                f'<div class="zs z1s" style="width:{w1}%"></div>'
                f'<div class="zs z2s" style="width:{w2}%"></div>'
                f'<div class="zs z3s" style="width:{w3}%"></div>'
                f'<div class="zs z4s" style="width:{w4}%"></div>'
                f'<div class="zone-dot" style="left:{mpos}%"></div>'
                f'</div>'
                f'<div class="zone-prices">'
                f'<span style="color:#10b981">{fp(cheap)}</span>'
                f'<span style="color:#34d399">{fp(fair)}</span>'
                f'<span style="color:#f59e0b">{fp(rich)}</span>'
                f'</div></div>'
            )
        else:
            bar_html = '<div class="zone-bar-wrap no-val">估值待深度研究後設定</div>'
        tw_ticker = s['ticker'].replace('.TW','').replace('.TWO','')
        yf_url = f"https://tw.stock.yahoo.com/quote/{tw_ticker}"

        # ── 技術指標 HTML ──
        rsi   = s.get("rsi")
        bias  = s.get("bias")
        ma20  = s.get("ma20")
        price = s.get("price")
        cheap_v = s.get("cheap")
        fair_v  = s.get("fair")

        # RSI 燈號
        if rsi is not None:
            if rsi <= 30:   rsi_c, rsi_lbl = "#10b981", f"RSI {rsi:.0f} 超賣"
            elif rsi <= 50: rsi_c, rsi_lbl = "#34d399", f"RSI {rsi:.0f} 偏弱"
            elif rsi <= 70: rsi_c, rsi_lbl = "#f59e0b", f"RSI {rsi:.0f} 中性"
            else:           rsi_c, rsi_lbl = "#ef4444", f"RSI {rsi:.0f} 超買"
        else:
            rsi_c, rsi_lbl = "#94a3b8", "RSI N/A"

        # 乖離率燈號
        if bias is not None:
            if bias <= -8:  bias_c, bias_lbl = "#10b981", f"乖離 {bias:+.1f}% 超賣"
            elif bias <= -3:bias_c, bias_lbl = "#34d399", f"乖離 {bias:+.1f}% 偏低"
            elif bias <= 5: bias_c, bias_lbl = "#f59e0b", f"乖離 {bias:+.1f}% 正常"
            else:           bias_c, bias_lbl = "#ef4444", f"乖離 {bias:+.1f}% 偏高"
        else:
            bias_c, bias_lbl = "#94a3b8", "乖離 N/A"

        tech_html = (
            f'<div class="tech-row">'
            f'<span class="tech-tag" style="color:{rsi_c};border-color:{rsi_c}">{rsi_lbl}</span>'
            f'<span class="tech-tag" style="color:{bias_c};border-color:{bias_c}">{bias_lbl}</span>'
            + (f'<span class="tech-ma">MA20 {fp(ma20)}</span>' if ma20 else '')
            + f'</div>'
        ) if cheap_v else ""

        # ── 分批觸發價 HTML ──
        batch_html = ""
        if cheap_v and fair_v and price:
            batches = get_batch_prices(cheap_v, fair_v)
            batch_rows = ""
            for i, bp in enumerate(batches):
                lbl = _BATCH_LABELS[i] if i < len(_BATCH_LABELS) else f"第{i+1}批"
                diff_pct = (bp - price) / price * 100
                if diff_pct <= 0:
                    d_c, d_str = "#10b981", f"{diff_pct:+.1f}% ✅已觸發"
                else:
                    d_c, d_str = "#94a3b8", f"差 +{diff_pct:.1f}%"
                batch_rows += (
                    f'<div class="batch-row">'
                    f'<span class="batch-n">{lbl}</span>'
                    f'<span class="batch-p">≤ {fp(bp)}</span>'
                    f'<span class="batch-d" style="color:{d_c}">{d_str}</span>'
                    f'</div>'
                )
            batch_html = f'<div class="batch-wrap"><div class="batch-title">分批進場觸發價</div>{batch_rows}</div>'

        return (
            f'<div class="stock-card">'
            f'<div class="card-top">'
            f'<div>'
            f'<a class="card-name card-link" href="{yf_url}" target="_blank" rel="noopener">{s.get("name","")}</a>'
            f'<span class="card-ticker">{tw_ticker}</span>'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:6px">'
            f'<span class="grade-badge" style="background:{gc}22;color:{gc};border-color:{gc}">{grade or "—"}</span>'
            f'{research_link}</div></div>'
            f'<div class="card-price">{fp(price)}</div>'
            f'<div class="card-change" style="color:{pc(s.get("pct"))}">'
            f'{arr(s.get("pct"))} {fpct(s.get("pct"))} <span class="chg-abs">{chg_abs}</span>'
            f'</div>'
            f'{bar_html}'
            f'<div class="zone-label" style="background:{zcolor}22;color:{zcolor};border-color:{zcolor}">{zlabel}</div>'
            + tech_html
            + batch_html
            + f'<div class="card-thesis">{s.get("thesis","")}</div>'
            + (f'<div class="card-conclusion">{s["research_conclusion"]}'
               + (f' <span class="card-researched">({s["last_researched"]})</span>' if s.get("last_researched") else "")
               + f'</div>'
               if s.get("type") == "observe" and s.get("research_conclusion") else "")
            + f'</div>'
        )

    def make_etf_card(s):
        price    = s.get("price")
        ticker   = s.get("ticker", "")
        category = s.get("category", "ETF")
        cat_colors = {
            "台股核心": "#3b82f6", "美股AI": "#8b5cf6",
            "現金流":  "#10b981", "美股廣度": "#f59e0b",
        }
        cat_c = cat_colors.get(category, "#64748b")
        tw_ticker2 = ticker.replace('.TW','').replace('.TWO','')
        yf_url = f"https://tw.stock.yahoo.com/quote/{tw_ticker2}"


        # ── 每隻 ETF 用最適合其本質的估值指標 ──
        if ticker == "0050.TW":
            # 台股大盤本益比（人工季度更新，存於 watchlist benchmark_pe）
            tw_pe = s.get("benchmark_pe")
            if tw_pe:
                if tw_pe < 16:
                    sig_label, sig_c = "台股P/E偏低，積極考慮進場", "#10b981"
                elif tw_pe <= 22:
                    sig_label, sig_c = "台股P/E合理，定期定額", "#f59e0b"
                else:
                    sig_label, sig_c = "台股P/E偏高，等待修正", "#ef4444"
                pe_str = f"{tw_pe:.0f}x"
                hint = "&lt;16買 / 16-22觀 / &gt;22停（每季人工更新）"
            else:
                sig_label, sig_c = "台股P/E待設定", "#94a3b8"
                pe_str = "N/A"
                hint = "請在watchlist設定benchmark_pe（台股市場本益比）"
            metric_html = (
                f'<div class="etf-metric">'
                f'台股市場本益比 <strong style="color:{sig_c}">{pe_str}</strong>'
                f' <span class="etf-hint">（{hint}）</span>'
                f'</div>'
            )

        elif ticker == "00662.TW":
            # VIX 市場情緒（NASDAQ波動與情緒高度相關）
            vix_v = (indicators.get("VIX") or {}).get("value")
            if vix_v:
                if vix_v > 25:
                    sig_label, sig_c = "恐慌指數高，NASDAQ積極考慮進場", "#10b981"
                elif vix_v >= 15:
                    sig_label, sig_c = "情緒正常，定期定額", "#f59e0b"
                else:
                    sig_label, sig_c = "市場過度樂觀，等待回調", "#ef4444"
                vix_str = f"{vix_v:.1f}"
                hint = "&gt;25買 / 15-25觀 / &lt;15停"
            else:
                sig_label, sig_c = "VIX資料待取", "#94a3b8"
                vix_str = "N/A"
                hint = "Yahoo Finance暫時無法取得"
            metric_html = (
                f'<div class="etf-metric">'
                f'VIX恐慌指數 <strong style="color:{sig_c}">{vix_str}</strong>'
                f' <span class="etf-hint">（{hint}）</span>'
                f'</div>'
            )

        elif ticker in ("00878.TW", "00919.TW", "00830.TW"):
            # 即時殖利率 + 深度研究欄位
            annual_div = s.get("annual_div")
            if ticker == "00919.TW":
                buy_thr, obs_thr = 8.0, 6.0
                hint = "&ge;8%買 / 6-8%觀 / &lt;6%停"
                freq_note = "季配，年化配息估算"
            elif ticker == "00830.TW":
                buy_thr, obs_thr = 10.0, 7.0
                hint = "&ge;10%買 / 7-10%觀 / &lt;7%停"
                freq_note = "年配，上次配息9元"
            else:  # 00878
                buy_thr, obs_thr = 5.5, 4.0
                hint = "&ge;5.5%買 / 4-5.5%觀 / &lt;4%停"
                freq_note = "季配，年化配息估算"
            if annual_div and price:
                yld = annual_div / price * 100
                if yld >= buy_thr:
                    sig_label, sig_c = f"殖利率{yld:.1f}%，高息，留意配息品質", "#10b981"
                elif yld >= obs_thr:
                    sig_label, sig_c = f"殖利率{yld:.1f}%，合理，觀察", "#f59e0b"
                else:
                    sig_label, sig_c = f"殖利率{yld:.1f}%，偏低，等待回落", "#ef4444"
                yld_str = f"{yld:.1f}%"
                note = f"{freq_note} {annual_div}元/股（每季更新）"
            else:
                sig_label, sig_c = "殖利率待設定", "#94a3b8"
                yld_str = "N/A"
                hint = "請在watchlist設定annual_div"
                note = ""

            # ── 深度研究欄位（B 研究後自動填入）──
            nav_trend       = s.get("nav_trend")
            payout_quality  = s.get("payout_quality")
            fill_rate_1y    = s.get("fill_rate_1y")
            div_history     = s.get("div_history") or []
            etf_research    = s.get("etf_research_conclusion")
            etf_researched  = s.get("etf_last_researched")

            nav_colors = {"上升": "#10b981", "持平": "#f59e0b", "下降": "#ef4444"}
            nav_c = nav_colors.get(nav_trend, "#94a3b8")
            pq_colors = {"純股利": "#10b981", "混合": "#f59e0b", "本金返還為主": "#ef4444"}
            pq_c = pq_colors.get(payout_quality, "#94a3b8")

            # 配息趨勢箭頭
            if len(div_history) >= 2:
                diff = div_history[0] - div_history[-1]
                div_trend = ("↑ 成長" if diff > 0.05 else ("↓ 縮水" if diff < -0.05 else "→ 持平"))
                div_trend_c = "#10b981" if diff > 0.05 else ("#ef4444" if diff < -0.05 else "#f59e0b")
                div_hist_str = " / ".join(f"{d}" for d in div_history[:4])
            else:
                div_trend, div_trend_c, div_hist_str = "待研究", "#94a3b8", "—"

            research_block = ""
            if etf_research:
                research_block = (
                    f'<div class="card-conclusion" style="border-left-color:{sig_c}">'
                    f'{etf_research}'
                    + (f' <span class="card-researched">({etf_researched})</span>' if etf_researched else "")
                    + f'</div>'
                )

            deep_metric = ""
            if nav_trend or payout_quality or fill_rate_1y is not None:
                fill_c = "#10b981" if (fill_rate_1y or 0) >= 80 else ("#f59e0b" if (fill_rate_1y or 0) >= 60 else "#ef4444")
                deep_metric = (
                    f'<div class="etf-deep">'
                    + (f'<span class="etf-deep-tag" style="color:{nav_c};border-color:{nav_c}">NAV {nav_trend or "待研究"}</span>' if nav_trend else '')
                    + (f'<span class="etf-deep-tag" style="color:{pq_c};border-color:{pq_c}">{payout_quality or "配息來源待研究"}</span>' if payout_quality else '')
                    + (f'<span class="etf-deep-tag" style="color:{fill_c};border-color:{fill_c}">填息率 {fill_rate_1y}%</span>' if fill_rate_1y is not None else '')
                    + (f'<span class="etf-deep-tag" style="color:{div_trend_c};border-color:{div_trend_c}">配息 {div_trend}</span>' if div_history else '')
                    + f'</div>'
                    + (f'<div class="etf-note" style="margin-top:4px">近4季配息：{div_hist_str}</div>' if div_hist_str != "—" else '')
                )
            else:
                deep_metric = '<div class="etf-deep-pending">📋 深度研究待執行（每季自動更新）</div>'

            metric_html = (
                f'<div class="etf-metric">'
                f'即時殖利率 <strong style="color:{sig_c}">{yld_str}</strong>'
                f' <span class="etf-hint">（{hint}）</span>'
                + (f'<div class="etf-note">{note}</div>' if note else '')
                + f'</div>'
                + deep_metric
                + research_block
            )

        elif ticker == "00646.TW":
            # Fed Model：美股盈利率 vs 10年債殖利率
            benchmark_pe = s.get("benchmark_pe")
            tnx_v = (indicators.get("TNX") or {}).get("value")
            if benchmark_pe and tnx_v:
                ey = 1.0 / benchmark_pe * 100   # earnings yield %
                spread = ey - tnx_v
                if spread > 0.5:
                    sig_label, sig_c = "盈利率優於債券，股票有優勢", "#10b981"
                elif spread > -0.5:
                    sig_label, sig_c = "盈利率接近債券，定期定額", "#f59e0b"
                else:
                    sig_label, sig_c = "債券勝過盈利率，美股偏貴", "#ef4444"
                sp_str = f"盈利率{ey:.1f}% / 10Y債{tnx_v:.1f}%"
                hint = f"S&amp;P P/E {benchmark_pe}x（每季人工更新）"
            else:
                sig_label, sig_c = "Fed Model待設定", "#94a3b8"
                sp_str = "N/A"
                hint = "請在watchlist設定benchmark_pe（S&P500 P/E）"
            metric_html = (
                f'<div class="etf-metric">'
                f'Fed Model <strong style="color:{sig_c}">{sp_str}</strong>'
                f' <span class="etf-hint">（{hint}）</span>'
                f'</div>'
            )

        else:
            # 其他 ETF：52週區間位置
            w52_high = s.get("w52_high")
            w52_low  = s.get("w52_low")
            if price and w52_high and w52_low and w52_high > w52_low:
                pos = max(2, min(98, (price - w52_low) / (w52_high - w52_low) * 100))
            else:
                pos = 50
            if pos <= 30:
                sig_label, sig_c = "接近52週低點，留意進場時機", "#10b981"
            elif pos <= 70:
                sig_label, sig_c = "位於52週中段，可逐步布局", "#f59e0b"
            else:
                sig_label, sig_c = "接近52週高點，等待回調", "#ef4444"
            hint = f"低點{round(w52_low,0):.0f} ← 目前{pos:.0f}% → 高點{round(w52_high,0):.0f}" if (w52_high and w52_low) else "資料待取"
            metric_html = (
                f'<div class="etf-metric">'
                f'52週區間位置 <strong style="color:{sig_c}">{pos:.0f}%</strong>'
                f' <span class="etf-hint">（{hint}）</span>'
                f'</div>'
            )

        return (
            f'<div class="stock-card">'
            f'<div class="card-top">'
            f'<div>'
            f'<a class="card-name card-link" href="{yf_url}" target="_blank" rel="noopener">{s.get("name","")}</a>'
            f'<span class="card-ticker">{tw_ticker2}</span>'
            f'</div>'
            f'<span class="etf-category" style="background:{cat_c}22;color:{cat_c};border-color:{cat_c}">{category}</span>'
            f'</div>'
            f'<div class="card-price">{fp(price)}</div>'
            f'<div class="card-change" style="color:{pc(s.get("pct"))}">'
            f'{arr(s.get("pct"))} {fpct(s.get("pct"))}'
            f'</div>'
            f'{metric_html}'
            f'<div class="zone-label" style="background:{sig_c}22;color:{sig_c};border-color:{sig_c}">{sig_label}</div>'
            f'<div class="card-thesis">{s.get("thesis","")}</div>'
            f'</div>'
        )

    etf_stks   = [v for v in data.values() if v["type"] == "etf"]
    core_cards = "".join(make_card(s) for s in core_stks)
    obs_cards  = "".join(make_card(s) for s in obs_stks)
    etf_cards  = "".join(make_etf_card(s) for s in etf_stks)

    # ── 市場溫度計 ──
    temp_icon, temp_label, temp_color, temp_desc = calc_market_temp(indicators)
    vix  = indicators.get("VIX",{})
    tnx  = indicators.get("TNX",{})
    twd  = indicators.get("USDTWD",{})
    inst = indicators.get("INST",{})
    marg = indicators.get("MARGIN",{})

    vix_v = vix.get("value")
    vix_interp, vix_c = ("市場極度恐慌 — 歷史買點","#10b981") if vix_v and vix_v > 35 \
        else ("市場恐慌 — 留意買點","#10b981") if vix_v and vix_v > 25 \
        else ("正常波動","#f59e0b") if vix_v and vix_v > 15 \
        else ("市場平靜 — 不宜追高","#ef4444") if vix_v \
        else ("無資料","#94a3b8")

    tnx_v = tnx.get("value")
    tnx_interp, tnx_c = ("利率偏高，估值壓力大","#ef4444") if tnx_v and tnx_v > 4.5 \
        else ("利率中性","#f59e0b") if tnx_v and tnx_v > 3.5 \
        else ("利率友善","#10b981") if tnx_v \
        else ("無資料","#94a3b8")

    twd_v = twd.get("value")
    twd_interp, twd_c = ("台幣偏強，外資傾向流入","#10b981") if twd_v and twd_v < 30 \
        else ("台幣正常","#f59e0b") if twd_v and twd_v < 32 \
        else ("台幣偏弱，注意外資動向","#ef4444") if twd_v \
        else ("無資料","#94a3b8")

    foreign = inst.get("foreign")
    foreign_str   = fmt_b(foreign)
    foreign_c     = "#10b981" if (foreign or 0) > 0 else "#ef4444"
    foreign_label = "外資淨買超" if (foreign or 0) > 0 else "外資淨賣超"

    marg_today  = marg.get("today")
    marg_change = marg.get("change")
    marg_str    = f"{marg_today/100_000:.0f}億" if marg_today else "N/A"
    marg_chg_str = (("↑+" if marg_change > 0 else "↓") + f"{abs(marg_change)/100_000:.0f}億") if marg_change else ""
    marg_c = "#ef4444" if (marg_change or 0) > 0 else "#10b981"

    thermo_html = (
        f'<div class="thermo-section">'
        f'<div class="thermo-signal" style="border-color:{temp_color};background:{temp_color}11;color:{temp_color}">'
        f'{temp_icon} {temp_label} — {temp_desc}</div>'
        f'<div class="thermo-grid">'
        # VIX
        f'<div class="tc-card">'
        f'<div class="tc-label">VIX 恐慌指數</div>'
        f'<div class="tc-value">{f"{vix_v:.1f}" if vix_v else "N/A"}</div>'
        f'<div class="tc-interp" style="color:{vix_c}">{vix_interp}</div>'
        f'</div>'
        # 10Y
        f'<div class="tc-card">'
        f'<div class="tc-label">美10年債殖利率</div>'
        f'<div class="tc-value">{f"{tnx_v:.2f}%" if tnx_v else "N/A"}</div>'
        f'<div class="tc-interp" style="color:{tnx_c}">{tnx_interp}</div>'
        f'</div>'
        # TWD
        f'<div class="tc-card">'
        f'<div class="tc-label">美元／台幣</div>'
        f'<div class="tc-value">{f"{twd_v:.2f}" if twd_v else "N/A"}</div>'
        f'<div class="tc-interp" style="color:{twd_c}">{twd_interp}</div>'
        f'</div>'
        # 外資
        f'<div class="tc-card">'
        f'<div class="tc-label">外資今日買賣超</div>'
        f'<div class="tc-value" style="color:{foreign_c}">{foreign_str}</div>'
        f'<div class="tc-interp" style="color:{foreign_c}">{foreign_label}</div>'
        f'</div>'
        # 融資
        f'<div class="tc-card">'
        f'<div class="tc-label">融資餘額</div>'
        f'<div class="tc-value">{marg_str}</div>'
        f'<div class="tc-interp" style="color:{marg_c}">{marg_chg_str or "持平"}</div>'
        f'</div>'
        f'</div></div>'
    )

    # ── 風險提醒 ──
    warn_html = ""
    wmap = {"danger":("#ef4444","!","danger-row"),"warn":("#f59e0b","~","warn-row"),
            "ok":("#10b981","+","ok-row"),"info":("#94a3b8","i","info-row")}
    for wtype, wtitle, wbody in warnings:
        wc, wsym, wcls = wmap.get(wtype, wmap["info"])
        warn_html += (f'<div class="warn-item {wcls}">'
                      f'<span class="warn-sym" style="color:{wc}">[{wsym}]</span>'
                      f'<div class="warn-text">'
                      f'<strong style="color:{wc}">{wtitle}</strong>'
                      f'<span>{wbody}</span>'
                      f'</div></div>')

    # ── 持倉 JS ──
    prices_json = json.dumps(
        {k: {"price": v.get("price"), "name": v.get("name")}
         for k, v in data.items() if v["type"] in ("core","observe","etf")},
        ensure_ascii=False)
    stocks_json = json.dumps(
        [{"ticker": k, "name": v["name"], "cheap": v.get("cheap"), "fair": v.get("fair"), "rich": v.get("rich")}
         for k, v in data.items() if v["type"] in ("core","observe","etf")],
        ensure_ascii=False)


    # ── 今日結論 HTML ──
    concl_rows_html = ""
    for name, action, ac, detail, order_str, rsi_str, bias_str in conclusion_rows:
        concl_rows_html += (
            f'<div class="concl-row">'
            f'<div class="concl-left">'
            f'<span class="concl-name">{name}</span>'
            f'<span class="concl-action" style="color:{ac}">{action}</span>'
            f'</div>'
            f'<div class="concl-right">'
            f'<div class="concl-detail">{detail}</div>'
            f'<div class="concl-meta">'
            f'<span class="concl-order">{order_str}</span>'
            f'<span class="concl-tech">RSI {rsi_str} / 乖離 {bias_str}</span>'
            f'</div></div></div>'
        )
    conclusion_html = (
        f'<div class="concl-section">'
        f'<div class="section-title" style="margin-bottom:10px">今日結論 — 應該掛多少？</div>'
        + concl_rows_html
        + f'</div>'
    )

    adv_color = {"T1":"#10b981","T2":"#f59e0b","T3":"#ef4444"}.get(signal,"#f59e0b")
    pc_       = deep.get("pattern_color","#64748b")
    deep_html = (
        f'<div class="deep-section">'
        f'<div class="pattern-row">'
        f'<span class="pattern-badge" style="color:{pc_};border-color:{pc_};background:{pc_}22">{deep.get("pattern","")}</span>'
        f'<span class="pattern-desc">{deep.get("pattern_desc","")}</span>'
        f'</div>'
        f'<div class="advisor-merged" style="border-left:4px solid {adv_color}">{advisor}</div>'
        f'<div class="context-box">{deep.get("context","")}</div>'
        f'<div class="buffett-box"><span class="buffett-icon">&#x1F4BC;</span>{deep.get("buffett_advice","")}</div>'
        f'<div class="claude-insight" id="claude-insight"><!-- CLAUDE_INSIGHT --></div>'
        f'</div>\n'
    )

    # ── 資金流向區塊 ──
    core_tickers_for_flow = [
        (v["ticker"].replace(".TW","").replace(".TWO",""), v["name"])
        for v in data.values()
        if v.get("type") in ("core","observe")
    ]
    flow_section_html = make_flow_section(
        indicators.get("INST", {}),
        indicators.get("SECTORS", []),
        indicators.get("STOCK_MARGIN", {}),
        core_tickers_for_flow,
    )

    # ── 月度報告 ──
    if monthly:
        m_month, m_body = monthly
        monthly_html = (f'<div class="monthly-section">'
                        f'<div class="monthly-header" onclick="toggleMonthly()">'
                        f'<span class="section-title" style="margin:0">&#x1F4CB; 月度研究報告 &mdash; {m_month}</span>'
                        f'<span class="monthly-chevron" id="monthly-chevron">&#x25B2;</span></div>'
                        f'<div class="monthly-body" id="monthly-body">{m_body}</div></div>\n')
    else:
        monthly_html = ('<div class="monthly-section">'
                        '<div class="monthly-none">月度研究報告尚未生成——每月1日自動執行後將顯示於此。</div>'
                        '</div>\n')

    css = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:20px 16px;font-size:15px}
h1{font-size:1.5rem;font-weight:700;margin-bottom:2px}
.subtitle{color:#94a3b8;font-size:.85rem;margin-bottom:4px}.update-time{color:#3b82f6;font-size:.78rem;margin-bottom:20px}
.top-bar{display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:20px}
.idx-price{font-size:1.8rem;font-weight:700}
.idx-chg{font-size:1rem;margin-top:2px}
.signal-badge{display:inline-block;padding:6px 20px;border-radius:999px;font-size:1.4rem;font-weight:800}
.signal-sub{font-size:.9rem;color:#94a3b8;margin-top:4px;text-align:right}
.section-title{font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8;margin-bottom:10px}
.section-label{font-size:.85rem;font-weight:700;color:#cbd5e1;margin-bottom:10px;padding-left:4px}
.stocks-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-bottom:24px}
.stock-card{background:#1e293b;border-radius:12px;padding:16px;border:1px solid #334155}
.card-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
.card-name{font-size:1rem;font-weight:600;color:#cbd5e1}
.grade-badge{font-size:.75rem;font-weight:700;padding:2px 8px;border-radius:999px;border:1px solid}
.research-link{font-size:.72rem;color:#3b82f6;text-decoration:none;padding:2px 7px;border:1px solid #3b82f622;border-radius:999px;background:#3b82f611;white-space:nowrap}
.research-link:hover{background:#3b82f622;color:#60a5fa}
.card-price{font-size:1.6rem;font-weight:700;margin:4px 0}
.card-change{font-size:.95rem;font-weight:600;margin-bottom:10px}
.chg-abs{font-size:.8rem;font-weight:400;color:#94a3b8}
.zone-bar-wrap{margin-bottom:8px}
.zone-bar-wrap.no-val{font-size:.75rem;color:#94a3b8;padding:6px 0;margin-bottom:8px;font-style:italic}
.zone-bar{position:relative;height:8px;border-radius:4px;overflow:visible;display:flex;margin-bottom:4px}
.zs{height:100%}
.z1s{background:#10b981;border-radius:4px 0 0 4px}
.z2s{background:#34d399}
.z3s{background:#f59e0b}
.z4s{background:#ef4444;border-radius:0 4px 4px 0}
.zone-dot{position:absolute;top:-3px;width:14px;height:14px;border-radius:50%;background:#fff;border:2px solid #0f172a;transform:translateX(-50%);box-shadow:0 0 0 2px rgba(255,255,255,.25)}
.zone-prices{display:flex;justify-content:space-between;font-size:.7rem}
.zone-label{display:inline-block;font-size:.8rem;font-weight:700;padding:3px 10px;border-radius:999px;border:1px solid;margin-bottom:8px}
.card-thesis{font-size:.82rem;color:#94a3b8;line-height:1.55}
.warn-list{display:flex;flex-direction:column;gap:8px;margin-bottom:24px}
.warn-item{display:flex;align-items:flex-start;gap:10px;background:#1e293b;border-radius:8px;padding:12px 14px}
.warn-sym{font-size:1rem;font-weight:700;font-family:monospace;flex-shrink:0;margin-top:1px}
.warn-text{display:flex;flex-direction:column;gap:2px;font-size:.88rem;line-height:1.5}
.danger-row{border-left:3px solid #ef4444}
.warn-row{border-left:3px solid #f59e0b}
.ok-row{border-left:3px solid #10b981}
.info-row{border-left:3px solid #475569}
.holding-section{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:24px;border:1px solid #334155}
.holding-section h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8;margin-bottom:12px}
#holding-table{width:100%;border-collapse:collapse;font-size:.88rem;margin-bottom:12px}
#holding-table th{color:#94a3b8;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;padding:6px 8px;text-align:left;border-bottom:1px solid #334155}
#holding-table td{padding:7px 8px;border-bottom:1px solid #1a2535}
.pl-pos{color:#10b981;font-weight:600}.pl-neg{color:#ef4444;font-weight:600}
.add-form{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end}
.add-form select,.add-form input{background:#0f172a;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:6px 10px;font-size:.88rem}
.btn{padding:6px 14px;border-radius:6px;border:none;font-size:.88rem;font-weight:600;cursor:pointer}
.btn-add{background:#3b82f6;color:#fff}.btn-del{background:#334155;color:#94a3b8;font-size:.75rem;padding:3px 8px}
.btn-del:hover{background:#ef4444;color:#fff}
.timestamp-bar{display:flex;justify-content:flex-end;gap:16px;font-size:.75rem;color:#94a3b8;margin-top:8px}
.btn-update{padding:6px 14px;border-radius:6px;border:1px solid #3b82f6;background:#3b82f622;color:#3b82f6;font-size:.85rem;font-weight:600;cursor:pointer;white-space:nowrap}
.btn-update:hover{background:#3b82f644}
.btn-update:disabled{opacity:.6;cursor:not-allowed}
.update-status{font-size:.78rem;color:#94a3b8;margin:-14px 0 12px 0;text-align:right}
.deep-section{background:#1e293b;border-radius:12px;padding:18px;margin-bottom:24px;border:1px solid #334155}
.pattern-row{display:flex;align-items:flex-start;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.pattern-badge{font-size:.85rem;font-weight:700;padding:4px 14px;border-radius:999px;border:1px solid;white-space:nowrap;flex-shrink:0}
.pattern-desc{font-size:.9rem;color:#cbd5e1;line-height:1.6}
.advisor-merged{font-size:1rem;line-height:1.7;padding:12px 16px;border-radius:8px;background:#1a2535;margin-bottom:12px}
.context-box{font-size:.88rem;color:#94a3b8;line-height:1.7;padding:10px 12px;background:#0f172a;border-radius:8px;margin-bottom:10px}
.buffett-box{font-size:.92rem;color:#86efac;line-height:1.7;padding:10px 14px;background:#052e16;border-radius:8px;border-left:3px solid #22c55e;margin-bottom:10px}
.buffett-icon{margin-right:6px}
.claude-insight{font-size:.9rem;color:#e2e8f0;line-height:1.7;padding:12px 14px;background:#1a2a1a;border-radius:8px;border-left:3px solid #10b981;display:none}
.claude-insight.visible{display:block}
.hadv-item{background:#0f172a;border-radius:8px;padding:10px 14px;margin-bottom:8px;font-size:.88rem;line-height:1.6;border-left:3px solid #334155}
.hadv-name{font-weight:700;margin-bottom:3px}.hadv-text{color:#94a3b8}
.holding-advice{margin-bottom:14px}
.monthly-section{background:#1e293b;border-radius:12px;margin-bottom:24px;border:1px solid #334155;overflow:hidden}
.monthly-header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;cursor:pointer;user-select:none}
.monthly-header:hover{background:#263548}
.monthly-chevron{font-size:.8rem;color:#94a3b8;transition:transform .2s}
.monthly-body{padding:0 18px 16px;display:block}
.monthly-body.closed{display:none}
.mr-h1{font-size:1rem;font-weight:700;color:#e2e8f0;margin:12px 0 4px}
.mr-h2{font-size:.9rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em;margin:14px 0 6px;padding-top:10px;border-top:1px solid #334155}
.mr-h3{font-size:.88rem;font-weight:600;color:#cbd5e1;margin:8px 0 4px}
.mr-li{font-size:.88rem;color:#94a3b8;line-height:1.6;padding-left:6px;margin-bottom:2px}
.mr-p{font-size:.88rem;color:#94a3b8;line-height:1.7;margin-bottom:2px}
.mr-gap{height:6px}
.monthly-none{padding:16px 18px;font-size:.88rem;color:#94a3b8}
.card-link{color:#cbd5e1;text-decoration:none;font-size:1rem;font-weight:600}.card-link:hover{color:#60a5fa;text-decoration:underline}
.card-ticker{display:block;font-size:.72rem;color:#94a3b8;margin-top:1px;font-family:monospace;letter-spacing:.04em}
.tech-row{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0}
.tech-tag{font-size:.72rem;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid}
.tech-ma{font-size:.7rem;color:#94a3b8;padding:2px 6px;align-self:center}
.batch-wrap{background:#0a1322;border-radius:8px;padding:8px 10px;margin:6px 0}
.batch-title{font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;margin-bottom:5px}
.batch-row{display:flex;align-items:center;gap:6px;padding:2px 0;font-size:.78rem}
.batch-n{color:#94a3b8;width:2.5rem;flex-shrink:0}
.batch-p{color:#e2e8f0;font-weight:600;flex:1}
.batch-d{font-size:.72rem}
.etf-category{font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:999px;border:1px solid;white-space:nowrap}
.etf-metric{font-size:.82rem;color:#cbd5e1;margin-bottom:8px;padding:7px 10px;background:#0f172a;border-radius:6px;line-height:1.55}
.etf-hint{font-size:.68rem;color:#94a3b8}
.etf-note{font-size:.7rem;color:#94a3b8;margin-top:2px}
.etf-deep{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0 4px}
.etf-deep-tag{font-size:.72rem;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid}
.etf-deep-pending{font-size:.75rem;color:#475569;font-style:italic;margin:6px 0 4px;padding:4px 8px;background:#0f172a;border-radius:6px}
.card-conclusion{font-size:.74rem;color:#94a3b8;background:#0f172a;border-radius:6px;padding:6px 10px;margin-top:6px;border-left:3px solid #3b82f6;line-height:1.5}
.card-researched{font-size:.68rem;color:#94a3b8}
.fv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-bottom:24px}
.fv-card{background:#1e293b;border-radius:12px;padding:16px;border:1px solid #334155}
.fv-cap{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8;margin-bottom:10px}
.fv-date{font-size:.7rem;color:#94a3b8;margin-bottom:6px}
.fbar{margin-bottom:8px}
.fbar-lbl{display:flex;justify-content:space-between;font-size:.82rem;margin-bottom:3px}
.fbar-track{height:8px;background:#0a1322;border-radius:4px;position:relative;overflow:hidden}
.fbar-mid{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#334155}
.fbar-fill{position:absolute;top:0;bottom:0;border-radius:4px}
.fv-gain{color:#ff5a5a}
.fv-loss{color:#22c08a}
.fv-verdict{font-size:.82rem;padding:8px 10px;border-radius:6px;border:1px solid #334155;margin-top:10px}
.fv-verdict-in{background:rgba(255,90,90,.08);border-color:rgba(255,90,90,.35)}
.fv-verdict-out{background:rgba(34,192,138,.08);border-color:rgba(34,192,138,.35)}
.fv-heat-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.fv-heat-cell{border-radius:7px;padding:8px 7px;display:flex;flex-direction:column;gap:4px;border:1px solid rgba(255,255,255,.05)}
.fv-heat-name{font-size:.72rem;color:#94a3b8}
.fv-table{width:100%;border-collapse:collapse;font-size:.8rem}
.fv-table th{color:#94a3b8;font-size:.68rem;text-transform:uppercase;padding:4px 6px;border-bottom:1px solid #334155;font-weight:500}
.fv-table td{padding:5px 6px;border-bottom:1px solid #1a2535}
.fv-table tr:last-child td{border-bottom:none}
.concl-section{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:24px;border:1px solid #334155}
.concl-row{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #1a2535;align-items:flex-start}
.concl-row:last-child{border-bottom:none}
.concl-left{width:160px;flex-shrink:0}
.concl-name{display:block;font-size:.88rem;font-weight:700;color:#cbd5e1;margin-bottom:4px}
.concl-action{font-size:.82rem;font-weight:600}
.concl-right{flex:1}
.concl-detail{font-size:.82rem;color:#94a3b8;margin-bottom:4px}
.concl-meta{display:flex;gap:12px;flex-wrap:wrap}
.concl-order{font-size:.82rem;color:#e2e8f0;font-weight:600}
.concl-tech{font-size:.72rem;color:#94a3b8}
.thermo-section{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:24px;border:1px solid #334155}
.thermo-signal{font-size:.92rem;font-weight:600;padding:10px 14px;border-radius:8px;border:1px solid;margin-bottom:14px;line-height:1.5}
.thermo-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
.tc-card{background:#0f172a;border-radius:8px;padding:12px;border:1px solid #1e293b}
.tc-label{font-size:.72rem;color:#94a3b8;margin-bottom:4px;text-transform:uppercase;letter-spacing:.06em}
.tc-value{font-size:1.2rem;font-weight:700;margin-bottom:2px}
.tc-interp{font-size:.75rem;line-height:1.4}
"""

    js_tpl = r"""
const PRICES = __PRICES__;
const STOCKS = __STOCKS__;
(function(){
  var sel = document.getElementById('f-ticker');
  STOCKS.forEach(function(s){
    var opt = document.createElement('option');
    opt.value = s.ticker; opt.textContent = s.name; sel.appendChild(opt);
  });
})();
function loadH(){ var d=localStorage.getItem('ai_adv_v3'); return JSON.parse(d||'[]'); }
function saveH(h){ localStorage.setItem('ai_adv_v3', JSON.stringify(h)); }
// 持倉狀態 Banner
(function renderHoldingBanner(){
  var el = document.getElementById('holding-status-banner');
  if(!el) return;
  var h = loadH();
  if(!h.length){
    el.innerHTML = '<div style="background:#1a2535;border:1px solid #334155;border-left:4px solid #3b82f6;border-radius:8px;padding:10px 14px;font-size:.88rem;color:#94a3b8;margin-bottom:16px">📋 <strong style="color:#60a5fa">目前持倉為零</strong>　以下分析為進場時機觀察，非持倉建議。若有買進，請在「我的持倉」欄位登錄。</div>';
  } else {
    var names = h.map(function(p){ var info=PRICES[p.ticker]; return info?info.name:p.ticker; });
    el.innerHTML = '<div style="background:#052e16;border:1px solid #166534;border-left:4px solid #22c55e;border-radius:8px;padding:10px 14px;font-size:.88rem;color:#86efac;margin-bottom:16px">💼 <strong>持倉中：</strong>' + names.join('、') + '　損益詳見下方持倉表格。</div>';
  }
})();
function fmtN(n){ return n==null?'-':n.toLocaleString('zh-TW',{maximumFractionDigits:0}); }
function fmtP(n){ return n==null?'-':(n>=0?'+':'')+n.toFixed(2)+'%'; }
function getZone(price,cheap,fair,rich){
  if(!price||!cheap) return 'none';
  if(price<=cheap) return 'z1'; if(price<=fair) return 'z2';
  if(price<=rich)  return 'z3'; return 'z4';
}
var ZONE_COLOR   = {z1:'#10b981',z2:'#34d399',z3:'#f59e0b',z4:'#ef4444',none:'#94a3b8'};
var ZONE_BUFFETT = {
  z1:'積極買進區 — 符合長期低點布局原則，可分批加碼，越跌越買。',
  z2:'合理布局區 — 估值合理，繼續持有，可小量加碼。',
  z3:'謹慎觀察區 — 接近合理上限，持有但暫緩加碼，等待更好時機。',
  z4:'偏貴等待區 — 超過合理估值，新資金暫停加碼，繼續長期持有。',
  none:'估值待研究設定。'
};
function renderHoldingAdvice(){
  var el=document.getElementById('holding-advice'); if(!el) return;
  var h=loadH(); if(!h.length){ el.innerHTML=''; return; }
  var html='<div style="font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8;margin-bottom:8px">持股個別建議</div>';
  h.forEach(function(p){
    var info=PRICES[p.ticker]; var stock=STOCKS.find(function(s){return s.ticker===p.ticker;});
    if(!info||!stock) return;
    var cur=info.price; var zone=getZone(cur,stock.cheap,stock.fair,stock.rich);
    var zc=ZONE_COLOR[zone]||'#94a3b8';
    var pl=cur?(cur-p.cost)/p.cost*100:null;
    var plStr=pl!=null?(pl>=0?'+':'')+pl.toFixed(1)+'%':'-';
    var plCls=pl==null?'':pl>=0?'pl-pos':'pl-neg';
    html+='<div class="hadv-item" style="border-left-color:'+zc+'">'
      +'<div class="hadv-name">'+info.name+' <span class="'+plCls+'">'+plStr+'</span></div>'
      +'<div class="hadv-text" style="color:'+zc+'">'+ZONE_BUFFETT[zone]+'</div></div>';
  });
  el.innerHTML=html;
}
function renderH(){
  var tbody=document.getElementById('holding-body'); var h=loadH();
  if(!h.length){
    tbody.innerHTML='<tr><td colspan="8" style="color:#94a3b8;text-align:center;padding:16px">尚未新增持倉</td></tr>';
    renderHoldingAdvice(); return;
  }
  tbody.innerHTML=h.map(function(p,i){
    var info=PRICES[p.ticker]; var cur=info?info.price:null; var name=info?info.name:p.ticker;
    var val=cur?cur*p.shares:null; var cost_t=p.cost*p.shares;
    var pl=val!=null?val-cost_t:null; var plP=pl!=null?pl/cost_t*100:null;
    var cls=pl==null?'':(pl>=0?'pl-pos':'pl-neg');
    return '<tr><td><strong>'+name+'</strong></td><td>'+p.shares.toLocaleString()+'</td>'
      +'<td>'+p.cost.toLocaleString()+'</td><td>'+(cur?cur.toLocaleString():'-')+'</td>'
      +'<td>'+fmtN(val)+'</td><td class="'+cls+'">'+fmtN(pl)+'</td>'
      +'<td class="'+cls+'">'+fmtP(plP)+'</td>'
      +'<td><button class="btn btn-del" onclick="removeH('+i+')">移除</button></td></tr>';
  }).join('');
  renderHoldingAdvice();
}
function addHolding(){
  var ticker=document.getElementById('f-ticker').value;
  var shares=parseFloat(document.getElementById('f-shares').value);
  var cost=parseFloat(document.getElementById('f-cost').value);
  if(!ticker||!shares||!cost||shares<=0||cost<=0){alert('請填寫完整資料');return;}
  var h=loadH(); h.push({ticker:ticker,shares:shares,cost:cost}); saveH(h);
  document.getElementById('f-shares').value=''; document.getElementById('f-cost').value='';
  renderH();
}
function removeH(i){ var h=loadH(); h.splice(i,1); saveH(h); renderH(); }
renderH();
function toggleMonthly(){
  var b=document.getElementById("monthly-body"); var c=document.getElementById("monthly-chevron");
  if(b.classList.contains("closed")){b.classList.remove("closed");c.innerHTML="&#x25B2;";}
  else{b.classList.add("closed");c.innerHTML="&#x25BC;";}
}
"""
    trigger_token = os.environ.get('UPDATE_TRIGGER_TOKEN', '')
    js = (js_tpl.replace('__PRICES__', prices_json)
                .replace('__STOCKS__', stocks_json)
                .replace('__TRIGGER_TOKEN__', trigger_token))

    n_core = len(core_stks)
    n_obs  = len(obs_stks)
    html = (
        '<!DOCTYPE html>\n<html lang="zh-TW">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">\n'
        '<title>AI 每日投資顧問</title>\n'
        '<style>' + css + '</style>\n</head>\n<body>\n'
        '<h1>AI 每日投資顧問</h1>\n'
        f'<p class="subtitle">{n_core} 檔核心持股 &middot; {n_obs} 檔潛力池 &middot; 巴菲特價值投資</p>\n'
        + '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">\n'
        + f'  <p class="update-time" style="margin:0">&#x1F551; 資料更新：{data_time}</p>\n'
        + '  <span style="font-size:.78rem;color:#94a3b8">&#x1F503; 盤中每5分鐘自動更新，收盤後17:01附深度分析</span>\n'
        + '</div>\n'
        + '<div class="top-bar">\n'
        '  <div>\n'
        '    <div class="section-title">加權指數</div>\n'
        f'    <div class="idx-price" style="color:{pc(twii.get("pct"))}">{fp(twii.get("price"))}</div>\n'
        f'    <div class="idx-chg" style="color:{pc(twii.get("pct"))}">{arr(twii.get("pct"))} {fpct(twii.get("pct"))}</div>\n'
        '  </div>\n'
        '  <div>\n'
        f'    <div class="signal-badge" style="border:2px solid {signal_color};background:{signal_color}22;color:{signal_color}">{signal}</div>\n'
        f'    <div class="signal-sub">{signal_label} 走勢</div>\n'
        '  </div>\n</div>\n'
        '<div class="section-title">市場溫度計</div>\n'
        + thermo_html
        + flow_section_html
        + conclusion_html
        + '<div class="section-title">今日市場觀察</div>\n'
        + '<div id="holding-status-banner"></div>\n'
        + deep_html
        + '<div class="section-title">核心持股 &mdash; 估值燈號</div>\n'
        + '<div class="section-label">🏆 核心價值股（有估值區間）</div>\n'
        + '<div class="stocks-grid">' + core_cards + '</div>\n'
        + '<div class="section-label">🔍 潛力池（持續追蹤）</div>\n'
        + '<div class="stocks-grid">' + obs_cards + '</div>\n'
        + '<div class="section-title">精選 ETF 觀察</div>\n'
        + '<div class="stocks-grid">' + etf_cards + '</div>\n'
        + '<div class="section-title">風險提醒</div>\n'
        + '<div class="warn-list">' + warn_html + '</div>\n'
        + '<div class="holding-section">\n'
        + '  <h2>我的持倉</h2>\n'
        + '  <div id="holding-advice" class="holding-advice"></div>\n'
        + '  <table id="holding-table">\n'
        + '    <thead><tr><th>標的</th><th>股數</th><th>成本</th><th>現價</th>'
        + '<th>市値</th><th>損益</th><th>損益%</th><th></th></tr></thead>\n'
        + '    <tbody id="holding-body"></tbody>\n  </table>\n'
        + '  <div class="add-form">\n'
        + '    <select id="f-ticker"><option value="">選擇標的</option></select>\n'
        + '    <input id="f-shares" type="number" placeholder="股數" style="width:90px">\n'
        + '    <input id="f-cost" type="number" placeholder="平均成本" style="width:110px" step="0.01">\n'
        + '    <button class="btn btn-add" onclick="addHolding()">加入持倉</button>\n'
        + '  </div>\n</div>\n'
        + '<div class="section-title">月度研究</div>\n'
        + monthly_html
        + '<div class="timestamp-bar">'        + '<span>資料時間：' + data_time + '</span>'        + '<span>頁面產生：' + generated_at + '</span>'        + '</div>\n'        + '<script>' + js + '</script>\n'        + '</body>\n</html>'    )
    return html


# ── 主程式 ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--cache",      action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  AI v5  |  {now_tw().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    tickers = load_watchlist()
    if not tickers:
        print("ERROR: watchlist.json empty")
        return

    data_time = "unknown"
    if args.cache and os.path.exists(CACHE_FILE):
        print("Using cached data...")
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        data = cached.get("data", {})
        raw_time = cached.get("updated", "")
        if raw_time:
            try:    data_time = datetime.datetime.fromisoformat(raw_time).strftime("%Y-%m-%d %H:%M")
            except: data_time = raw_time[:16]
    else:
        print("Fetching prices...")
        data = fetch_all(tickers)
        data_time = now_tw().strftime("%Y-%m-%d %H:%M")
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"data": data, "updated": now_tw().isoformat()}, f, ensure_ascii=False, indent=2)

    research_map = find_research_files()
    indicators   = fetch_market_indicators()

    # 大盤訊號
    twii = data.get("^TWII", {})
    twii_pct = twii.get("pct") or 0
    if twii_pct >= 1.5:
        signal, signal_label, signal_color = "T1", "大盤偏多", "#10b981"
    elif twii_pct <= -1.5:
        signal, signal_label, signal_color = "T3", "大盤退潮", "#ef4444"
    else:
        signal, signal_label, signal_color = "T2", "市場震盪", "#f59e0b"

    advisor  = build_advisor(signal, data)
    warnings = build_warnings(signal, data)
    deep     = build_deep_analysis(signal, data)

    generated_at = now_tw().strftime("%Y-%m-%d %H:%M")
    monthly = read_monthly_report()
    html = generate_html(data, signal, signal_label, signal_color,
                         advisor, warnings, deep,
                         data_time, generated_at, research_map, indicators,
                         monthly=monthly)
    html = inject_cached_analysis(html)
    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    core_n = sum(1 for v in data.values() if v["type"] == "core")
    obs_n  = sum(1 for v in data.values() if v["type"] == "observe")
    etf_n  = sum(1 for v in data.values() if v["type"] == "etf")
    res_n  = len(research_map)
    print(f"\n  Dashboard: {DASHBOARD_FILE}")
    print(f"  Data time: {data_time}")
    print(f"  Core: {core_n}  Observe: {obs_n}  ETF: {etf_n}")
    print(f"  Research reports: {res_n}")

if __name__ == "__main__":
    main()
