"""
美股行情数据源 - 自包含版本

数据源：
- Finnhub: 美股实时报价
- Polygon.io: 美股历史K线

不包含任何A股相关代码，与 stock_trader_cn 完全独立。

用法:
    from market_data_us import get_quote, get_kline, calculate_ema

    quote = get_quote("NVDL")
    kline = get_kline("NVDL", days=60)
    ema = calculate_ema(kline, period=13)
"""

import sys
import os
import time
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "d72m321r01qlfd9nns6gd72m321r01qlfd9nns70")
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "nGzVm3pmOHsTVB2WQ4kDTBqwrOwmWpGH")
POLYGON_BASE_URL = "https://api.polygon.io"


# ============================================================
# FinnhubSource（美股实时报价）
# ============================================================

class FinnhubSource:
    """Finnhub 数据源 —— 美股实时报价"""

    _cache: Dict = {}
    _cache_time: Dict = {}
    CACHE_TTL = 10

    @classmethod
    def get_quote(cls, symbol: str, use_cache: bool = True) -> Optional[Dict]:
        """
        获取美股实时报价

        Args:
            symbol: 股票代码，如 "AAPL", "NVDL"
            use_cache: 是否使用缓存

        Returns:
            Dict: 包含 last_price, prev_close, open, high, low, volume
        """
        cache_key = f"quote_{symbol}"

        if use_cache and cache_key in cls._cache:
            if time.time() - cls._cache_time.get(cache_key, 0) < cls.CACHE_TTL:
                return cls._cache[cache_key]

        try:
            url = f"{FINNHUB_BASE_URL}/quote"
            params = {"symbol": symbol.upper(), "token": FINNHUB_API_KEY}

            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('c') is not None and data['c'] > 0:
                    result = {
                        "symbol": symbol.upper(),
                        "last_price": float(data['c']),
                        "prev_close": float(data.get('pc', data['c'])),
                        "open": float(data.get('o', 0)),
                        "high": float(data.get('h', 0)),
                        "low": float(data.get('l', 0)),
                        "volume": int(data.get('v', 0)) if data.get('v') else 0,
                        "timestamp": datetime.now().isoformat()
                    }
                    cls._cache[cache_key] = result
                    cls._cache_time[cache_key] = time.time()
                    return result
        except Exception as e:
            logger.warning(f"[Finnhub] {symbol} 报价获取失败: {e}")

        return None

    @classmethod
    def get_company_profile(cls, symbol: str) -> Optional[Dict]:
        """获取公司信息"""
        try:
            url = f"{FINNHUB_BASE_URL}/stock/profile2"
            params = {"symbol": symbol.upper(), "token": FINNHUB_API_KEY}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('name'):
                    return {
                        "symbol": symbol.upper(),
                        "name": data.get('name', ''),
                        "industry": data.get('finnhubIndustry', ''),
                        "market_cap": data.get('marketCapitalization', 0),
                        "exchange": data.get('exchange', ''),
                        "currency": data.get('currency', 'USD')
                    }
        except Exception as e:
            logger.warning(f"[Finnhub] {symbol} 公司信息获取失败: {e}")
        return None

    @classmethod
    def clear_cache(cls):
        cls._cache.clear()
        cls._cache_time.clear()


# ============================================================
# PolygonSource（美股K线）
# ============================================================

class PolygonSource:
    """Polygon.io 数据源 —— 美股K线"""

    _cache: Dict = {}
    _cache_time: Dict = {}
    CACHE_TTL = 300

    @classmethod
    def get_prev_close(cls, symbol: str, use_cache: bool = True) -> Optional[float]:
        """获取前一交易日收盘价"""
        cache_key = f"prev_close_{symbol}"

        if use_cache and cache_key in cls._cache:
            if time.time() - cls._cache_time.get(cache_key, 0) < cls.CACHE_TTL:
                return cls._cache[cache_key]

        try:
            url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol.upper()}/prev"
            params = {"apiKey": POLYGON_API_KEY}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("results") and len(data["results"]) > 0:
                    prev_close = float(data["results"][0]['c'])
                    cls._cache[cache_key] = prev_close
                    cls._cache_time[cache_key] = time.time()
                    return prev_close
        except Exception as e:
            logger.warning(f"[Polygon] {symbol} 昨收获取失败: {e}")
        return None

    @classmethod
    def get_kline(cls, symbol: str, days: int = 60, use_cache: bool = True) -> Optional[pd.DataFrame]:
        """
        获取美股K线数据

        Args:
            symbol: 股票代码
            days: 获取天数
            use_cache: 是否使用缓存

        Returns:
            pd.DataFrame: columns=["open","high","low","close","volume","time"]
        """
        cache_key = f"kline_{symbol}_{days}"

        if use_cache and cache_key in cls._cache:
            if time.time() - cls._cache_time.get(cache_key, 0) < cls.CACHE_TTL:
                return cls._cache[cache_key].copy()

        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=int(days * 1.5) + 10)

            url = (f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol.upper()}"
                   f"/range/1/day/{start_date}/{end_date}")
            params = {"apiKey": POLYGON_API_KEY, "adjusted": "true", "sort": "asc"}

            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("results"):
                    results = data["results"]
                    df = pd.DataFrame({
                        "open":   [float(r['o']) for r in results],
                        "high":   [float(r['h']) for r in results],
                        "low":    [float(r['l']) for r in results],
                        "close":  [float(r['c']) for r in results],
                        "volume": [int(r['v'])   for r in results],
                        "time":   [datetime.fromtimestamp(r['t']/1000).strftime("%Y-%m-%d") for r in results]
                    })

                    # 去除今日未完成K线
                    today_str = date.today().strftime("%Y-%m-%d")
                    if len(df) > 0 and df['time'].iloc[-1] == today_str:
                        df = df.iloc[:-1]

                    cls._cache[cache_key] = df
                    cls._cache_time[cache_key] = time.time()
                    return df
        except Exception as e:
            logger.warning(f"[Polygon] {symbol} K线获取失败: {e}")
        return None

    @classmethod
    def clear_cache(cls):
        cls._cache.clear()
        cls._cache_time.clear()


# ============================================================
# 工具函数
# ============================================================

def is_chinese_market(symbol: str) -> bool:
    """判断是否为A股代码（A股：6位数字，以 0/3/6 开头）"""
    return bool(symbol.isdigit() and len(symbol) == 6 and symbol[0] in ['0', '3', '6'])


# ============================================================
# 公共接口
# ============================================================

def get_quote(symbol: str, use_cache: bool = True) -> Optional[Dict]:
    """获取美股实时报价"""
    return FinnhubSource.get_quote(symbol, use_cache)


def get_kline(symbol: str, days: int = 60, use_cache: bool = True) -> Optional[pd.DataFrame]:
    """获取美股历史K线"""
    return PolygonSource.get_kline(symbol, days, use_cache)


def get_prev_close(symbol: str, use_cache: bool = True) -> Optional[float]:
    """获取前一交易日收盘价"""
    prev = PolygonSource.get_prev_close(symbol, use_cache)
    if prev:
        return prev
    quote = FinnhubSource.get_quote(symbol, use_cache)
    return quote.get("prev_close") if quote else None


def get_company_profile(symbol: str) -> Optional[Dict]:
    """获取公司信息"""
    return FinnhubSource.get_company_profile(symbol)


def calculate_ema(df: pd.DataFrame, column: str = 'close', period: int = 13) -> pd.Series:
    """计算 EMA"""
    return df[column].ewm(span=period, adjust=False).mean()


def get_snapshots(symbols: List[str], use_cache: bool = True) -> Dict[str, Optional[Dict]]:
    """批量获取美股实时报价"""
    results = {}
    for sym in symbols:
        results[sym] = get_quote(sym, use_cache)
    return results


def clear_all_cache():
    """清除所有缓存"""
    FinnhubSource.clear_cache()
    PolygonSource.clear_cache()


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    test_symbols = ["NVDL", "LITE", "NAVN"]

    print("=" * 60)
    print(f"美股行情数据测试 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    print("\n[1] 实时报价 (Finnhub)")
    for sym in test_symbols:
        q = get_quote(sym)
        if q:
            change_pct = (q["last_price"] - q["prev_close"]) / q["prev_close"] * 100
            trend = "▲" if change_pct >= 0 else "▼"
            print(f"  {sym}: ${q['last_price']:.2f} {trend} {change_pct:+.2f}%")
        else:
            print(f"  {sym}: 获取失败")
        time.sleep(0.2)

    print("\n[2] K线 (Polygon.io)")
    df = get_kline("NVDL", days=60)
    if df is not None and len(df) > 0:
        df["ema"] = calculate_ema(df, 13)
        print(f"  共 {len(df)} 条，最新: ${df['close'].iloc[-1]:.2f}, EMA13: ${df['ema'].iloc[-1]:.2f}")
    else:
        print("  K线获取失败")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)
