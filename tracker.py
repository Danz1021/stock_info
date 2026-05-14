"""
Stock & Crypto Price Tracker
每次執行抓取台積電(2330)、台灣50(0050)、比特幣(BTC) 並推送 Telegram
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── 設定 ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

STOCKS = {
    "台積電 2330": "2330",
    "台灣50 0050": "0050",
    "凱基台灣TOP50 009816": "009816",
    "統一升級50 00403A": "00403A",
}
CRYPTO_IDS = {"比特幣 BTC": "bitcoin"}

GLOBAL_MARKETS = {
    "台股加權指數": "^TWII",
    "布蘭特原油": "BZ=F",
    "美債10年殖利率": "^TNX",
}

NIGHT_MARKETS = {
    "道瓊指數期貨": "YM=F",
    "納斯達克期貨": "NQ=F",
    "S&P500期貨": "ES=F",
    "道瓊指數": "^DJI",
    "納斯達克指數": "^IXIC",
    "S&P500指數": "^GSPC",
}

TW_TZ = timezone(timedelta(hours=8))


# ── Telegram ──────────────────────────────────────────
def send_telegram(message: str) -> bool:
    """發送 Telegram 訊息，回傳是否成功。"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[警告] Telegram 未設定，跳過推播。")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            print(f"[錯誤] Telegram 回應: {resp.status_code} {resp.text}")
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[錯誤] Telegram 推播失敗: {e}")
        return False


# ── 台股（yfinance） ──────────────────────────────────
def fetch_tw_stocks() -> list[dict]:
    """使用台灣證交所即時 API 抓取台股報價（盤中即時，盤後顯示收盤價）。"""
    ex_ch = "|".join(f"tse_{code}.tw" for code in STOCKS.values())
    ts = int(datetime.now(TW_TZ).timestamp() * 1000)
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch}&_={ts}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://mis.twse.com.tw/",
    }
    results = []
    try:
        data = requests.get(url, headers=headers, timeout=10).json()
        items = data.get("msgArray", [])
        for name, code in STOCKS.items():
            item = next((x for x in items if x.get("c") == code), None)
            if not item:
                results.append({"name": name, "price": None})
                continue
            # z=最新成交價；若為"-"則用最佳委買價(b)第一檔；最後用昨收(y)
            def first_val(s):
                v = (s or "").split("_")[0].strip()
                return v if v and v != "-" else None

            z = first_val(item.get("z", "-"))
            b = first_val(item.get("b", "-"))
            y = first_val(item.get("y", "-"))
            price_str = z or b or y
            prev_str  = y
            if not price_str or not prev_str:
                results.append({"name": name, "price": None})
                continue
            price = float(price_str.replace(",", ""))
            prev  = float(prev_str.replace(",", ""))
            change     = price - prev
            change_pct = (change / prev) * 100 if prev else 0
            results.append({
                "name": name,
                "price": price,
                "change": change,
                "change_pct": change_pct,
            })
    except Exception as e:
        print(f"[錯誤] 抓取台股失敗: {e}")
        for name in STOCKS:
            results.append({"name": name, "price": None})
    return results


# ── 全球市場（Yahoo Finance v8）──────────────────────
def fetch_global_markets() -> list[dict]:
    """使用 Yahoo Finance API 抓取原油、美債殖利率等全球市場資料。"""
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    results = []
    for name, symbol in GLOBAL_MARKETS.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
            meta = requests.get(url, headers=headers, timeout=10).json()["chart"]["result"][0]["meta"]
            price = float(meta.get("regularMarketPrice", 0))
            prev  = float(meta.get("chartPreviousClose", price))
            change     = price - prev
            change_pct = (change / prev) * 100 if prev else 0
            results.append({"name": name, "symbol": symbol, "price": price, "change": change, "change_pct": change_pct})
        except Exception as e:
            print(f"[錯誤] 抓取 {name} 失敗: {e}")
            results.append({"name": name, "price": None})
    return results


# ── 台股夜盤期貨（TAIFEX）────────────────────────────
def fetch_taiex_night() -> dict:
    """從 TAIFEX 抓取台指夜盤期貨最近月合約（成交量最大）。"""
    try:
        url = "https://mis.taifex.com.tw/futures/api/getQuoteList"
        payload = {"MarketType": "1", "CommodityID": "TXF", "CommodityGroupID": ""}
        items = requests.post(url, json=payload, timeout=10).json()["RtData"]["QuoteList"]
        # 過濾有成交量的合約，取成交量最大的近月
        actives = [x for x in items if x.get("CTotalVolume", "").isdigit() and int(x["CTotalVolume"]) > 0]
        if not actives:
            return {"name": "台股夜盤期貨", "price": None}
        front = max(actives, key=lambda x: int(x["CTotalVolume"]))
        price  = float(front["CLastPrice"])
        prev   = float(front["CRefPrice"])
        change = price - prev
        change_pct = (change / prev * 100) if prev else 0
        return {"name": "台股夜盤期貨", "price": price, "change": change, "change_pct": change_pct}
    except Exception as e:
        print(f"[錯誤] 抓取台股夜盤失敗: {e}")
        return {"name": "台股夜盤期貨", "price": None}


# ── 美股晚盤（Yahoo Finance v8）──────────────────────
def fetch_night_markets() -> list[dict]:
    """使用 Yahoo Finance 抓取美股指數與期貨。"""
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    results = []
    for name, symbol in NIGHT_MARKETS.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
            meta = requests.get(url, headers=headers, timeout=10).json()["chart"]["result"][0]["meta"]
            price = float(meta.get("regularMarketPrice", 0))
            prev  = float(meta.get("chartPreviousClose", price))
            change     = price - prev
            change_pct = (change / prev) * 100 if prev else 0
            results.append({"name": name, "price": price, "change": change, "change_pct": change_pct})
        except Exception as e:
            print(f"[錯誤] 抓取 {name} 失敗: {e}")
            results.append({"name": name, "price": None})
    return results


# ── 虛擬貨幣（CoinGecko API） ─────────────────────────
def fetch_crypto() -> list[dict]:
    """使用 CoinGecko 免費 API 抓取幣種報價（無需 API Key，雲端友善）。"""
    ids = ",".join(CRYPTO_IDS.values())
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd"
        f"&include_24hr_change=true&include_24hr_vol=true"
        f"&include_high=true&include_low=true"
    )
    results = []
    try:
        data = requests.get(url, timeout=15).json()
        for name, coin_id in CRYPTO_IDS.items():
            d = data.get(coin_id, {})
            if not d:
                results.append({"name": name, "price": None})
                continue
            price      = float(d.get("usd", 0))
            change_pct = float(d.get("usd_24h_change", 0))
            change     = price / (1 + change_pct / 100) * (change_pct / 100)
            results.append({
                "name": name,
                "price": price,
                "change": change,
                "change_pct": change_pct,
            })
    except Exception as e:
        print(f"[錯誤] 抓取加密貨幣失敗: {e}")
        for name in CRYPTO_IDS:
            results.append({"name": name, "price": None})
    return results


# ── 格式化訊息 ────────────────────────────────────────
def format_market_row(m: dict, unit: str = "USD", decimals: int = 2) -> str:
    """格式化單筆市場資料列。"""
    if m.get("price") is None:
        return f"  {m['name']}：抓取失敗"
    arrow = "🔺" if m["change"] >= 0 else "🟢"
    price_fmt = f"{m['price']:,.{decimals}f}"
    return (f"  {arrow} *{m['name']}*\n"
            f"       {price_fmt} {unit}  ({m['change_pct']:+.2f}%)")


def format_message(stocks: list[dict], global_markets: list[dict],
                   taiex_night: dict, night_markets: list[dict], crypto: list[dict]) -> str:
    """組合 Telegram Markdown 訊息。"""
    now = datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M")
    lines = [f"📊 *市場行情速報*", f"🕐 {now} (台北時間)", ""]

    # 台股（加權指數排第一）
    lines.append("*📈 台灣股市*")
    taiex = next((m for m in global_markets if "加權" in m["name"]), None)
    if taiex:
        if taiex.get("price") is None:
            lines.append(f"  {taiex['name']}：抓取失敗")
        else:
            arrow = "🔺" if taiex["change"] >= 0 else "🟢"
            lines.append(
                f"  {arrow} *{taiex['name']}*\n"
                f"       {taiex['price']:,.2f} 點  ({taiex['change_pct']:+.2f}%)"
            )
    for s in stocks:
        if s.get("price") is None:
            lines.append(f"  {s['name']}：抓取失敗")
            continue
        arrow = "🔺" if s["change"] >= 0 else "🟢"
        lines.append(
            f"  {arrow} *{s['name']}*\n"
            f"       ${s['price']:,.2f}  ({s['change']:+.2f} / {s['change_pct']:+.2f}%)"
        )

    lines.append("")

    # 全球市場（排除加權指數，已顯示於台股區）
    lines.append("*🌍 全球市場*")
    for m in global_markets:
        if "加權" in m["name"]:
            continue
        if m.get("price") is None:
            lines.append(f"  {m['name']}：抓取失敗")
            continue
        arrow = "🔺" if m["change"] >= 0 else "🟢"
        if "殖利率" in m["name"]:
            unit, fmt = "%", ".3f"
        elif "加權" in m["name"]:
            unit, fmt = "點", ",.2f"
        else:
            unit, fmt = "USD", ",.3f"
        lines.append(
            f"  {arrow} *{m['name']}*\n"
            f"       {m['price']:{fmt}} {unit}  ({m['change_pct']:+.2f}%)"
        )

    lines.append("")

    # 加密貨幣
    lines.append("*₿ 加密貨幣*")
    for c in crypto:
        if c.get("price") is None:
            lines.append(f"  {c['name']}：抓取失敗")
            continue
        arrow = "🔺" if c["change"] >= 0 else "🟢"
        lines.append(
            f"  {arrow} *{c['name']}*\n"
            f"       ${c['price']:,.2f} USDT  ({c['change_pct']:+.2f}%)"
        )

    lines.append("")

    # 晚盤區塊
    lines.append("*🌙 晚盤指數*")
    lines.append(format_market_row(taiex_night, unit="點", decimals=0))
    for m in night_markets:
        if "期貨" in m["name"]:
            lines.append(format_market_row(m, unit="點", decimals=0))
    lines.append("")
    for m in night_markets:
        if "期貨" not in m["name"]:
            lines.append(format_market_row(m, unit="點", decimals=2))

    lines.append("")
    lines.append("_資料來源: TWSE / TAIFEX / Yahoo Finance / CoinGecko_")
    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────
def main():
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 開始抓取行情...")

    stocks         = fetch_tw_stocks()
    global_markets = fetch_global_markets()
    taiex_night    = fetch_taiex_night()
    night_markets  = fetch_night_markets()
    crypto         = fetch_crypto()

    message = format_message(stocks, global_markets, taiex_night, night_markets, crypto)
    print("\n" + message + "\n")

    ok = send_telegram(message)
    if ok:
        print("✅ Telegram 推播成功")
    else:
        print("⚠️  Telegram 未推播（請確認 .env 設定）")

    # 同時將結果存入 log
    log_path = os.path.join(os.path.dirname(__file__), "price_log.json")
    entry = {
        "time": datetime.now(TW_TZ).isoformat(),
        "stocks": stocks,
        "crypto": crypto,
    }
    try:
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                log = json.load(f)
        else:
            log = []
        log.append(entry)
        log = log[-500:]  # 只保留最近 500 筆
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        print(f"📝 已記錄至 {log_path}")
    except Exception as e:
        print(f"[警告] 寫入 log 失敗: {e}")


if __name__ == "__main__":
    main()
