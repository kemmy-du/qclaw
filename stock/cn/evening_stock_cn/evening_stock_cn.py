"""
尾盘交易策略 - A股
T+1 机制：
  - 信号日(Day0) 14:50 触发买入信号，记录信号日期
  - 下一交易日(Day1) 14:50-15:00 执行买入（价差买入）
  - 下下一交易日(Day2) 09:25-09:30 执行卖出（早盘卖出）

用法:
  python evening_stock_cn.py --signal    # 买入信号（14:50执行）
  python evening_stock_cn.py --buy       # 执行买入（Day1 14:50-15:00）
  python evening_stock_cn.py --sell      # 执行卖出（Day2 09:25-09:30）
  python evening_stock_cn.py --status    # 查看状态
"""

import sys
import os
import json
from datetime import datetime, date, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd

# 添加父目录到路径以引用 cn_sim_account
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = _SCRIPT_DIR
sys.path.insert(0, _PARENT_DIR)

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
    cfg.setdefault("feishu_webhook", global_defaults.get("feishu_webhook", ""))
    cfg.setdefault("send_to_feishu", global_defaults.get("send_to_feishu", False))
    notify_cfg = global_defaults.get("notification", {})
    strategy_notify = cfg.get("notification", {})
    channels = strategy_notify.get("channels") or notify_cfg.get("channels") or ["feishu"]
    cfg["_notification_config"] = _create_notif_config(
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
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ============================================================
# 通知（简化版，复制通知逻辑）
# ============================================================

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/89a829de-fc60-4a7c-ade0-e4a422e9434b"

def _create_notif_config(webhook=None, enabled=True, channels=None, weixin_target=None):
    class NotifConfig:
        def __init__(self):
            self.enabled = enabled
            self.channels = channels or ["feishu"]
            self.weixin_target = weixin_target or "o9cq80-aiozlTjCmF5CjVtM5Mhyw@im.wechat"
    return NotifConfig()

class _FeishuCardBuilder:
    def __init__(self, title="", color="blue"):
        self.title = title
        color_map = {"green": "0", "red": "1", "yellow": "2", "blue": "3", "purple": "4", "gray": "5", "orange": "6"}
        self.header = {"title": {"tag": "plain_text", "content": title}, "template": color_map.get(color, "3")} if title else None
        self.elements = []
    def add_key_value(self, key, value):
        self.elements.append({"tag": "markdown", "content": f"**{key}**: {value}"})
        return self
    def add_divider(self):
        self.elements.append({"tag": "hr"})
        return self
    def add_note(self, text):
        self.elements.append({"tag": "markdown", "content": f"<note>{text}</note>"})
        return self
    def add_markdown(self, text):
        self.elements.append({"tag": "markdown", "content": text})
        return self
    def build(self):
        card = {}
        if self.header:
            card["header"] = self.header
        card["elements"] = self.elements
        return card

def _send_card(card, enabled=True, channels=None):
    if not enabled:
        return False
    channels = channels or ["feishu"]
    if "feishu" in channels:
        try:
            import requests
            resp = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            print(f"[通知] 飞书失败: {e}")
    return False

STRATEGY_NAME = "A股尾盘策略"

def _notif_kwargs(notif_cfg):
    return {"enabled": notif_cfg.enabled if notif_cfg else False,
            "channels": notif_cfg.channels if notif_cfg else None}

def send_trade_notification(symbol, action, price, qty, order_id="", reason=""):
    cfg = get_symbol_config(symbol)
    notif_cfg = cfg.get("_notification_config")
    action_text = "买入" if action == "BUY" else "卖出"
    color = "green" if action == "BUY" else "red"
    name = cfg.get("name", symbol)
    builder = _FeishuCardBuilder(title=f"[{STRATEGY_NAME}] {action_text} - {symbol} ({name})", color=color)
    builder.add_key_value("交易方向", f"**{action_text}**")
    builder.add_key_value("成交价格", f"`{price:.3f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    if order_id:
        builder.add_key_value("订单ID", f"`{order_id}`")
    if reason:
        builder.add_key_value("原因", reason)
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {STRATEGY_NAME} | 自动通知")
    return _send_card(builder.build(), **_notif_kwargs(notif_cfg))

def send_profit_notification(symbol, buy_price, sell_price, qty, buy_date="", sell_date="", sell_reason=""):
    cfg = get_symbol_config(symbol)
    notif_cfg = cfg.get("_notification_config")
    name = cfg.get("name", symbol)
    profit_amount = (sell_price - buy_price) * qty
    profit_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    is_profit = profit_amount >= 0
    color = "green" if is_profit else "red"
    emoji = "🟢" if is_profit else "🔴"
    builder = _FeishuCardBuilder(title=f"[{STRATEGY_NAME}] 卖出 - {symbol} ({name})", color=color)
    builder.add_markdown(f"{emoji} **盈亏: `{profit_amount:.2f}` ({profit_pct:+.2f}%)**")
    builder.add_divider()
    if buy_date:
        builder.add_key_value("买入日期", buy_date)
    if sell_date:
        builder.add_key_value("卖出日期", sell_date)
    builder.add_key_value("买入价", f"`{buy_price:.3f}`")
    builder.add_key_value("卖出价", f"`{sell_price:.3f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    builder.add_key_value("持仓盈亏", f"{emoji} `{profit_amount:.2f}`")
    if sell_reason:
        builder.add_key_value("卖出原因", sell_reason)
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {STRATEGY_NAME} | 自动通知")
    return _send_card(builder.build(), **_notif_kwargs(notif_cfg))

# ============================================================
# A股模拟账户
# ============================================================

def _load_sim_account():
    """加载模拟账户状态"""
    account_file = os.path.join(os.path.dirname(__file__), "cn_sim_account.json")
    if os.path.exists(account_file):
        with open(account_file, "r", encoding="utf-8") as f:
            return json.load(f)
    # 默认模拟账户
    return {
        "cash": 100000.0,
        "positions": {},
        "trades": [],
        "initial_cash": 100000.0
    }

def _save_sim_account(acct):
    account_file = os.path.join(os.path.dirname(__file__), "cn_sim_account.json")
    with open(account_file, "w", encoding="utf-8") as f:
        json.dump(acct, f, ensure_ascii=False, indent=2)

def _sim_buy(symbol, qty, price):
    """模拟账户买入"""
    acct = _load_sim_account()
    cost = price * qty * 1.0003  # 万3手续费
    if acct["cash"] < cost:
        print(f"[模拟买入失败] 资金不足: 需要 {cost:.2f}, 可用 {acct['cash']:.2f}")
        return None
    acct["cash"] -= cost
    if symbol in acct["positions"]:
        pos = acct["positions"][symbol]
        total_qty = pos["qty"] + qty
        pos["avg_cost"] = (pos["avg_cost"] * pos["qty"] + price * qty) / total_qty
        pos["qty"] = total_qty
    else:
        acct["positions"][symbol] = {"qty": qty, "avg_cost": price}
    trade_record = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol, "action": "BUY", "price": price,
        "qty": qty, "amount": cost, "cash": acct["cash"]
    }
    acct["trades"].append(trade_record)
    _save_sim_account(acct)
    print(f"[模拟买入] {symbol} x{qty} @ {price:.3f}, 花费 {cost:.2f}, 剩余 {acct['cash']:.2f}")
    return {"order_id": f"sim_{datetime.now().strftime('%Y%m%d%H%M%S')}", "trade_record": trade_record}

def _sim_sell(symbol, qty, price):
    """模拟账户卖出"""
    acct = _load_sim_account()
    if symbol not in acct["positions"]:
        print(f"[模拟卖出失败] 无持仓: {symbol}")
        return None
    pos = acct["positions"][symbol]
    if pos["qty"] < qty:
        print(f"[模拟卖出失败] 持仓不足: 持有{pos['qty']}股, 卖出{qty}股")
        return None
    revenue = price * qty * 0.9997  # 扣万3手续费
    avg_cost = pos["avg_cost"]
    profit = (price - avg_cost) * qty
    acct["cash"] += revenue
    pos["qty"] -= qty
    if pos["qty"] == 0:
        del acct["positions"][symbol]
    trade_record = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol, "action": "SELL", "price": price,
        "qty": qty, "amount": revenue, "profit": profit, "cash": acct["cash"]
    }
    acct["trades"].append(trade_record)
    _save_sim_account(acct)
    print(f"[模拟卖出] {symbol} x{qty} @ {price:.3f}, 收益 {revenue:.2f}, 盈利 {profit:.2f}, 剩余 {acct['cash']:.2f}")
    return {"order_id": f"sim_{datetime.now().strftime('%Y%m%d%H%M%S')}", "trade_record": trade_record}

# ============================================================
# 行情数据（东方财富）
# ============================================================

def get_quote(symbol: str):
    """获取A股实时行情（东方财富）"""
    try:
        import requests
        # 东方财富实时行情 API
        url = f"http://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": f"1.{symbol}" if not symbol.startswith("6") else f"0.{symbol}",
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
        return {
            "symbol": symbol,
            "last_price": float(stock_data.get("f43", 0)) / 100 if stock_data.get("f43") else 0,
            "prev_close": float(stock_data.get("f50", 0)) / 100 if stock_data.get("f50") else 0,
            "name": stock_data.get("f58", symbol),
            "currency": "CNY",
            "market": "CN"
        }
    except Exception as e:
        print(f"[行情] {symbol} 获取失败: {e}")
    return None

# ============================================================
# 状态管理
# ============================================================

def get_position_file(symbol):
    return os.path.join(DATA_DIR, f"{symbol}_evening_pos.json")

def load_position_state(symbol):
    pos_file = get_position_file(symbol)
    if os.path.exists(pos_file):
        with open(pos_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"symbol": symbol, "phase": "idle",
            "signal_date": None, "signal_price": None,
            "buy_date": None, "buy_price": None, "buy_qty": None, "buy_order_id": None,
            "hold_days": 0, "last_sell_date": None, "last_sell_price": None}

def save_position_state(state, symbol):
    with open(get_position_file(symbol), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_trades_log(symbol):
    return os.path.join(LOGS_DIR, f"{symbol}_evening_trades.jsonl")

def log_trade(symbol, action, price, qty, reason=""):
    cfg = get_symbol_config(symbol)
    trade_log = get_trades_log(symbol)
    record = {"timestamp": datetime.now().isoformat(), "symbol": symbol,
              "name": cfg.get("name", symbol), "action": action,
              "price": price, "qty": qty, "reason": reason}
    with open(trade_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[日志] {action} {symbol} x{qty} @ {price:.3f}, 原因: {reason}")

# ============================================================
# 买入信号（Day0 尾盘）
# ============================================================

def trigger_signal():
    """触发买入信号（14:50尾盘）"""
    symbols = get_enabled_symbols()
    results = []
    print(f"[买入信号] 执行中 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 标的: {symbols}")
    for symbol in symbols:
        state = load_position_state(symbol)
        if state.get("phase") not in ("idle",):
            print(f"[跳过] {symbol} 当前阶段={state.get('phase')}，非空闲状态，跳过")
            results.append({"symbol": symbol, "action": "skip", "reason": f"阶段={state.get('phase')}"})
            continue
        quote = get_quote(symbol)
        if not quote:
            print(f"[行情] {symbol} 获取失败，跳过")
            results.append({"symbol": symbol, "action": "error", "reason": "行情获取失败"})
            continue
        current_price = quote.get("last_price", 0)
        print(f"[信号] {symbol}: 现价={current_price:.3f}")
        # 记录信号
        state.update({"phase": "signal_sent", "signal_date": date.today().strftime("%Y-%m-%d"),
                       "signal_price": current_price})
        save_position_state(state, symbol)
        results.append({"symbol": symbol, "action": "signal", "price": current_price})
        print(f"[信号] {symbol} 买入信号已记录，信号日期={state['signal_date']}，信号价={current_price:.3f}")
    return results

# ============================================================
# 执行买入（Day1 14:50-15:00）
# ============================================================

def buy_all():
    """执行买入（仅对已发信号的标的）"""
    symbols = get_enabled_symbols()
    results = []
    print(f"[尾盘买入] 执行中 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 标的: {symbols}")
    for symbol in symbols:
        state = load_position_state(symbol)
        if state.get("phase") != "signal_sent":
            print(f"[跳过] {symbol} 阶段={state.get('phase')}，非待买入状态，跳过")
            results.append({"symbol": symbol, "action": "skip", "reason": f"阶段={state.get('phase')}"})
            continue
        if state.get("buy_date"):
            print(f"[跳过] {symbol} 已买入（{state.get('buy_date')}），跳过")
            results.append({"symbol": symbol, "action": "skip", "reason": "已买入"})
            continue
        cfg = get_symbol_config(symbol)
        quote = get_quote(symbol)
        if not quote:
            print(f"[行情] {symbol} 获取失败，跳过")
            results.append({"symbol": symbol, "action": "error", "reason": "行情获取失败"})
            continue
        # 使用信号价与现价的均值作为执行价（简化）
        signal_price = state.get("signal_price", 0)
        current_price = quote.get("last_price", 0)
        exec_price = (signal_price + current_price) / 2 if signal_price > 0 else current_price
        qty = cfg.get("trade_qty", 100)
        print(f"[买入] {symbol}: 信号价={signal_price:.3f}, 现价={current_price:.3f}, 执行价={exec_price:.3f}, 数量={qty}")
        order_resp = _sim_buy(symbol, qty, exec_price)
        if order_resp:
            state.update({"phase": "bought", "buy_date": date.today().strftime("%Y-%m-%d"),
                          "buy_time": datetime.now().strftime("%H:%M:%S"),
                          "buy_price": exec_price, "buy_qty": qty,
                          "buy_order_id": order_resp.get("order_id")})
            save_position_state(state, symbol)
            log_trade(symbol, "BUY", exec_price, qty, f"尾盘买入(信号日期={state.get('signal_date')})")
            send_trade_notification(symbol, "BUY", exec_price, qty, order_resp.get("order_id"),
                                   f"尾盘买入(信号日期={state.get('signal_date')})")
            results.append({"symbol": symbol, "action": "buy", "price": exec_price, "qty": qty})
        else:
            results.append({"symbol": symbol, "action": "error", "reason": "模拟账户失败"})
    return results

# ============================================================
# 执行卖出（Day2 早盘）
# ============================================================

def sell_all():
    """执行卖出"""
    symbols = get_enabled_symbols()
    results = []
    print(f"[早盘卖出] 执行中 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 标的: {symbols}")
    for symbol in symbols:
        state = load_position_state(symbol)
        if state.get("phase") != "bought":
            print(f"[跳过] {symbol} 阶段={state.get('phase')}，非持仓状态，跳过")
            results.append({"symbol": symbol, "action": "skip", "reason": f"阶段={state.get('phase')}"})
            continue
        last_sell_date = state.get("last_sell_date", "")
        today_str = date.today().strftime("%Y-%m-%d")
        if last_sell_date == today_str:
            print(f"[跳过] {symbol} 今天已卖出，跳过")
            results.append({"symbol": symbol, "action": "skip", "reason": "今日已卖出"})
            continue
        cfg = get_symbol_config(symbol)
        quote = get_quote(symbol)
        if not quote:
            print(f"[行情] {symbol} 获取失败，跳过")
            results.append({"symbol": symbol, "action": "error", "reason": "行情获取失败"})
            continue
        current_price = quote.get("last_price", 0)
        buy_price = state.get("buy_price", 0)
        qty = state.get("buy_qty", 0)
        print(f"[卖出] {symbol}: 现价={current_price:.3f}, 买入价={buy_price:.3f}, 数量={qty}")
        order_resp = _sim_sell(symbol, qty, current_price)
        if order_resp:
            sell_reason = "早盘定时卖出(T+1)"
            _archive_trade(symbol, state, current_price, order_resp.get("order_id"), sell_reason)
            state.update({"phase": "idle", "last_sell_date": today_str,
                          "last_sell_price": current_price})
            save_position_state(state, symbol)
            log_trade(symbol, "SELL", current_price, qty, sell_reason)
            send_profit_notification(symbol, buy_price, current_price, qty,
                                    state.get("buy_date", ""), today_str, sell_reason)
            results.append({"symbol": symbol, "action": "sell",
                            "buy_price": buy_price, "sell_price": current_price, "qty": qty})
        else:
            results.append({"symbol": symbol, "action": "error", "reason": "模拟账户失败"})
    return results

def _archive_trade(symbol, state, sell_price, order_id, sell_reason=""):
    archive_file = os.path.join(DATA_DIR, f"{symbol}_evening_archive.jsonl")
    buy_price = state.get("buy_price", 0)
    qty = state.get("buy_qty", 0)
    profit_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    profit_amount = (sell_price - buy_price) * qty
    buy_date = state.get("buy_date", "")
    hold_days = (datetime.now() - datetime.strptime(buy_date, "%Y-%m-%d")).days if buy_date else 0
    is_profit = profit_amount >= 0
    record = {
        "symbol": symbol, "name": state.get("name", symbol),
        "signal_date": state.get("signal_date"),
        "buy_date": buy_date, "buy_time": state.get("buy_time", ""),
        "buy_price": buy_price, "buy_qty": qty, "buy_order_id": state.get("buy_order_id"),
        "sell_date": date.today().strftime("%Y-%m-%d"),
        "sell_time": datetime.now().strftime("%H:%M:%S"),
        "sell_price": sell_price, "sell_qty": qty, "sell_order_id": order_id,
        "hold_days": hold_days, "profit_pct": profit_pct, "profit_amount": profit_amount,
        "is_profit": is_profit,
        "profit_pct_display": f"+{profit_pct:.2f}%" if is_profit else f"{profit_pct:.2f}%",
        "profit_amount_display": f"+¥{profit_amount:.2f}" if is_profit else f"-¥{abs(profit_amount):.2f}",
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
    print(f"A股尾盘策略状态 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    acct = _load_sim_account()
    print(f"\n模拟账户: 现金 ¥{acct['cash']:.2f}")
    if acct["positions"]:
        print("  持仓:")
        for sym, pos in acct["positions"].items():
            print(f"    {sym}: {pos['qty']}股, 成本价 {pos['avg_cost']:.3f}")
    print()
    for symbol in symbols:
        cfg = get_symbol_config(symbol)
        state = load_position_state(symbol)
        phase_text = {"idle": "空闲", "signal_sent": "待买入", "bought": "已买入"}.get(state.get("phase"), state.get("phase"))
        print(f"[{symbol}] {cfg.get('name', symbol)} | 阶段: {phase_text}")
        if state.get("signal_date"):
            print(f"  信号日期: {state['signal_date']} | 信号价: {state.get('signal_price', 0):.3f}")
        if state.get("buy_date"):
            print(f"  买入日期: {state['buy_date']} | 买入价: {state['buy_price']:.3f} | 数量: {state['buy_qty']}")
            quote = get_quote(symbol)
            current_price = quote.get("last_price", 0) if quote else 0
            if current_price > 0 and state.get("buy_price", 0) > 0:
                profit_pct = (current_price - state["buy_price"]) / state["buy_price"] * 100
                emoji = "🟢" if profit_pct >= 0 else "🔴"
                print(f"  当前价: {current_price:.3f} | 盈亏: {emoji} {profit_pct:+.2f}%")
    print(f"\n{'='*60}")

# ============================================================
# 主入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n可用参数:")
        print("  --signal   买入信号（Day0 14:50，尾盘触发）")
        print("  --buy      执行买入（Day1 14:50-15:00）")
        print("  --sell     执行卖出（Day2 09:25-09:30）")
        print("  --status   查看状态")
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "--signal":
        results = trigger_signal()
        print(f"\n[完成] 信号触发完成，处理 {len(results)} 个标的")
    elif cmd == "--buy":
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
