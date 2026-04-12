"""
行情数据模块 - 美股
"""
import sys
import os

def get_quote(symbol: str):
    """获取实时报价"""
    try:
        import requests
        import json as _json
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})
        last_price = meta.get("regularMarketPrice")
        prev_close = meta.get("previousClose")
        if last_price is None:
            return None
        return {
            "symbol": symbol,
            "last_price": float(last_price),
            "prev_close": float(prev_close) if prev_close else float(last_price),
            "currency": meta.get("currency", "USD"),
            "market": "US"
        }
    except Exception as e:
        print(f"[行情] {symbol} 获取失败: {e}")
    return None

def get_finnhub_quote(symbol: str, api_key: str = ""):
    """从 Finnhub 获取报价（备用）"""
    if not api_key:
        return get_quote(symbol)
    try:
        import requests
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return get_quote(symbol)
        data = resp.json()
        c = data.get("c", 0)
        if c == 0:
            return get_quote(symbol)
        return {
            "symbol": symbol,
            "last_price": float(c),
            "prev_close": float(data.get("pc", c)),
            "currency": "USD",
            "market": "US"
        }
    except:
        return get_quote(symbol)
