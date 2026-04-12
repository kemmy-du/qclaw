# -*- coding: utf-8 -*-
"""
股票模拟交易系统 - A股策略验证专用
无需注册登录，纯本地文件持久化，供策略直接调用

作者: QClaw Agent
版本: 1.0.0
"""

from __future__ import annotations

import json
import os
import copy
import uuid
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Optional, Dict, List, Any
from enum import Enum

from .order import Order, OrderStatus, OrderType, OrderSide
from .market_data import get_quote


# ============================================================
# 常量
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

DEFAULT_INITIAL_CASH = 1_000_000.0        # 默认初始资金 100万
DEFAULT_COMMISSION_RATE = 0.0003           # 佣金（万三）
DEFAULT_STAMP_TAX_SELL = 0.001             # 印花税（卖出时千一）
DEFAULT_SLIPPAGE_PCT = 0.001               # 默认滑点（千分之一）


# ============================================================
# 持仓（单笔买入记录）
# ============================================================

@dataclass
class PositionLot:
    """持仓批次（用于 T+1 精确追踪）"""
    lot_id: str               # 批次唯一ID
    symbol: str               # 股票代码
    qty: int                  # 当前剩余数量
    avg_cost: float           # 买入均价（含手续费摊分）
    buy_date: str             # 买入日期 "YYYY-MM-DD"
    buy_time: str             # 买入时间 "HH:MM:SS"
    buy_price: float          # 买入价格（原始成交价）
    buy_order_id: str         # 对应买入订单ID

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PositionLot":
        return cls(**d)


# ============================================================
# 持仓快照（实时统计）
# ============================================================

@dataclass
class PositionSnapshot:
    """某一时刻某标的的持仓快照"""
    symbol: str
    name: str = ""
    total_qty: int = 0              # 总持仓股数
    avg_cost: float = 0.0           # 综合持仓成本
    can_sell_today: int = 0         # 今日可卖数量（T+0部分，极少）
    can_sell_tomorrow: int = 0      # 明日可卖数量
    market_value: float = 0.0       # 市值
    unrealized_pnl: float = 0.0      # 浮动盈亏
    unrealized_pnl_pct: float = 0.0 # 浮动盈亏比例%
    today_bought: int = 0           # 今日买入数量（这部分今日不可卖）
    current_price: float = 0.0      # 当前价

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# 模拟账户
# ============================================================

class SimAccount:
    """
    A股模拟股票账户

    核心功能：
    - 现金管理
    - 持仓管理（支持多批次，支持 T+1 精确校验）
    - 下单/成交（支持市价/限价，自动滑点）
    - 实时资金计算（市值 + 可用现金）
    - 历史成交记录
    - 全量状态持久化（JSON）

    用法：
        from common.sim_account import SimAccount
        acc = SimAccount(initial_cash=1_000_000)
        acc.load()  # 加载已有账户或创建新账户
        acc.buy("001270", 100, price=50.0)   # 市价买入
        acc.sell("001270", 100)               # 市价卖出
        print(acc.get_positions())
        print(acc.get_stats())
    """

    def __init__(
        self,
        account_id: str = "default",
        initial_cash: float = DEFAULT_INITIAL_CASH,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        stamp_tax_sell: float = DEFAULT_STAMP_TAX_SELL,
        slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
        enable_market_data: bool = True,
        data_dir: str = DATA_DIR,
    ):
        self.account_id = account_id
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        self.stamp_tax_sell = stamp_tax_sell
        self.slippage_pct = slippage_pct
        self.enable_market_data = enable_market_data

        self._data_dir = data_dir
        os.makedirs(self._data_dir, exist_ok=True)

        # ----- 内存状态 -----
        self.cash: float = initial_cash           # 当前可用资金
        self.frozen_cash: float = 0.0             # 冻结资金（下单时预扣）
        self.positions: Dict[str, List[PositionLot]] = {}  # symbol -> [lots]
        self.orders: List[Order] = []              # 历史订单
        self.trades: List[dict] = []              # 历史成交
        self.created_at: str = ""
        self.updated_at: str = ""
        self.version: str = "1.0"

        self._account_file = os.path.join(self._data_dir, f"{account_id}.json")
        self._pending_orders: List[Order] = []     # 当日未成交订单（运行时状态）

    # ============================================================
    # 持久化
    # ============================================================

    def _now_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _today_str(self) -> str:
        return date.today().strftime("%Y-%m-%d")

    def _save(self):
        """保存账户状态到文件"""
        self.updated_at = self._now_str()
        data = {
            "account_id": self.account_id,
            "version": self.version,
            "created_at": self.created_at or self._now_str(),
            "updated_at": self.updated_at,
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "frozen_cash": self.frozen_cash,
            "positions": {
                sym: [lot.to_dict() for lot in lots]
                for sym, lots in self.positions.items()
            },
            "orders": [o.to_dict() for o in self.orders],
            "trades": self.trades,
        }
        with open(self._account_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self) -> "SimAccount":
        """加载账户（不存在则创建新账户）"""
        if os.path.exists(self._account_file):
            with open(self._account_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.created_at = data.get("created_at", "")
            self.updated_at = data.get("updated_at", "")
            self.cash = float(data.get("cash", self.initial_cash))
            self.frozen_cash = float(data.get("frozen_cash", 0.0))
            self.positions = {
                sym: [PositionLot.from_dict(l) for l in lots]
                for sym, lots in data.get("positions", {}).items()
            }
            self.orders = [Order.from_dict(o) for o in data.get("orders", [])]
            self.trades = data.get("trades", [])
            print(f"[SimAccount] 已加载账户 {self.account_id}，现金={self.cash:.2f}，持仓标的={list(self.positions.keys())}")
        else:
            self.created_at = self._now_str()
            self._save()
            print(f"[SimAccount] 新建账户 {self.account_id}，初始资金={self.initial_cash:.2f}")
        return self

    def reset(self, initial_cash: Optional[float] = None):
        """重置账户（清空所有持仓和历史）"""
        if initial_cash is not None:
            self.initial_cash = initial_cash
        self.cash = self.initial_cash
        self.frozen_cash = 0.0
        self.positions = {}
        self.orders = []
        self.trades = []
        self._pending_orders = []
        self._save()
        print(f"[SimAccount] 账户已重置，初始资金={self.initial_cash:.2f}")

    # ============================================================
    # 持仓查询
    # ============================================================

    def get_position_qty(self, symbol: str) -> int:
        """获取某标的总持仓数量"""
        lots = self.positions.get(symbol, [])
        return sum(lot.qty for lot in lots)

    def get_position_lots(self, symbol: str) -> List[PositionLot]:
        """获取某标的所有持仓批次"""
        return list(self.positions.get(symbol, []))

    def get_can_sell_qty(self, symbol: str, target_date: Optional[str] = None) -> int:
        """
        计算某标的在目标日期可卖数量
        
        A股 T+1 规则：
        - 今天买的股票，今天不能卖
        - 之前买的，今天可以卖
        """
        if target_date is None:
            target_date = self._today_str()
        today = datetime.strptime(target_date, "%Y-%m-%d")
        total = 0
        for lot in self.positions.get(symbol, []):
            buy_date = datetime.strptime(lot.buy_date, "%Y-%m-%d")
            # T+1: 买入次日才可卖出
            if (today - buy_date).days >= 1:
                total += lot.qty
        return total

    def get_positions_snapshot(self) -> Dict[str, PositionSnapshot]:
        """获取所有持仓快照（含实时行情）"""
        snapshots = {}
        for symbol, lots in self.positions.items():
            if not lots:
                continue
            total_qty = sum(lot.qty for lot in lots)
            if total_qty <= 0:
                continue
            # 综合成本
            total_cost = sum(lot.avg_cost * lot.qty for lot in lots)
            avg_cost = total_cost / total_qty
            # T+1 可卖数量
            can_sell = self.get_can_sell_qty(symbol)
            today_bought = sum(
                lot.qty for lot in lots
                if lot.buy_date == self._today_str()
            )
            # 实时行情
            current_price = 0.0
            name = ""
            if self.enable_market_data:
                quote = get_quote(symbol)
                if quote:
                    current_price = quote.get("last_price", 0.0)
                    name = quote.get("name", symbol)
            market_value = current_price * total_qty
            unrealized_pnl = (current_price - avg_cost) * total_qty
            unrealized_pnl_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0.0
            snapshots[symbol] = PositionSnapshot(
                symbol=symbol,
                name=name,
                total_qty=total_qty,
                avg_cost=avg_cost,
                can_sell_today=0,          # A股基本没有T+0
                can_sell_tomorrow=can_sell - today_bought,
                market_value=market_value,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                today_bought=today_bought,
                current_price=current_price,
            )
        return snapshots

    def get_positions(self) -> List[dict]:
        """获取持仓列表（兼容旧API）"""
        snapshots = self.get_positions_snapshot()
        return [s.to_dict() for s in snapshots.values()]

    # ============================================================
    # 账户统计
    # ============================================================

    def get_stats(self) -> dict:
        """获取账户统计"""
        pos_snapshots = self.get_positions_snapshot()
        total_market_value = sum(s.market_value for s in pos_snapshots.values())
        total_unrealized_pnl = sum(s.unrealized_pnl for s in pos_snapshots.values())
        total_assets = self.cash + total_market_value
        total_cost = sum(s.avg_cost * s.total_qty for s in pos_snapshots.values())
        realized_pnl = sum(t.get("realized_pnl", 0.0) for t in self.trades)

        return {
            "account_id": self.account_id,
            "date": self._today_str(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "frozen_cash": self.frozen_cash,
            "total_market_value": total_market_value,
            "total_assets": total_assets,
            "total_cost": total_cost,
            "total_unrealized_pnl": total_unrealized_pnl,
            "total_realized_pnl": realized_pnl,
            "total_pnl": total_unrealized_pnl + realized_pnl,
            "total_pnl_pct": (total_assets - self.initial_cash) / self.initial_cash * 100,
            "position_count": len(pos_snapshots),
            "positions": [s.to_dict() for s in pos_snapshots.values()],
        }

    def get_trade_history(self, limit: int = 100) -> List[dict]:
        """获取成交历史"""
        return list(reversed(self.trades))[:limit]

    def get_order_history(self, symbol: Optional[str] = None, limit: int = 50) -> List[dict]:
        """获取订单历史"""
        orders = list(reversed(self.orders))
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return [o.to_dict() for o in orders[:limit]]

    # ============================================================
    # 下单核心
    # ============================================================

    def _new_order_id(self) -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S") + str(uuid.uuid4())[:6].upper()

    def _calc_commission(self, amount: float) -> float:
        """计算佣金（不足5元按5元收）"""
        comm = amount * self.commission_rate
        return max(comm, 5.0) if amount > 0 else 0.0

    def _apply_slippage(self, price: float, side: OrderSide, order_type: OrderType = OrderType.MARKET) -> float:
        """应用滑点"""
        if order_type == OrderType.LIMIT:
            return price
        slip = price * self.slippage_pct
        if side == OrderSide.BUY:
            return price + slip
        else:
            return price - slip

    def _validate_buy(self, symbol: str, qty: int, price: float) -> tuple[bool, str]:
        """买入前校验"""
        if qty <= 0:
            return False, f"买入数量必须>0，当前={qty}"
        if qty % 100 != 0:
            return False, f"A股买入数量必须是100的整数倍，当前={qty}"
        # 粗估成本
        est_cost = price * qty * (1 + self.commission_rate)
        if self.cash < est_cost:
            return False, f"资金不足：需要约{est_cost:.2f}，可用{self.cash:.2f}"
        return True, "ok"

    def _validate_sell(self, symbol: str, qty: int) -> tuple[bool, str, int]:
        """卖出前校验，返回(can_sell, msg, can_sell_qty)"""
        if qty <= 0:
            return False, f"卖出数量必须>0，当前={qty}", 0
        if qty % 100 != 0:
            return False, f"A股卖出数量必须是100的整数倍，当前={qty}", 0
        can_sell = self.get_can_sell_qty(symbol)
        if can_sell < qty:
            return False, f"可卖数量不足：需要{qty}股，当前可卖{can_sell}股（T+1规则）", can_sell
        return True, "ok", can_sell

    def _execute_buy(
        self, symbol: str, qty: int, exec_price: float,
        order_id: str, name: str = ""
    ) -> Order:
        """执行买入（内部方法）"""
        # 滑点加成
        buy_price = self._apply_slippage(exec_price, OrderSide.BUY)
        amount = buy_price * qty
        commission = self._calc_commission(amount)
        total_cost = amount + commission
        avg_cost = total_cost / qty  # 含佣金均摊

        # 扣款
        self.cash -= total_cost

        # 记录成交
        trade = {
            "trade_id": self._new_order_id(),
            "order_id": order_id,
            "symbol": symbol,
            "name": name,
            "side": "BUY",
            "price": buy_price,
            "qty": qty,
            "amount": amount,
            "commission": commission,
            "total_cost": total_cost,
            "avg_cost": avg_cost,
            "cash_after": self.cash,
            "trade_date": self._today_str(),
            "trade_time": datetime.now().strftime("%H:%M:%S"),
            "realized_pnl": 0.0,
            "slippage": buy_price - exec_price,
        }
        self.trades.append(trade)

        # 记录持仓批次
        lot = PositionLot(
            lot_id=trade["trade_id"],
            symbol=symbol,
            qty=qty,
            avg_cost=avg_cost,
            buy_date=self._today_str(),
            buy_time=datetime.now().strftime("%H:%M:%S"),
            buy_price=buy_price,
            buy_order_id=order_id,
        )
        if symbol not in self.positions:
            self.positions[symbol] = []
        self.positions[symbol].append(lot)

        # 更新订单
        order = Order(
            order_id=order_id,
            symbol=symbol,
            name=name,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=qty,
            price=exec_price,
            filled_qty=qty,
            avg_fill_price=buy_price,
            status=OrderStatus.FILLED,
            filled_at=self._now_str(),
            trade_id=trade["trade_id"],
        )
        self.orders.append(order)
        self._save()

        return order

    def _execute_sell(
        self, symbol: str, qty: int, exec_price: float,
        order_id: str, name: str = ""
    ) -> Order:
        """执行卖出（内部方法，按FIFO消耗批次）"""
        sell_price = self._apply_slippage(exec_price, OrderSide.SELL)
        amount = sell_price * qty
        commission = self._calc_commission(amount)
        stamp_tax = amount * self.stamp_tax_sell
        net_amount = amount - commission - stamp_tax

        # FIFO 消耗批次
        lots = self.positions.get(symbol, [])
        remaining = qty
        realized_pnl = 0.0
        sold_lots = []

        for lot in list(lots):
            if remaining <= 0:
                break
            sell_from_lot = min(lot.qty, remaining)
            realized_pnl += (sell_price - lot.avg_cost) * sell_from_lot
            lot.qty -= sell_from_lot
            remaining -= sell_from_lot
            sold_lots.append((lot.lot_id, sell_from_lot))

        # 清理空批次
        self.positions[symbol] = [l for l in self.positions[symbol] if l.qty > 0]
        if not self.positions[symbol]:
            del self.positions[symbol]

        # 到账
        self.cash += net_amount

        # 记录成交
        trade = {
            "trade_id": self._new_order_id(),
            "order_id": order_id,
            "symbol": symbol,
            "name": name,
            "side": "SELL",
            "price": sell_price,
            "qty": qty,
            "amount": amount,
            "commission": commission,
            "stamp_tax": stamp_tax,
            "net_amount": net_amount,
            "avg_cost": sum(l[1] * next((ll.avg_cost for ll in lots if ll.lot_id == l[0]), 0) for l in sold_lots) / qty if qty > 0 else 0,
            "cash_after": self.cash,
            "trade_date": self._today_str(),
            "trade_time": datetime.now().strftime("%H:%M:%S"),
            "realized_pnl": realized_pnl,
            "slippage": exec_price - sell_price,
            "sold_lots": sold_lots,
        }
        self.trades.append(trade)

        # 更新订单
        order = Order(
            order_id=order_id,
            symbol=symbol,
            name=name,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=qty,
            price=exec_price,
            filled_qty=qty,
            avg_fill_price=sell_price,
            status=OrderStatus.FILLED,
            filled_at=self._now_str(),
            trade_id=trade["trade_id"],
        )
        self.orders.append(order)
        self._save()

        return order

    # ============================================================
    # 公开下单接口
    # ============================================================

    def buy(
        self,
        symbol: str,
        qty: int,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET,
        name: str = "",
        enable_slippage: bool = True,
    ) -> Order:
        """
        买入股票（市价单或限价单）

        参数:
            symbol: 股票代码，如 "001270"
            qty: 买入数量（必须是100的整数倍）
            price: 指定价格（None=市价单，实时获取行情价）
            order_type: OrderType.MARKET（市价）或 LIMIT（限价）
            name: 股票名称（可选，用于记录）
            enable_slippage: 是否启用滑点（默认启用）

        返回:
            Order 对象
        """
        order_id = self._new_order_id()

        # 获取实时价格
        if price is None:
            if self.enable_market_data:
                quote = get_quote(symbol)
                if quote:
                    price = quote.get("last_price", 0.0)
                    name = name or quote.get("name", symbol)
                else:
                    print(f"[SimAccount] 警告: 无法获取 {symbol} 行情，买入失败")
                    order = Order(
                        order_id=order_id, symbol=symbol, name=name,
                        side=OrderSide.BUY, order_type=order_type,
                        qty=qty, price=0, status=OrderStatus.REJECTED,
                        reject_reason="行情获取失败"
                    )
                    self.orders.append(order)
                    self._save()
                    return order
            else:
                price = 0.0

        valid, msg = self._validate_buy(symbol, qty, price)
        if not valid:
            print(f"[SimAccount] 买入拒绝: {msg}")
            order = Order(
                order_id=order_id, symbol=symbol, name=name,
                side=OrderSide.BUY, order_type=order_type,
                qty=qty, price=price, status=OrderStatus.REJECTED,
                reject_reason=msg
            )
            self.orders.append(order)
            self._save()
            return order

        print(f"[SimAccount] 买入: {symbol}({name}) x{qty} @ {price:.3f}")
        return self._execute_buy(symbol, qty, price, order_id, name)

    def sell(
        self,
        symbol: str,
        qty: int,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET,
        name: str = "",
    ) -> Order:
        """
        卖出股票

        参数:
            symbol: 股票代码
            qty: 卖出数量（必须是100的整数倍）
            price: 指定价格（None=市价单）
            order_type: OrderType.MARKET 或 LIMIT

        返回:
            Order 对象
        """
        order_id = self._new_order_id()

        # 获取实时价格
        if price is None:
            if self.enable_market_data:
                quote = get_quote(symbol)
                if quote:
                    price = quote.get("last_price", 0.0)
                    name = name or quote.get("name", symbol)
                else:
                    print(f"[SimAccount] 警告: 无法获取 {symbol} 行情，卖出失败")
                    order = Order(
                        order_id=order_id, symbol=symbol, name=name,
                        side=OrderSide.SELL, order_type=order_type,
                        qty=qty, price=0, status=OrderStatus.REJECTED,
                        reject_reason="行情获取失败"
                    )
                    self.orders.append(order)
                    self._save()
                    return order
            else:
                price = 0.0

        valid, msg, can_sell = self._validate_sell(symbol, qty)
        if not valid:
            print(f"[SimAccount] 卖出拒绝: {msg}（可卖={can_sell}）")
            order = Order(
                order_id=order_id, symbol=symbol, name=name,
                side=OrderSide.SELL, order_type=order_type,
                qty=qty, price=price, status=OrderStatus.REJECTED,
                reject_reason=msg
            )
            self.orders.append(order)
            self._save()
            return order

        print(f"[SimAccount] 卖出: {symbol}({name}) x{qty} @ {price:.3f}")
        return self._execute_sell(symbol, qty, price, order_id, name)

    def cancel_order(self, order_id: str) -> bool:
        """取消未成交订单"""
        for o in self._pending_orders:
            if o.order_id == order_id and o.status == OrderStatus.PENDING:
                o.status = OrderStatus.CANCELLED
                o.updated_at = self._now_str()
                # 解冻资金（如果之前有冻结）
                self.orders.append(o)
                self._save()
                print(f"[SimAccount] 订单已取消: {order_id}")
                return True
        return False

    # ============================================================
    # 报表
    # ============================================================

    def generate_report(self) -> str:
        """生成账户日报字符串"""
        stats = self.get_stats()
        pos_list = stats["positions"]

        lines = []
        lines.append(f"{'=' * 50}")
        lines.append(f"  A股模拟账户日报  {stats['date']} {stats['time']}")
        lines.append(f"{'=' * 50}")
        lines.append(f"  账户ID    : {stats['account_id']}")
        lines.append(f"  初始资金  : ¥{stats['initial_cash']:,.2f}")
        lines.append(f"  当前现金  : ¥{stats['cash']:,.2f}")
        lines.append(f"  总市值    : ¥{stats['total_market_value']:,.2f}")
        lines.append(f"  总资产    : ¥{stats['total_assets']:,.2f}")
        lines.append(f"  浮动盈亏  : ¥{stats['total_unrealized_pnl']:,.2f} ({stats['total_unrealized_pnl']/stats['total_assets']*100:+.2f}%)")
        lines.append(f"  已实现盈亏: ¥{stats['total_realized_pnl']:,.2f}")
        lines.append(f"  总盈亏    : ¥{stats['total_pnl']:,.2f} ({stats['total_pnl_pct']:+.2f}%)")
        lines.append(f"  持仓数量  : {stats['position_count']} 只")
        lines.append(f"{'=' * 50}")

        if pos_list:
            lines.append(f"{'代码':<8} {'名称':<10} {'持仓':>6} {'成本':>8} {'现价':>8} {'市值':>10} {'盈亏%':>8}")
            lines.append("-" * 60)
            for p in sorted(pos_list, key=lambda x: x["unrealized_pnl_pct"], reverse=True):
                emoji = "🟢" if p["unrealized_pnl"] >= 0 else "🔴"
                lines.append(
                    f"{p['symbol']:<8} {p['name'][:10]:<10} "
                    f"{p['total_qty']:>6} {p['avg_cost']:>8.3f} {p['current_price']:>8.3f} "
                    f"{p['market_value']:>10.2f} {emoji}{p['unrealized_pnl_pct']:>+6.2f}%"
                )
        else:
            lines.append("  （暂无持仓）")

        lines.append(f"{'=' * 50}")
        return "\n".join(lines)

    def __repr__(self):
        stats = self.get_stats()
        return (
            f"SimAccount(id={self.account_id}, cash={stats['cash']:.2f}, "
            f"assets={stats['total_assets']:.2f}, "
            f"pnl={stats['total_pnl']:.2f}({stats['total_pnl_pct']:+.2f}%), "
            f"positions={stats['position_count']})"
        )


# ============================================================
# 快捷工厂函数
# ============================================================

_default_account: Optional[SimAccount] = None

def get_account(
    account_id: str = "default",
    initial_cash: float = DEFAULT_INITIAL_CASH,
    **kwargs
) -> SimAccount:
    """获取全局单例账户（默认账户）"""
    global _default_account
    if _default_account is None or _default_account.account_id != account_id:
        _default_account = SimAccount(
            account_id=account_id,
            initial_cash=initial_cash,
            **kwargs
        ).load()
    return _default_account
