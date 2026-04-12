"""
老虎证券持仓报告 - 多渠道推送

用法:
  python push_positions.py                       # 默认飞书
  python push_positions.py --channels=feishu      # 仅飞书
  python push_positions.py --channels=weixin      # 仅微信
  python push_positions.py --channels=feishu,weixin  # 飞书+微信
"""

import sys
import os
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import requests
import json

# 导入 US common 通知模块
_REPORT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPORT_DIR)

from common.notification_us import notification, init, send_card, build_status_card, build_positions_card, FeishuCardBuilder

# 老虎证券配置
TIGER_CONFIG_PATH = "C:\\Users\\Administrator\\WorkBuddy\\Claw\\stock_monitor\\tiger_openapi_config.properties"
ACCOUNT = "21578171741955114"


def get_tiger_client():
    from tigeropen.tiger_open_config import TigerOpenClientConfig
    from tigeropen.trade.trade_client import TradeClient
    props_dir = os.path.dirname(TIGER_CONFIG_PATH)
    return TradeClient(TigerOpenClientConfig(props_path=props_dir))


def get_positions(client):
    """获取持仓"""
    try:
        positions = client.get_positions()
        result = []
        for pos in positions:
            sym = None
            if hasattr(pos, 'symbol') and pos.symbol:
                sym = pos.symbol
            elif hasattr(pos, 'contract') and pos.contract:
                sym = getattr(pos.contract, 'symbol', None)

            qty = int(getattr(pos, 'quantity', 0) or 0)
            cost = float(getattr(pos, 'average_cost', 0) or 0)
            market_val = float(getattr(pos, 'market_value', 0) or 0)

            if qty > 0 and sym:
                result.append({
                    "symbol": sym,
                    "qty": qty,
                    "cost_price": cost,
                    "market_value": market_val,
                })
        return result
    except Exception as e:
        print(f"查询持仓失败: {e}")
        return []


def get_account_info(client):
    """获取账户信息"""
    try:
        assets = client.get_assets()
        if assets and len(assets) > 0:
            asset = assets[0]
            summary = getattr(asset, 'summary', None)

            cash = 0
            net_liquidation = 0

            if summary:
                if hasattr(summary, 'cash'):
                    v = summary.cash
                    if v not in (float('inf'), None):
                        cash = float(v)
                if hasattr(summary, 'net_liquidation'):
                    v = summary.net_liquidation
                    if v not in (float('inf'), None):
                        net_liquidation = float(v)

            return {
                'total_assets': net_liquidation,
                'cash': cash,
            }
    except Exception as e:
        print(f"查询账户失败: {e}")
    return None


def get_open_orders(client, account):
    """获取活跃挂单"""
    try:
        orders = client.get_open_orders(account=account)
        result = []
        for o in orders:
            symbol = None
            if hasattr(o, 'symbol') and o.symbol:
                symbol = o.symbol
            elif hasattr(o, 'contract') and o.contract:
                symbol = getattr(o.contract, 'symbol', None)
            
            result.append({
                'order_id': getattr(o, 'order_id', '') or getattr(o, 'id', ''),
                'symbol': symbol,
                'action': getattr(o, 'action', ''),
                'order_type': getattr(o, 'order_type', ''),
                'quantity': int(getattr(o, 'quantity', 0) or 0),
                'filled_qty': int(getattr(o, 'filled_quantity', 0) or 0),
                'price': float(getattr(o, 'limit_price', 0) or getattr(o, 'price', 0) or 0),
                'status': getattr(o, 'status', ''),
                'created_at': getattr(o, 'create_time', '') or getattr(o, 'created_at', ''),
            })
        return result
    except Exception as e:
        print(f"查询挂单失败: {e}")
        return []


def get_realtime_prices(symbols):
    """获取实时价格（Finnhub）"""
    api_key = "d72m321r01qlfd9nns6gd72m321r01qlfd9nns70"
    prices = {}
    for sym in symbols:
        try:
            resp = requests.get("https://finnhub.io/api/v1/quote",
                               params={"symbol": sym, "token": api_key}, timeout=10)
            if resp.status_code == 200:
                d = resp.json()
                if d.get('c') is not None:
                    prices[sym] = {
                        "last_price": float(d['c']),
                        "prev_close": float(d.get('pc', d['c'])),
                    }
        except:
            pass
    return prices


def parse_channels():
    """从命令行参数解析通知渠道"""
    for arg in sys.argv:
        if arg.startswith("--channels="):
            return [c.strip() for c in arg.split("=", 1)[1].split(",")]
    return None  # 使用默认


def load_notification_config():
    """从策略 config.json 加载通知配置并初始化"""
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")
    if not os.path.exists(config_path):
        return
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        notify_cfg = config.get("global_defaults", {}).get("notification", {})
        if notify_cfg:
            init(
                channels=notify_cfg.get("channels"),
                weixin_target=notify_cfg.get("weixin_target"),
                feishu_webhook=notify_cfg.get("feishu_webhook") or config.get("global_defaults", {}).get("feishu_webhook"),
                enabled=True
            )
    except Exception as e:
        print(f"[通知] 加载配置失败: {e}")


# 启动时加载通知配置
load_notification_config()


def build_template_context(positions, account_info, open_orders, prices, now):
    """
    构建模板渲染所需的上下文数据
    所有变量都在这里计算好，模板只负责渲染
    """
    total_assets = account_info.get("total_assets", 0) if account_info else 0
    cash = account_info.get("cash", 0) if account_info else 0
    
    # 计算持仓数据
    position_details = []
    total_market_value = 0
    total_profit = 0
    
    for pos in positions:
        sym = pos.get("symbol", "")
        qty = pos.get("qty", 0)
        cost = pos.get("cost_price", 0)
        market_val = pos.get("market_value", 0)
        
        # 获取实时价格
        price_info = (prices or {}).get(sym, {})
        last_price = price_info.get("last_price", 0)
        
        # 计算盈亏
        if last_price > 0:
            profit = (last_price - cost) * qty
            profit_pct = (last_price - cost) / cost * 100 if cost > 0 else 0
            market_value = last_price * qty
        else:
            profit = market_val - cost * qty
            profit_pct = profit / (cost * qty) * 100 if cost * qty > 0 else 0
            market_value = market_val if market_val else cost * qty
            if not last_price and market_value:
                last_price = market_value / qty if qty > 0 else 0
        
        total_market_value += market_value
        total_profit += profit
        
        # 持仓明细变量
        profit_emoji = "🟢" if profit >= 0 else "🔴"
        profit_sign = "+" if profit >= 0 else ""
        
        position_details.append({
            "symbol": sym,
            "qty": qty,
            "cost_price": cost,
            "last_price": last_price,
            "profit": profit,
            "profit_pct": profit_pct,
            "profit_emoji": profit_emoji,
            "profit_sign": profit_sign,
        })
    
    # 账户汇总变量
    position_ratio = (total_market_value / total_assets * 100) if total_assets > 0 else 0
    daily_pnl = total_profit
    daily_pnl_pct = (daily_pnl / total_assets * 100) if total_assets > 0 else 0
    daily_pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
    daily_pnl_sign = "+" if daily_pnl >= 0 else ""
    
    # 挂单数据
    order_count = len(open_orders) if open_orders else 0
    open_orders_text = ""
    if open_orders:
        order_lines = []
        for o in open_orders:
            sym = o.get("symbol", "???")
            action = o.get("action", "")
            action_text = "买入" if action == "BUY" else "卖出" if action == "SELL" else action
            qty = o.get("quantity", 0) - o.get("filled_qty", 0)
            price = o.get("price", 0)
            if price > 0:
                order_lines.append(f"  {action_text} {sym} {qty}股 @ ${price:.2f}")
            else:
                order_lines.append(f"  {action_text} {sym} {qty}股 (市价)")
        open_orders_text = "\n".join(order_lines)
    else:
        open_orders_text = "(0笔)"
    
    # 持仓明细内容
    positions_content = ""
    if position_details:
        lines = []
        for p in position_details:
            lines.append(
                f"{p['profit_emoji']} {p['symbol']}\n"
                f" 持仓: {p['qty']}股\n"
                f" 成本${p['cost_price']:.2f} 现价${p['last_price']:.2f} ({p['profit_sign']}{p['profit_pct']:.1f}%) "
                f"盈亏{p['profit_sign']}${int(round(p['profit']))}"
            )
        positions_content = "\n".join(lines)
    
    # 日期
    date_str = now.strftime("%Y年%m月%d日")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # 颜色
    color = "green" if total_profit >= 0 else "red"
    
    return {
        # 基础变量
        "strategy_name": "定投策略",
        "date": date_str,
        "timestamp": timestamp,
        "color": color,
        
        # 账户汇总
        "total_assets": total_assets,
        "cash": cash,
        "total_market_value": total_market_value,
        "position_ratio": position_ratio,
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": daily_pnl_pct,
        "daily_pnl_emoji": daily_pnl_emoji,
        "daily_pnl_sign": daily_pnl_sign,
        
        # 挂单
        "order_count": order_count,
        "open_orders_text": open_orders_text,
        
        # 持仓
        "position_count": len(positions),
        "position_details_content": positions_content,
        "position_details": position_details,
    }


def send_notification(context, channels=None):
    """发送持仓报告"""
    card = build_positions_card(**context)
    return send_card(card, channels=channels)


def main():
    channels = parse_channels()
    now = datetime.now()

    print(f"\n{'='*60}")
    print(f"老虎证券持仓报告 - {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if channels:
        print(f"通知渠道: {channels}")
    print(f"{'='*60}")

    client = get_tiger_client()

    # 获取账户信息
    print("\n[1] 查询账户...")
    acc = get_account_info(client)
    if acc:
        print(f"  总资产: ${acc['total_assets']:,.2f}")
        print(f"  现金: ${acc['cash']:,.2f}")

    # 获取持仓
    print("\n[2] 查询持仓...")
    positions = get_positions(client)
    if not positions:
        print("  无持仓")
        # 使用状态模板发送无持仓通知
        card = build_status_card(
            title="[定投策略] 持仓报告",
            content="账户无任何持仓",
            color="grey",
            strategy_name="定投策略"
        )
        send_card(card, channels=channels)
        return

    print(f"  持仓数量: {len(positions)}")

    # 获取活跃挂单
    print("\n[3] 查询挂单...")
    open_orders = get_open_orders(client, ACCOUNT)
    print(f"  挂单数量: {len(open_orders)}")

    # 获取实时价格
    symbols = [p["symbol"] for p in positions]
    order_symbols = [o["symbol"] for o in open_orders if o["symbol"] and o["symbol"] not in symbols]
    symbols.extend(order_symbols)
    print(f"\n[4] 获取实时价格...")
    prices = get_realtime_prices(symbols)

    # 构建模板上下文
    print(f"\n[5] 构建模板上下文...")
    context = build_template_context(positions, acc, open_orders, prices, now)
    
    print(f"  总资产: ${context['total_assets']:,.0f}")
    print(f"  持仓市值: ${context['total_market_value']:,.0f}")
    print(f"  当日盈亏: {context['daily_pnl_emoji']} ${context['daily_pnl_sign']}${context['daily_pnl']:,.0f}")
    print(f"  持仓数量: {context['position_count']}只")

    # 发送通知
    print(f"\n[6] 发送通知...")
    ok = send_notification(context, channels=channels)
    if ok:
        print("  发送成功")
    else:
        print("  发送失败")


if __name__ == "__main__":
    main()