# -*- coding: utf-8 -*-
"""
订单模型 - 定义订单数据结构
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"      # 市价单
    LIMIT = "LIMIT"        # 限价单


class OrderStatus(str, Enum):
    PENDING = "PENDING"    # 待成交
    PARTIAL = "PARTIAL"    # 部分成交
    FILLED = "FILLED"      # 全部成交
    CANCELLED = "CANCELLED"  # 已取消
    REJECTED = "REJECTED"  # 已拒绝
    EXPIRED = "EXPIRED"    # 已过期


@dataclass
class Order:
    """订单数据结构"""
    order_id: str
    symbol: str
    name: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    qty: int = 0           # 委托数量
    price: float = 0.0    # 委托价格（市价单=0）
    filled_qty: int = 0   # 成交数量
    avg_fill_price: float = 0.0  # 成交均价
    status: OrderStatus = OrderStatus.PENDING
    created_at: str = ""
    updated_at: str = ""
    filled_at: str = ""
    cancel_reason: str = ""
    reject_reason: str = ""
    trade_id: str = ""     # 对应的成交记录ID

    def to_dict(self) -> dict:
        d = asdict(self)
        # 枚举序列化为字符串
        d["side"] = self.side.value if isinstance(self.side, OrderSide) else self.side
        d["order_type"] = self.order_type.value if isinstance(self.order_type, OrderType) else self.order_type
        d["status"] = self.status.value if isinstance(self.status, OrderStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Order":
        # 反序列化枚举
        if "side" in d:
            d["side"] = OrderSide(d["side"])
        if "order_type" in d:
            d["order_type"] = OrderType(d["order_type"])
        if "status" in d:
            d["status"] = OrderStatus(d["status"])
        # 补默认值
        for key in ["name", "qty", "price", "filled_qty", "avg_fill_price",
                    "created_at", "updated_at", "filled_at",
                    "cancel_reason", "reject_reason", "trade_id"]:
            d.setdefault(key, "")
        d["qty"] = int(d["qty"])
        d["filled_qty"] = int(d["filled_qty"])
        d["price"] = float(d["price"] or 0)
        d["avg_fill_price"] = float(d["avg_fill_price"] or 0)
        return cls(**d)


@dataclass
class TradeRecord:
    """成交记录（由 Order 成交后生成）"""
    trade_id: str
    order_id: str
    symbol: str
    name: str = ""
    side: str = ""         # "BUY" 或 "SELL"
    price: float = 0.0
    qty: int = 0
    amount: float = 0.0    # 毛成交金额
    commission: float = 0.0 # 手续费
    stamp_tax: float = 0.0 # 印花税（仅卖出）
    net_amount: float = 0.0 # 净到账金额（卖出时）
    total_cost: float = 0.0 # 总成本（买入时）
    avg_cost: float = 0.0   # 含手续费均摊成本
    cash_after: float = 0.0
    trade_date: str = ""
    trade_time: str = ""
    realized_pnl: float = 0.0  # 已实现盈亏（卖出时才有）
    slippage: float = 0.0   # 滑点

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TradeRecord":
        for key in ["name", "stamp_tax", "net_amount", "total_cost", "avg_cost",
                    "cash_after", "trade_date", "trade_time", "realized_pnl", "slippage"]:
            d.setdefault(key, 0.0 if key in ["amount", "commission", "stamp_tax", "net_amount",
                                               "total_cost", "avg_cost", "cash_after",
                                               "realized_pnl", "price", "slippage"] else "")
        d["price"] = float(d["price"])
        d["amount"] = float(d["amount"])
        d["qty"] = int(d["qty"])
        return cls(**d)
