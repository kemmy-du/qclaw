# -*- coding: utf-8 -*-
"""
A股模拟股票交易系统
==================

纯本地文件持久化，无需注册登录，供策略直接调用。

使用示例：
    from common.sim_account import SimAccount, get_account

    # 方式一：快速获取（全局单例）
    acc = get_account()

    # 方式二：自定义账户
    acc = SimAccount(account_id="test", initial_cash=500000).load()

    # 买入
    order = acc.buy("001270", 100, price=50.0)
    # 卖出
    order = acc.sell("001270", 100)
    # 查询
    print(acc.get_stats())        # 账户统计
    print(acc.get_positions())    # 持仓列表
    print(acc.get_trade_history()) # 成交历史
    print(acc.generate_report())  # 日报

    # 重置
    acc.reset()

核心类：
    SimAccount     - 模拟账户（持仓/资金/成交管理）
    get_account()  - 获取全局单例账户

订单类：
    Order          - 订单数据模型
    OrderSide      - BUY / SELL
    OrderType      - MARKET / LIMIT
    OrderStatus    - PENDING / FILLED / CANCELLED / REJECTED

行情：
    get_quote(symbol)           - 获取实时行情（统一接口）
    get_realtime_price(symbol)  - 快速获取当前价格

版本: 1.0.0
"""

from __future__ import annotations

# 从 sim_account 子包统一导出，保持对外 API 不变
from .sim_account import (
    SimAccount,
    get_account,
    PositionLot,
    PositionSnapshot,
    DEFAULT_INITIAL_CASH,
    DEFAULT_COMMISSION_RATE,
    DEFAULT_STAMP_TAX_SELL,
    DEFAULT_SLIPPAGE_PCT,
    DATA_DIR,
)

from .sim_account.order import (
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    TradeRecord,
)

from .sim_account.market_data import (
    get_quote,
    get_realtime_price,
)

__all__ = [
    # 账户
    "SimAccount",
    "get_account",
    "PositionLot",
    "PositionSnapshot",
    "DEFAULT_INITIAL_CASH",
    "DEFAULT_COMMISSION_RATE",
    "DEFAULT_STAMP_TAX_SELL",
    "DEFAULT_SLIPPAGE_PCT",
    "DATA_DIR",
    # 订单
    "Order",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "TradeRecord",
    # 行情
    "get_quote",
    "get_realtime_price",
]

__version__ = "1.0.0"
