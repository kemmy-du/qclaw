"""
A股行情数据源 - 东方财富网

数据源：
- 实时报价：东方财富 push2.eastmoney.com
- 历史K线：东方财富（支持前复权）
- 前日收盘：东方财富

不支持美股代码。

用法:
    from market_data_cn import get_quote, get_kline, calculate_ema

    quote = get_quote("603773")
    kline = get_kline("603773", days=60)
    ema = calculate_ema(kline, period=13)
"""

import sys
import os
import time
import logging
from datetime import datetime, date, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
import requests

logger = logging.getLogger(__name__)


# ============================================================
# 工具函数
# ============================================================

def is_chinese_market(symbol: str) -> bool:
    """
    判断是否为A股代码

    A股：6位数字，以 0/3/6 开头
    """
    return bool(symbol.isdigit() and len(symbol) == 6 and symbol[0] in ['0', '3', '6'])


def format_cn_symbol(symbol: str) -> str:
    """
    格式化为东方财富 secid

    0/3 开头 -> 0.{code}  (深交所)
    6 开头   -> 1.{code}  (上交所)
    """
    if symbol[0] in ['0', '3']:
        return f"0.{symbol}"
    elif symbol[0] == '6':
        return f"1.{symbol}"
    return symbol


# ============================================================
# 东方财富数据源
# ============================================================

class EastmoneySource:
    """东方财富网数据源"""

    name = "eastmoney"
    quote_url = "https://push2.eastmoney.com/api/qt/stock/get"
    kline_url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"

    @classmethod
    def get_quote(cls, symbol: str) -> dict:
        """
        获取A股实时报价

        Returns:
            dict: {
                "last_price": float,   # 当前价
                "prev_close": float,   # 昨收
                "open": float,         # 开盘价
                "high": float,         # 最高价
                "low": float,          # 最低价
                "change": float,       # 涨跌额
                "change_percent": float, # 涨跌幅（%）
                "name": str            # 股票名称
            }
        """
        secid = format_cn_symbol(symbol)
        params = {
            "secid": secid,
            "fltt": "2",
            "fields": "f43,f57,f58,f60,f107,f162,f163,f164,f166,f169,f170,f171",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        }

        try:
            resp = requests.get(cls.quote_url, params=params, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"东方财富 quote {symbol}: HTTP {resp.status_code}")
                return {}

            data = resp.json()
            if data.get("rc") != 0 or not data.get("data"):
                return {}

            d = data["data"]
            return {
                "last_price": float(d.get('f43', 0)) / 100,
                "prev_close": float(d.get('f60', 0)) / 100,
                "open": float(d.get('f46', 0)) / 100 if d.get('f46') else 0.0,
                "high": float(d.get('f44', 0)) / 100 if d.get('f44') else 0.0,
                "low": float(d.get('f45', 0)) / 100 if d.get('f45') else 0.0,
                "change": float(d.get('f169', 0)) / 100 if d.get('f169') else 0.0,
                "change_percent": float(d.get('f170', 0)) / 100 if d.get('f170') else 0.0,
                "name": d.get('f58', symbol),
            }
        except Exception as e:
            logger.warning(f"东方财富 snapshot failed {symbol}: {e}")
            return {}

    @classmethod
    def get_kline(cls, symbol: str, days: int = 60, fq_type: int = 1) -> pd.DataFrame:
        """
        获取A股历史K线

        Args:
            symbol:  6位股票代码
            days:    所需交易日数
            fq_type: 复权类型，0=不复权，1=前复权（默认），2=后复权

        Returns:
            DataFrame: columns=["open","high","low","close","volume","time"]
        """
        secid = format_cn_symbol(symbol)
        end_date = date.today()
        start_date = end_date - timedelta(days=days + 30)  # 缓冲

        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "secid": secid,
            "klt": "101",   # 日K线
            "fqt": str(fq_type),
            "beg": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
            "lmt": days + 10,
            "_": int(datetime.now().timestamp() * 1000),
        }

        try:
            resp = requests.get(
                cls.kline_url, params=params, timeout=10,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("rc") != 0:
                raise Exception(f"东方财富返回错误码: {data.get('rc')}, {data.get('rt')}")

            klines = data.get("data", {}).get("klines", [])
            if not klines:
                raise Exception("klines数组为空")

            records = []
            for kline in klines:
                fields = kline.split(",")
                if len(fields) >= 6:
                    records.append({
                        "open": float(fields[1]) if fields[1] else 0,
                        "close": float(fields[2]) if fields[2] else 0,
                        "high": float(fields[3]) if fields[3] else 0,
                        "low": float(fields[4]) if fields[4] else 0,
                        "volume": int(float(fields[5])) if fields[5] else 0,
                        "time": fields[0],
                    })

            df = pd.DataFrame(records)
            return df.tail(days).reset_index(drop=True)

        except Exception as e:
            logger.error(f"东方财富K线获取失败 ({symbol}): {e}")
            return pd.DataFrame()

    @classmethod
    def get_previous_close(cls, symbol: str) -> dict:
        """获取前一交易日OHLC"""
        secid = format_cn_symbol(symbol)
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=5)

            params = {
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "secid": secid,
                "klt": "101",
                "fqt": "0",
                "beg": start_date.strftime("%Y%m%d"),
                "end": end_date.strftime("%Y%m%d"),
                "lmt": 3,
                "_": int(datetime.now().timestamp() * 1000),
            }

            resp = requests.get(
                cls.kline_url, params=params, timeout=10,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("rc") == 0:
                    klines = data.get("data", {}).get("klines", [])
                    if klines:
                        fields = klines[-1].split(",")
                        return {
                            "o": float(fields[1]) if fields[1] else 0,
                            "h": float(fields[3]) if fields[3] else 0,
                            "l": float(fields[4]) if fields[4] else 0,
                            "c": float(fields[2]) if fields[2] else 0,
                            "v": int(float(fields[5])) if fields[5] else 0,
                        }
            return {}
        except Exception as e:
            logger.warning(f"东方财富 previous close failed {symbol}: {e}")
            return {}


# ============================================================
# 公共接口
# ============================================================

def get_quote(symbol: str) -> dict:
    """获取A股实时报价"""
    return EastmoneySource.get_quote(symbol)


def get_kline(symbol: str, days: int = 60, fq_type: int = 1) -> pd.DataFrame:
    """获取A股历史K线"""
    return EastmoneySource.get_kline(symbol, days=days, fq_type=fq_type)


def get_previous_close(symbol: str) -> dict:
    """获取前一交易日收盘"""
    return EastmoneySource.get_previous_close(symbol)


def calculate_ema(df: pd.DataFrame, period: int = 13) -> pd.Series:
    """计算EMA"""
    return df["close"].ewm(span=period, adjust=False).mean()


def get_snapshots(symbols: list) -> dict:
    """批量获取实时报价"""
    results = {}
    for sym in symbols:
        q = get_quote(sym)
        if q:
            results[sym] = q
        time.sleep(0.1)
    return results


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    test_symbols = ["603773", "688011", "001270"]

    print("=" * 60)
    print(f"A股行情数据测试（东方财富）- {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # 实时报价
    print("\n[1] 实时报价")
    for sym in test_symbols:
        q = get_quote(sym)
        if q:
            change_pct = q.get("change_percent", 0)
            trend = "▲" if q.get("change", 0) > 0 else "▼" if q.get("change", 0) < 0 else "→"
            print(f"  {sym}({q['name']}): ¥{q['last_price']:.2f}  "
                  f"{trend} {q['change']:+.2f} ({change_pct:+.2f}%)")
        else:
            print(f"  {sym}: 获取失败")
        time.sleep(0.2)

    # K线
    print("\n[2] K线 (603773, 60日)")
    df = get_kline("603773", days=60)
    if not df.empty:
        df["ema"] = calculate_ema(df, 13)
        print(f"  共 {len(df)} 条，最新: ¥{df['close'].iloc[-1]:.2f}, EMA13: ¥{df['ema'].iloc[-1]:.2f}")
        print("  最近5日:")
        for i in range(-5, 0):
            row = df.iloc[i]
            print(f"    {row['time']}: O¥{row['open']:.2f} H¥{row['high']:.2f} "
                  f"L¥{row['low']:.2f} C¥{row['close']:.2f}")
    else:
        print("  K线获取失败")

    # 批量报价
    print("\n[3] 批量报价")
    snaps = get_snapshots(test_symbols)
    for sym, q in snaps.items():
        print(f"  {sym}: ¥{q['last_price']:.2f}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)
