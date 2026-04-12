# -*- coding: utf-8 -*-
"""
sim_account 子包 - A股模拟账户核心模块
============================================

导出 SimAccount 及相关类型，供外部统一导入：

    from common.sim_account import SimAccount, get_account
    from common.sim_account import Order, OrderSide, OrderType, OrderStatus

版本: 1.0.0
"""

from __future__ import annotations

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

from .order import (
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    TradeRecord,
)

from .market_data import (
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
