# -*- coding: utf-8 -*-
"""
行情数据适配层 - A股模拟交易系统

统一封装各行情源，供 SimAccount 直接调用。
内部调用同目录下的 market_data_cn.py。
"""

from __future__ import annotations

from typing import Optional

# 优先使用同目录的行情模块
try:
    from .market_data_cn import get_quote as _get_quote_em
except ImportError:
    _get_quote_em = None


def _get_quote_eastmoney(symbol: str) -> Optional[dict]:
    """备用：东方财富行情"""
    try:
        import requests
        if symbol.startswith("6") or symbol.startswith("9"):
            secid = f"0.{symbol}"
        else:
            secid = f"1.{symbol}"
        url = "http://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": secid,
            "fields": "f43,f170,f171,f50,f57,f58,f107,f45",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b"
        }
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.eastmoney.com/"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        stock_data = data.get("data", {})
        if not stock_data:
            return None
        last_price = stock_data.get("f43")
        prev_close = stock_data.get("f50")
        return {
            "symbol": symbol,
            "name": stock_data.get("f58", symbol),
            "last_price": float(last_price) / 100 if last_price else 0.0,
            "prev_close": float(prev_close) / 100 if prev_close else 0.0,
            "currency": "CNY",
            "market": "CN",
            "source": "eastmoney",
        }
    except Exception:
        return None


def _get_quote_sina(symbol: str) -> Optional[dict]:
    """备用：新浪行情"""
    try:
        import requests
        if symbol.startswith("6") or symbol.startswith("9"):
            sina_code = f"sh{symbol}"
        else:
            sina_code = f"sz{symbol}"
        url = f"https://hq.sinajs.cn/list={sina_code}"
        headers = {"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        content = resp.content.decode("gbk", errors="replace")
        parts = content.split('"')
        if len(parts) < 2:
            return None
        fields = parts[1].split(",")
        if len(fields) < 10:
            return None
        name = fields[0]
        price = float(fields[3]) if fields[3] else 0.0
        prev_close = float(fields[2]) if fields[2] else price
        return {
            "symbol": symbol,
            "name": name,
            "last_price": price,
            "prev_close": prev_close,
            "currency": "CNY",
            "market": "CN",
            "source": "sina",
        }
    except Exception:
        return None


def get_quote(symbol: str) -> Optional[dict]:
    """
    获取A股实时行情（统一接口）
    
    参数:
        symbol: 股票代码，如 "001270"、"600519"
    
    返回:
        {
            "symbol": str,
            "name": str,
            "last_price": float,   # 最新价
            "prev_close": float,   # 昨收价
            "currency": "CNY",
            "market": "CN",
            "source": str,         # 数据来源
        }
        失败返回 None
    """
    if _get_quote_em:
        try:
            result = _get_quote_em(symbol)
            if result and result.get("last_price", 0) > 0:
                result["source"] = "internal"
                return result
        except Exception:
            pass
    result = _get_quote_eastmoney(symbol)
    if result:
        return result
    return _get_quote_sina(symbol)


def get_realtime_price(symbol: str) -> float:
    """快速获取当前价（仅返回价格数字，失败返回0.0）"""
    q = get_quote(symbol)
    return q.get("last_price", 0.0) if q else 0.0
