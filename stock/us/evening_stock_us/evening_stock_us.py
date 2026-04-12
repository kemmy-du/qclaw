"""
尾盘交易策略 - 美股
每天凌晨3:55市价买入，第二天21:35市价卖出，T+1持仓

用法:
  python evening_stock_us.py --buy     # 买入（凌晨3:55执行）
  python evening_stock_us.py --sell   # 卖出（21:35执行）
  python evening_stock_us.py --status # 查看持仓状态
"""

import sys
import os
import json
import time
from datetime import datetime, date

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加本目录 common 到路径
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_COMMON_DIR = os.path.join(_SCRIPT_DIR, "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

from market_data import get_quote
from notification import send_card, create_config, FeishuCardBuilder, build_status_card

STRATEGY_NAME = "美股尾盘策略"

# ============================================================
# 配置加载
# ============================================================

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_symbol_config(symbol: str):
    config = load_config()
    if symbol not in config["symbol_configs"]:
        raise ValueError(f"股票配置不存在: {symbol}")
    cfg = config["symbol_configs"][symbol].copy()
    global_defaults = config.get("global_defaults", {})
    cfg.setdefault("account", global_defaults.get("account", ""))
    cfg.setdefault("tiger_config_path", global_defaults.get("tiger_config_path", ""))
    cfg.setdefault("feishu_webhook", global_defaults.get("feishu_webhook", ""))
    cfg.setdefault("send_to_feishu", global_defaults.get("send_to_feishu", False))
    notify_cfg = global_defaults.get("notification", {})
    strategy_notify = cfg.get("notification", {})
    channels = strategy_notify.get("channels") or notify_cfg.get("channels") or ["feishu"]
    cfg["_notification_config"] = create_config(
        webhook=cfg.get("feishu_webhook"),
        enabled=cfg.get("send_to_feishu", False),
        channels=channels,
        weixin_target=strategy_notify.get("weixin_target") or notify_cfg.get("weixin_target")
    )
    return cfg

def get_enabled_symbols():
    return load_config().get("enabled_symbols", [])

# ============================================================
# 全局变量
# ============================================================

CONFIG = load_config()
ACCOUNT = CONFIG.get("global_defaults", {}).get("account", "")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ============================================================
# 老虎证券 API
# ============================================================

def get_tiger_api(symbol_cfg):
    try:
        import logging
        from tigeropen.trade.trade_client import TradeClient
        from tigeropen.tiger_open_config import TigerOpenClientConfig
        config_path = symbol_cfg.get("tiger_config_path", "")
        if not config_path or not os.path.exists(config_path):
            return None
        logger = logging.getLogger('tigeropen')
        logger.setLevel(logging.WARNING)
        config = TigerOpenClientConfig(sandbox_debug=False, props_path=config_path)
        return TradeClient(config, logger=logger)
    except Exception as e:
        print(f"[老虎] API初始化失败: {e}")
    return None

def get_positions(api, account):
    try:
        if api:
            resp = api.get_positions(account=account)
            if resp:
                positions = []
                for pos in resp if isinstance(resp, list) else []:
                    contract = str(pos.contract) if pos.contract else ""
                    symbol = contract.split("/")[0] if "/" in contract else contract
                    positions.append({
                        "symbol": symbol,
                        "quantity": pos.quantity,
                        "avg_cost": pos.average_cost,
                        "market_price": pos.market_price
                    })
                return positions
    except Exception as e:
        print(f"[持仓] 获取失败: {e}")
    return []

def place_market_order(api, account, symbol, qty, action):
    try:
        from tigeropen.trade.domain.contract import Contract
        from tigeropen.trade.domain.order import Order
        from tigeropen.common.consts import Market, OrderType, SecurityType
        contract = Contract(symbol=symbol, currency="USD", sec_type=SecurityType.STK)
        order = Order(
            account=account,
            contract=contract,
            action=action,
            order_type=OrderType.MKT.value,
            quantity=qty
        )
        order_id = api.place_order(order)
        if order_id:
            print(f"[下单] {action} {symbol} x{qty}, 订单ID: {order_id}")
            return {"order_id": order_id}
    except Exception as e:
        print(f"[下单] {action} {symbol} x{qty} 失败: {e}")
    return None

# ============================================================
# 通知
# ============================================================

def _notif_kwargs(notif_cfg):
    return {"enabled": notif_cfg.enabled if notif_cfg else False,
            "channels": notif_cfg.channels if notif_cfg else None}

def send_trade_notification(symbol, action, price, qty, order_id="", reason=""):
    cfg = get_symbol_config(symbol)
    notif_cfg = cfg.get("_notification_config")
    action_text = "买入" if action == "BUY" else "卖出"
    color = "green" if action == "BUY" else "red"
    name = cfg.get("name", symbol)
    builder = FeishuCardBuilder(title=f"[{STRATEGY_NAME}] {action_text} - {symbol} ({name})", color=color)
    builder.add_key_value("交易方向", f"**{action_text}**")
    builder.add_key_value("成交价格", f"`${price:.2f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    builder.add_key_value("订单ID", f"`{order_id or 'N/A'}`")
    if reason:
        builder.add_key_value("原因", reason)
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {STRATEGY_NAME} | 自动通知")
    return send_card(builder.build(), **_notif_kwargs(notif_cfg))

def send_profit_notification(symbol, buy_price, sell_price, qty, buy_date="", sell_date="", sell_reason=""):
    cfg = get_symbol_config(symbol)
    notif_cfg = cfg.get("_notification_config")
    name = cfg.get("name", symbol)
    profit_amount = (sell_price - buy_price) * qty
    profit_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    is_profit = profit_amount >= 0
    color = "green" if is_profit else "red"
    emoji = "🟢" if is_profit else "🔴"
    builder = FeishuCardBuilder(title=f"[{STRATEGY_NAME}] 卖出 - {symbol} ({name})", color=color)
    builder.add_markdown(f"{emoji} **盈亏: `${profit_amount:.2f}` ({profit_pct:+.2f}%)**")
    builder.add_divider()
    if buy_date:
        builder.add_key_value("买入日期", buy_date)
    if sell_date:
        builder.add_key_value("卖出日期", sell_date)
    builder.add_key_value("买入价", f"`${buy_price:.2f}`")
    builder.add_key_value("卖出价", f"`${sell_price:.2f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    builder.add_key_value("持仓盈亏", f"{emoji} `${profit_amount:.2f}`")
    if sell_reason:
        builder.add_key_value("卖出原因", sell_reason)
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {STRATEGY_NAME} | 自动通知")
    return send_card(builder.build(), **_notif_kwargs(notif_cfg))

def send_status_notification(symbol, content, color="blue"):
    cfg = get_symbol_config(symbol)
    notif_cfg = cfg.get("_notification_config")
    card = build_status_card(title=f"[{STRATEGY_NAME}] {symbol} 提醒", content=content, color=color)
    return send_card(card, **_notif_kwargs(notif_cfg))

# ============================================================
# 状态管理
# ============================================================

def get_position_file(symbol):
    return os.path.join(DATA_DIR, f"{symbol.lower()}_evening_pos.json")

def load_position_state(symbol):
    pos_file = get_position_file(symbol)
    if os.path.exists(pos_file):
        with open(pos_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"symbol": symbol, "has_position": False, "buy_date": None, "buy_price": None,
            "buy_qty": None, "buy_order_id": None, "hold_days": 0,
            "last_sell_date": None, "last_sell_price": None}

def save_position_state(state, symbol):
    with open(get_position_file(symbol), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_trades_log(symbol):
    return os.path.join(LOGS_DIR, f"{symbol.lower()}_evening_trades.jsonl")

def log_trade(symbol, action, price, qty, reason=""):
    cfg = get_symbol_config(symbol)
    trade_log = get_trades_log(symbol)
    record = {"timestamp": datetime.now().isoformat(), "symbol": symbol,
              "name": cfg.get("name", symbol), "action": action,
              "price": price, "qty": qty, "reason": reason}
    with open(trade_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[日志] {action} {symbol} x{qty} @ {price}, 原因: {reason}")

# ============================================================
# 买入逻辑
# ============================================================

def buy_all():
    symbols = get_enabled_symbols()
    results = []
    print(f"[尾盘买入] 执行中 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 标的: {symbols}")
    for symbol in symbols:
        cfg = get_symbol_config(symbol)
        api = get_tiger_api(cfg)
        state = load_position_state(symbol)
        if state.get("has_position"):
            print(f"[跳过] {symbol} 已有持仓（{state.get('buy_date')}），跳过")
            results.append({"symbol": symbol, "action": "skip", "reason": "已有持仓"})
            continue
        quote = get_quote(symbol)
        if not quote:
            print(f"[行情] {symbol} 获取失败，跳过")
            results.append({"symbol": symbol, "action": "error", "reason": "行情获取失败"})
            continue
        current_price = quote.get("last_price", 0)
        prev_close = quote.get("prev_close", current_price)
        print(f"[行情] {symbol}: 现价=${current_price}, 昨收=${prev_close}")
        qty = cfg.get("trade_qty", 10)
        order_resp = place_market_order(api, ACCOUNT, symbol, qty, "BUY")
        if order_resp and order_resp.get("order_id"):
            buy_price = current_price * (1 + cfg.get("buy_slippage_pct", 0.005))
            state.update({"has_position": True, "buy_date": date.today().strftime("%Y-%m-%d"),
                          "buy_time": datetime.now().strftime("%H:%M:%S"),
                          "buy_price": buy_price, "buy_qty": qty,
                          "buy_order_id": order_resp.get("order_id")})
            save_position_state(state, symbol)
            log_trade(symbol, "BUY", buy_price, qty, "尾盘市价买入")
            send_trade_notification(symbol, "BUY", buy_price, qty, order_resp.get("order_id"), "尾盘市价买入")
            results.append({"symbol": symbol, "action": "buy", "price": buy_price, "qty": qty})
        else:
            print(f"[失败] {symbol} 买入订单失败")
            results.append({"symbol": symbol, "action": "error", "reason": "订单失败"})
    return results

# ============================================================
# 卖出逻辑
# ============================================================

def sell_all():
    symbols = get_enabled_symbols()
    results = []
    print(f"[尾盘卖出] 执行中 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 标的: {symbols}")
    for symbol in symbols:
        cfg = get_symbol_config(symbol)
        api = get_tiger_api(cfg)
        state = load_position_state(symbol)
        if not state.get("has_position"):
            print(f"[跳过] {symbol} 无持仓，跳过")
            results.append({"symbol": symbol, "action": "skip", "reason": "无持仓"})
            continue
        last_sell_date = state.get("last_sell_date", "")
        today_str = date.today().strftime("%Y-%m-%d")
        if last_sell_date == today_str:
            print(f"[跳过] {symbol} 今天已卖出，跳过")
            results.append({"symbol": symbol, "action": "skip", "reason": "今日已卖出"})
            continue
        positions = get_positions(api, ACCOUNT)
        real_pos = next((p for p in positions if p.get("symbol") == symbol), None)
        real_qty = int(real_pos.get("quantity", 0)) if real_pos else 0
        planned_qty = state.get("buy_qty", 0)
        print(f"[持仓] {symbol}: 实际={real_qty} 股，计划={planned_qty} 股")
        if real_qty <= 0:
            print(f"[跳过] {symbol} 账户无持仓，重置状态")
            state["has_position"] = False
            save_position_state(state, symbol)
            results.append({"symbol": symbol, "action": "skip", "reason": "账户无持仓"})
            continue
        if real_qty < planned_qty:
            print(f"[警告] {symbol} 持仓不足，调整为 {real_qty}")
            planned_qty = real_qty
        quote = get_quote(symbol)
        if not quote:
            print(f"[行情] {symbol} 获取失败，跳过")
            results.append({"symbol": symbol, "action": "error", "reason": "行情获取失败"})
            continue
        current_price = quote.get("last_price", 0)
        buy_price = state.get("buy_price", 0)
        qty = planned_qty
        print(f"[行情] {symbol}: 现价=${current_price}, 买入价=${buy_price}, 数量={qty}")
        if buy_price > 0:
            profit_pct = (current_price - buy_price) / buy_price * 100
            profit_amount = (current_price - buy_price) * qty
        else:
            profit_pct = 0
            profit_amount = 0
        buy_date = state.get("buy_date", "")
        if buy_date:
            buy_dt = datetime.strptime(buy_date, "%Y-%m-%d")
            hold_days = (datetime.now() - buy_dt).days
        else:
            hold_days = 0
        sell_reason = "尾盘定时卖出"
        order_resp = place_market_order(api, ACCOUNT, symbol, qty, "SELL")
        if order_resp and order_resp.get("order_id"):
            sell_price = current_price * (1 - cfg.get("sell_slippage_pct", 0.005))
            log_trade(symbol, "SELL", sell_price, qty, sell_reason)
            _archive_trade(symbol, state, sell_price, order_resp.get("order_id"), sell_reason)
            state.update({"has_position": False, "last_sell_date": today_str,
                          "last_sell_price": sell_price})
            save_position_state(state, symbol)
            send_profit_notification(symbol, buy_price, sell_price, qty,
                                    state.get("buy_date", ""), today_str, sell_reason)
            results.append({"symbol": symbol, "action": "sell",
                            "buy_price": buy_price, "sell_price": sell_price,
                            "qty": qty, "profit_pct": profit_pct})
        else:
            print(f"[失败] {symbol} 卖出订单失败")
            results.append({"symbol": symbol, "action": "error", "reason": "订单失败"})
    return results

def _archive_trade(symbol, state, sell_price, order_id, sell_reason=""):
    archive_file = os.path.join(DATA_DIR, f"{symbol.lower()}_evening_archive.jsonl")
    buy_price = state.get("buy_price", 0)
    qty = state.get("buy_qty", 0)
    profit_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    profit_amount = (sell_price - buy_price) * qty
    buy_date = state.get("buy_date", "")
    hold_days = (datetime.now() - datetime.strptime(buy_date, "%Y-%m-%d")).days if buy_date else 0
    is_profit = profit_amount >= 0
    record = {
        "symbol": symbol, "name": state.get("name", symbol),
        "buy_date": buy_date, "buy_time": state.get("buy_time", ""),
        "buy_price": buy_price, "buy_qty": qty, "buy_order_id": state.get("buy_order_id"),
        "sell_date": date.today().strftime("%Y-%m-%d"),
        "sell_time": datetime.now().strftime("%H:%M:%S"),
        "sell_price": sell_price, "sell_qty": qty, "sell_order_id": order_id,
        "hold_days": hold_days, "profit_pct": profit_pct, "profit_amount": profit_amount,
        "is_profit": is_profit,
        "profit_pct_display": f"+{profit_pct:.2f}%" if is_profit else f"{profit_pct:.2f}%",
        "profit_amount_display": f"+${profit_amount:.2f}" if is_profit else f"-${abs(profit_amount):.2f}",
        "sell_reason": sell_reason, "closed": True
    }
    with open(archive_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[归档] {symbol} -> {archive_file}")

# ============================================================
# 状态查询
# ============================================================

def show_status():
    symbols = get_enabled_symbols()
    print(f"\n{'='*60}")
    print(f"美股尾盘策略状态 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    for symbol in symbols:
        cfg = get_symbol_config(symbol)
        state = load_position_state(symbol)
        print(f"\n[{symbol}] {cfg.get('name', symbol)}")
        print(f"  配置数量: {cfg.get('trade_qty', 10)} 股")
        print(f"  持仓状态: {'有持仓' if state.get('has_position') else '无持仓'}")
        if state.get("has_position"):
            buy_price = state.get("buy_price", 0)
            buy_date = state.get("buy_date", "")
            quote = get_quote(symbol)
            current_price = quote.get("last_price", 0) if quote else 0
            hold_days = (datetime.now() - datetime.strptime(buy_date, "%Y-%m-%d")).days if buy_date else 0
            if buy_price > 0 and current_price > 0:
                profit_pct = (current_price - buy_price) / buy_price * 100
                profit_amount = (current_price - buy_price) * state.get("buy_qty", 0)
                emoji = "🟢" if profit_pct >= 0 else "🔴"
            else:
                profit_pct = 0
                profit_amount = 0
                emoji = "⚪"
            print(f"  买入日期: {buy_date} (持仓 {hold_days} 天)")
            print(f"  买入价: ${buy_price:.2f}")
            print(f"  当前价: ${current_price:.2f}")
            print(f"  盈亏: {emoji} ${profit_amount:.2f} ({profit_pct:+.2f}%)")
    print(f"\n{'='*60}")

# ============================================================
# 主入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n可用参数:")
        print("  --buy     执行尾盘买入（凌晨3:55）")
        print("  --sell    执行尾盘卖出（21:35）")
        print("  --status  查看持仓状态")
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "--buy":
        results = buy_all()
        print(f"\n[完成] 买入完成，处理 {len(results)} 个标的")
    elif cmd == "--sell":
        results = sell_all()
        print(f"\n[完成] 卖出完成，处理 {len(results)} 个标的")
    elif cmd == "--status":
        show_status()
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
