"""
股票定投策略 - 重构版本

支持通过配置文件（config.json）配置任意股票的定投策略。
使用通用行情数据源和通知模块。

用法:
  python stock_t.py --symbol=LITE --init          # 初始化底仓
  python stock_t.py --symbol=LITE --buy-check     # 买入检查
  python stock_t.py --symbol=LITE --sell-check    # 卖出检查
  python stock_t.py --symbol=LITE --sync          # 订单同步
  python stock_t.py --symbol=LITE --status        # 查看状态

A股使用本地模拟账户，美股使用老虎证券。
"""

import sys
import os
import json
import time
import shutil
from datetime import datetime, timedelta, date

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd

# ============================================================
# 导入 US common 模块
# ============================================================
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import market_data_us as market_data
from common import notification_us as notification

# ============================================================
# 配置加载
# ============================================================

def get_symbol_from_args():
    for arg in sys.argv:
        if arg.startswith("--symbol="):
            return arg.split("=", 1)[1].upper()
    return None

def is_hang_all_mode():
    """检查是否是 --hang-all 模式（批量处理所有股票）"""
    for arg in sys.argv:
        if arg == "--hang-all":
            return True
    return False

def get_market_filter():
    """获取 --market 过滤参数（CN/US），None表示不过滤"""
    for arg in sys.argv:
        if arg.startswith("--market="):
            return arg.split("=", 1)[1].upper()
    return None

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
    if "account" not in cfg:
        cfg["account"] = global_defaults.get("account", "")
    if "tiger_config_path" not in cfg:
        cfg["tiger_config_path"] = global_defaults.get("tiger_config_path", "")
    if "feishu_webhook" not in cfg:
        cfg["feishu_webhook"] = global_defaults.get("feishu_webhook", "")

    # 通知渠道配置（支持 feishu / weixin / 两者同时）
    notify_cfg = config.get("global_defaults", {}).get("notification", {})
    strategy_notify = cfg.get("notification", {})
    channels = strategy_notify.get("channels") or notify_cfg.get("channels") or ["feishu"]

    cfg["_notification_config"] = notification.create_config(
        webhook=cfg.get("feishu_webhook"),
        enabled=config.get("global_defaults", {}).get("send_to_feishu", True),
        channels=channels,
        weixin_target=strategy_notify.get("weixin_target") or notify_cfg.get("weixin_target"),
        weixin_account_id=strategy_notify.get("weixin_account_id") or notify_cfg.get("weixin_account_id")
    )
    return cfg

SYMBOL = get_symbol_from_args()
# --hang-all 模式不需要 --symbol 参数
if not SYMBOL and not is_hang_all_mode():
    print("错误: 请指定股票代码，例如 --symbol=LITE")
    sys.exit(1)

CONFIG = get_symbol_config(SYMBOL) if SYMBOL else load_config()
MARKET = CONFIG.get("market", "US") if CONFIG else "US"
# 从 global_defaults 获取 account
GLOBAL_DEFAULTS = CONFIG.get("global_defaults", {}) if isinstance(CONFIG, dict) else {}
ACCOUNT = CONFIG.get("account", "") or GLOBAL_DEFAULTS.get("account", "")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
ARCHIVE_DIR = os.path.join(LOGS_DIR, "archive")

STATE_FILE = None
DAILY_OP_FILE = None
TRADES_LOG = None
ARCHIVE_FILE = None

def get_state_file(symbol):
    return os.path.join(DATA_DIR, f"{symbol.lower()}_state.json")

def get_daily_op_file(symbol):
    return os.path.join(DATA_DIR, f"{symbol.lower()}_daily_op.json")

def get_trades_log(symbol):
    return os.path.join(LOGS_DIR, f"{symbol.lower()}_trades.jsonl")

def get_archive_file(symbol):
    return os.path.join(DATA_DIR, f"{symbol.lower()}_archive.jsonl")

# ============================================================
# 通知（使用通用模块）
# ============================================================

STRATEGY_NAME = "定投策略"

def _notif_kwargs(notif_cfg):
    """提取通知渠道参数"""
    return {
        "enabled": notif_cfg.enabled if notif_cfg else False,
        "channels": notif_cfg.channels if notif_cfg else None
    }

def send_feishu(text, title=None, color="blue", symbol=None):
    """发送通知（支持多渠道）"""
    sym = symbol or SYMBOL
    cfg = get_symbol_config(sym) if sym else CONFIG
    notif_cfg = cfg.get("_notification_config")

    card = notification.build_status_card(
        title=f"[{STRATEGY_NAME}] {title or sym + ' 策略通知'}",
        content=text,
        color=color
    )

    if notif_cfg:
        return notification.send_card(card, **_notif_kwargs(notif_cfg))
    return notification.send_card(card, enabled=False)

def send_trade_notification(symbol, action, price, qty, order_id="", reason="", extra_info=None):
    """发送交易通知（支持多渠道）"""
    cfg = get_symbol_config(symbol)
    notif_cfg = cfg.get("_notification_config")

    action_text = "买入" if action == "BUY" else "卖出"
    color = "green" if action == "BUY" else "red"
    name = cfg.get("name", symbol)

    builder = notification.FeishuCardBuilder(title=f"[{STRATEGY_NAME}] {action_text} - {symbol} ({name})", color=color)
    builder.add_key_value("交易方向", f"**{action_text}**")
    builder.add_key_value("成交价格", f"`${price:.2f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    builder.add_key_value("订单ID", f"`{order_id or 'N/A'}`")
    if extra_info:
        builder.add_divider()
        for k, v in extra_info.items():
            builder.add_key_value(str(k), str(v))
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {STRATEGY_NAME} | 自动通知")

    return notification.send_card(builder.build(), **_notif_kwargs(notif_cfg))

def send_status_notification(symbol, content, color="blue"):
    """发送状态通知（支持多渠道）"""
    cfg = get_symbol_config(symbol)
    notif_cfg = cfg.get("_notification_config")

    card = notification.build_status_card(
        title=f"[{STRATEGY_NAME}] {symbol} 提醒",
        content=content,
        color=color
    )

    return notification.send_card(card, **_notif_kwargs(notif_cfg))

def send_profit_notification(symbol, buy_price, sell_price, qty, buy_date="", sell_date=""):
    """发送盈亏通知（支持多渠道）"""
    cfg = get_symbol_config(symbol)
    notif_cfg = cfg.get("_notification_config")

    name = cfg.get("name", symbol)
    profit_amount = (sell_price - buy_price) * qty
    profit_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    is_profit = profit_amount >= 0
    color = "green" if is_profit else "red"
    emoji = "🟢" if is_profit else "🔴"

    builder = notification.FeishuCardBuilder(title=f"[{STRATEGY_NAME}] 卖出 - {symbol} ({name})", color=color)
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
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {STRATEGY_NAME} | 自动通知")

    return notification.send_card(builder.build(), **_notif_kwargs(notif_cfg))

# ============================================================
# 状态管理
# ============================================================

def load_state(symbol=None):
    sym = symbol or SYMBOL
    state_file = get_state_file(sym)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    if os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
            state.setdefault("base_established", False)
            state.setdefault("base_qty", 0)
            state.setdefault("batches", [])
            state.setdefault("batch_counter", 0)
            state.setdefault("pending_orders", [])
            state.setdefault("hang_order_id", None)
            state.setdefault("hang_order_date", None)
            state.setdefault("last_ema_high_sell_price", None)
            state.setdefault("cleared_date", None)
            for b in state.get("batches", []):
                if "trade_count" not in b:
                    b["trade_count"] = 0
            return state
    return {
        "base_established": False, "base_qty": 0, "batches": [], "batch_counter": 0,
        "pending_orders": [], "hang_order_id": None, "hang_order_date": None, "last_ema_high_sell_price": None,
        "cleared_date": None
    }

def save_state(state, symbol=None):
    sym = symbol or SYMBOL
    state_file = get_state_file(sym)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_daily_op():
    if SYMBOL:
        return load_daily_op_by_symbol(SYMBOL)
    today_str = date.today().strftime("%Y-%m-%d")
    return {"date": today_str, "sold": False, "bought": False, "op_count": 0, "buy_count": 0, "sell_count": 0}

def load_daily_op_by_symbol(symbol):
    daily_file = get_daily_op_file(symbol)
    today_str = date.today().strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(daily_file), exist_ok=True)
    if os.path.exists(daily_file):
        with open(daily_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("date") == today_str:
                return data
    return {"date": today_str, "sold": False, "bought": False, "op_count": 0, "buy_count": 0, "sell_count": 0}

def save_daily_op(data):
    if SYMBOL:
        save_daily_op_by_symbol(data, SYMBOL)

def save_daily_op_by_symbol(data, symbol):
    daily_file = get_daily_op_file(symbol)
    os.makedirs(os.path.dirname(daily_file), exist_ok=True)
    with open(daily_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_trade(action, price, qty, reason="", order_id="", batch_id=None):
    if SYMBOL:
        log_trade_by_symbol(action, price, qty, reason, order_id, batch_id, SYMBOL)

def log_trade_by_symbol(action, price, qty, reason, order_id, batch_id, symbol):
    trade_log = get_trades_log(symbol)
    cfg = get_symbol_config(symbol)
    os.makedirs(os.path.dirname(trade_log), exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(), "action": action, "symbol": symbol,
        "name": cfg.get("name", symbol), "price": price, "qty": qty,
        "reason": reason, "order_id": order_id, "batch_id": batch_id
    }
    with open(trade_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def update_config_base_position(symbol, new_base_qty):
    """同步更新 config.json 中的 base_position"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            full_config = json.load(f)
        if symbol in full_config.get("symbol_configs", {}):
            old_val = full_config["symbol_configs"][symbol].get("base_position", 0)
            full_config["symbol_configs"][symbol]["base_position"] = new_base_qty
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(full_config, f, ensure_ascii=False, indent=2)
            print(f"[底仓] {symbol} base_position: {old_val} -> {new_base_qty}")
            return True
    except Exception as e:
        print(f"[底仓] {symbol} 更新配置失败: {e}")
    return False

# ============================================================
# 清仓归档
# ============================================================

def archive_on_clear(state):
    sym = SYMBOL or "unknown"
    today_str = date.today().strftime("%Y-%m-%d")
    trades_log = get_trades_log(sym)

    if os.path.exists(trades_log):
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        archive_log = os.path.join(ARCHIVE_DIR, f"{sym.lower()}_trades_{today_str}.jsonl")
        shutil.move(trades_log, archive_log)
        print(f"[归档] 交易日志 -> {archive_log}")

    archive_records = []
    for b in state.get("batches", []):
        if b.get("status") == "sold":
            archive_records.append({
                "batch_id": b.get("id"), "buy_date": b.get("buy_date"), "buy_price": b.get("buy_price"),
                "qty": b.get("qty"), "sell_date": b.get("sell_date"), "sell_price": b.get("sell_price"),
                "profit_pct": b.get("profit_pct"), "signal": b.get("signal"), "archive_date": today_str
            })

    archive_file = get_archive_file(sym)
    if archive_records:
        os.makedirs(os.path.dirname(archive_file), exist_ok=True)
        with open(archive_file, "a", encoding="utf-8") as f:
            for r in archive_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[归档] 买卖记录 {len(archive_records)} 条 -> {archive_file}")

# ============================================================
# 行情数据（使用通用模块）
# ============================================================

def get_quote(symbol):
    """获取实时报价（使用通用行情模块）"""
    return market_data.get_quote(symbol)

def get_kline(symbol, days=60):
    """获取K线数据（使用通用行情模块）"""
    return market_data.get_kline(symbol, days=days)

def calc_ema(df, period):
    """计算EMA"""
    return market_data.calculate_ema(df, period=period)

# ============================================================
# 老虎证券交易
# ============================================================

def get_tiger_api(symbol_cfg=None):
    """获取老虎证券API实例"""
    try:
        import logging
        from tigeropen.trade.trade_client import TradeClient
        from tigeropen.tiger_open_config import TigerOpenClientConfig
        cfg = symbol_cfg or CONFIG
        config_path = cfg.get("tiger_config_path", "")
        if not config_path or not os.path.exists(config_path):
            return None
        # 创建 logger
        logger = logging.getLogger('tigeropen')
        logger.setLevel(logging.WARNING)
        config = TigerOpenClientConfig(sandbox_debug=False, props_path=config_path)
        return TradeClient(config, logger=logger)
    except Exception as e:
        print(f"[老虎] API初始化失败: {e}")
        return None

def get_positions(api, account):
    """获取持仓"""
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

def place_order(api, account, symbol, qty, action, order_type="MKT", limit_price=None):
    """下单"""
    try:
        # 新版 API：先获取合约，再创建订单，最后下单
        contract = api.get_contract(symbol, "STK", currency="USD")
        if not contract:
            print(f"[下单] {symbol} 获取合约失败")
            return None

        # 映射订单类型
        order_type_map = {
            "0": "MKT",    # 市价
            "2": "LMT",    # 限价
            "MKT": "MKT",
            "LMT": "LMT",
            "STP": "STP",
            "STP_LMT": "STP_LMT",
            "TRAIL": "TRAIL",
            "TWAP": "TWAP",
            "VWAP": "VWAP",
            "AL": "AL",
            "AM": "AM"
        }
        order_type_normalized = order_type_map.get(order_type, order_type)

        # 创建订单
        if order_type_normalized == "MKT":
            order = api.create_order(account, contract, action, order_type_normalized, qty)
        else:
            # 限价单需要指定价格
            if limit_price is None:
                print(f"[下单] {symbol} 限价单需要指定价格")
                return None
            order = api.create_order(account, contract, action, order_type_normalized, qty, limit_price=limit_price)

        if not order:
            print(f"[下单] {action} {symbol} x{qty} 创建订单失败")
            return None

        # 下单
        order_id = api.place_order(order)
        if order_id:
            return {"order_id": order_id, "order": order}
    except Exception as e:
        print(f"[下单] {action} {symbol} x{qty} 失败: {e}")
    return None

# ============================================================
# 核心交易函数（美股）
# ============================================================

def get_positions_unified(symbol: str, cfg: Dict) -> List[Dict]:
    """获取持仓接口（美股：老虎证券）"""
    api = get_tiger_api(cfg)
    if api:
        return get_positions(api, ACCOUNT)
    return []

def place_buy_order(symbol: str, name: str, qty: int, price: float, reason: str, cfg: Dict) -> Dict:
    """
    买入接口（美股：老虎证券）

    Returns:
        {"success": True/False, "order_id": "...", "message": "..."}
    """
    api = get_tiger_api(cfg)
    if not api:
        return {"success": False, "message": "无法获取老虎API"}

    order_resp = place_order(api, ACCOUNT, symbol, qty, "BUY")
    if order_resp and order_resp.get("order_id"):
        return {
            "success": True,
            "order_id": order_resp.get("order_id"),
            "message": f"买入成功: {symbol} {qty}股"
        }
    return {"success": False, "message": "下单失败"}

def place_sell_order(symbol: str, name: str, qty: int, price: float, reason: str, cfg: Dict) -> Dict:
    """
    卖出接口（美股：老虎证券）

    Returns:
        {"success": True/False, "order_id": "...", "message": "...", "profit": ..., "profit_pct": ...}
    """
    api = get_tiger_api(cfg)
    if not api:
        return {"success": False, "message": "无法获取老虎API"}

    order_resp = place_order(api, ACCOUNT, symbol, qty, "SELL")
    if order_resp and order_resp.get("order_id"):
        return {
            "success": True,
            "order_id": order_resp.get("order_id"),
            "message": f"卖出成功: {symbol} {qty}股"
        }
    return {"success": False, "message": "下单失败"}

def get_prev_close(symbol):
    """获取前一交易日收盘价"""
    return market_data.get_prev_close(symbol)

def is_market_open():
    now = datetime.now()
    weekday = now.weekday()
    if weekday >= 5:
        return False
    current_time = now.time()
    market_open = datetime.strptime("09:30", "%H:%M").time()
    market_close = datetime.strptime("16:00", "%H:%M").time()
    return market_open <= current_time <= market_close

def promote_batches_to_base(symbol, state, cfg):
    """
    动态底仓逻辑：
    持仓超过 dynamic_base_days 天的加仓批次，自动升级为底仓。
    base_qty += 该批次股数，批次标记为 promoted，从浮动仓位转入底仓。
    """
    dynamic_days = cfg.get("dynamic_base_days", 0)
    if dynamic_days <= 0:
        return  # 未配置，不执行

    today = date.today()
    promoted_batches = []
    total_promoted = 0

    for batch in state.get("batches", []):
        if batch.get("status") != "holding":
            continue
        buy_date = datetime.strptime(batch.get("buy_date"), "%Y-%m-%d").date()
        hold_days = (today - buy_date).days
        if hold_days >= dynamic_days:
            batch_qty = batch.get("qty", 0)
            batch["status"] = "promoted"
            batch["promote_date"] = today.strftime("%Y-%m-%d")
            batch["promote_price"] = batch.get("buy_price", 0)
            promoted_batches.append(batch)
            total_promoted += batch_qty

    if total_promoted > 0:
        old_base = state.get("base_qty", 0)
        state["base_qty"] = old_base + total_promoted
        save_state(state, symbol)
        batch_ids = [b.get("id") for b in promoted_batches]
        print(f"[动态底仓] {symbol} 升级 {len(promoted_batches)} 个批次({'/'.join(map(str, batch_ids))}) 共{total_promoted}股 -> "
              f"base_qty: {old_base} -> {state['base_qty']}")

def do_buy_check(symbol, state, cfg):
    """
    买入检查
    - A股：使用模拟账户
    - 美股：使用老虎证券
    """
    print(f"\n[买入检查] {symbol} 开始检查...")

    # 清仓当日禁止交易
    cleared_date = state.get("cleared_date")
    today_str = date.today().strftime("%Y-%m-%d")
    if cleared_date and cleared_date == today_str:
        print(f"[买入检查] {symbol} 今日已清仓，禁止交易，次日方可重建底仓")
        return False

    daily_op = load_daily_op_by_symbol(symbol)
    if daily_op.get("buy_count", 0) >= cfg.get("max_buy_count", 2):
        print(f"[买入检查] {symbol} 今日买入次数已达上限")
        return False

    # 动态底仓：检查是否有批次持仓超期，自动升级为底仓
    promote_batches_to_base(symbol, state, cfg)

    api = get_tiger_api(cfg)
    if not api:
        print(f"[买入检查] {symbol} 无法获取老虎API")
        return False

    quote = get_quote(symbol)
    if not quote:
        print(f"[买入检查] {symbol} 无法获取行情")
        return False

    current_price = quote.get("last_price", 0)
    prev_close = quote.get("prev_close", current_price)

    print(f"[行情] {symbol}: 现价={current_price:.2f}, 昨收={prev_close:.2f}")

    # 检查是否启用交易
    trade_enabled = cfg.get("trade_enabled", True)
    watch_only = cfg.get("watch_only", False)

    kline = get_kline(symbol, days=cfg.get("kline_num", 60))
    if kline is None or len(kline) < cfg.get("ema_period", 13) + 5:
        print(f"[买入检查] {symbol} K线数据不足（可能停牌或数据延迟）")
        # 如果是仅监控模式，即使K线不足也发送行情提醒
        if not trade_enabled or watch_only:
            print(f"[监控] {symbol} 发送行情提醒...")
            market = "US"
            currency = "$"
            change_pct = (current_price - prev_close) / prev_close * 100 if prev_close > 0 else 0

            notif_content = f"""**【{symbol} 行情提醒】**

📈 市场: {market}
🏷️ 代码: `{symbol}`
💰 当前价格: `{currency}{current_price:.2f}`
📊 昨收价格: `{currency}{prev_close:.2f}`
📊 涨跌额: `{currency}{current_price - prev_close:.4f}`
📊 涨跌幅: `{change_pct:+.2f}%`

⚠️ K线数据暂不可用（可能停牌或延迟）

请人工判断交易时机！"""
            send_status_notification(symbol, notif_content, color="blue")
        return False

    kline['ema'] = calc_ema(kline, cfg.get("ema_period", 13))
    latest_ema = kline['ema'].iloc[-1]

    print(f"[EMA] {symbol}: 当前EMA={latest_ema:.2f}")

    # 计算信号
    signal = None
    signal_reason = ""

    # 1. EMA突破
    # 突破条件：
    #   1) 现价 >= EMA13
    #   2) 前M天收盘价全部 < EMA13
    #   3) 前N天内至少有1天收盘价 < EMA13×(1-参数)
    if not signal:
        breakout_all_lookback = cfg.get("ema_breakout_all_lookback", 10)  # M天
        breakout_lookback = cfg.get("ema_breakout_lookback", 5)  # N天
        breakout_threshold = cfg.get("ema_breakout_threshold", 0.03)  # 参数

        # 条件1: 现价 >= EMA13
        if current_price >= latest_ema:
            # 条件2: 前M天所有收盘价都 < EMA13
            all_below_ema = True
            m_check = 0
            for i in range(-breakout_all_lookback, 0):
                if -i <= len(kline):
                    if kline['close'].iloc[i] >= kline['ema'].iloc[i]:
                        all_below_ema = False
                        break
                    m_check += 1

            # 条件3: 前N天内至少有1天收盘价 < EMA13×(1-threshold)
            below_threshold_count = 0
            threshold_price = 0
            if all_below_ema and m_check > 0:
                for i in range(-breakout_lookback, 0):
                    if -i <= len(kline):
                        ema_val = kline['ema'].iloc[i]
                        close_val = kline['close'].iloc[i]
                        threshold_price = ema_val * (1 - breakout_threshold)
                        if close_val < threshold_price:
                            below_threshold_count += 1

            if all_below_ema and below_threshold_count > 0:
                signal = "ema_breakout"
                signal_reason = f"EMA突破，现价{current_price:.2f} >= EMA={latest_ema:.2f}，前{m_check}天均在EMA之下，前{breakout_lookback}天中{below_threshold_count}天低于EMA×(1-{breakout_threshold})={threshold_price:.2f}"

    # 2. EMA回踩
    # 回踩条件：
    #   1) 前M天内所有收盘价都在EMA13之上
    #   2) 回看前N天收盘价中有超过 EMA13×(1+百分比) 的价格
    #   3) 当前价格在 EMA×(1-low) ~ EMA×(1+high) 之间
    if not signal:
        pullback_high = cfg.get("ema_pullback_high_threshold", 0.03)
        pullback_low = cfg.get("ema_pullback_low_threshold", 0.03)
        pullback_all_above_lookback = cfg.get("ema_pullback_all_above_lookback", 10)  # M天：所有收盘价都需在EMA之上
        pullback_above_lookback = cfg.get("ema_pullback_above_lookback", 5)  # N天：检查是否有超过EMA×百分比的价格
        pullback_above_pct = cfg.get("ema_pullback_above_pct", 0.05)  # 超过EMA×(1+该比例)才算明显涨幅

        # 条件1: 检查前M天所有收盘价是否都在EMA之上
        all_above_ema = True
        m_check_count = 0
        for i in range(-pullback_all_above_lookback, 0):  # 不包含今天
            if -i <= len(kline):
                ema_val = kline['ema'].iloc[i]
                close_val = kline['close'].iloc[i]
                if close_val < ema_val:
                    all_above_ema = False
                    break
                m_check_count += 1

        # 条件2: 检查前N天是否有超过 EMA×(1+pullback_above_pct) 的价格
        above_threshold_count = 0
        threshold_price = 0
        if all_above_ema and m_check_count > 0:
            for i in range(-pullback_above_lookback, 0):
                if -i <= len(kline):
                    ema_val = kline['ema'].iloc[i]
                    close_val = kline['close'].iloc[i]
                    threshold_price = ema_val * (1 + pullback_above_pct)
                    if close_val > threshold_price:
                        above_threshold_count += 1

        if all_above_ema and above_threshold_count > 0:
            # 条件3: 当前价格在EMA附近
            if ema_val * (1 - pullback_low) <= current_price <= ema_val * (1 + pullback_high):
                signal = "ema_pullback"
                signal_reason = f"EMA回踩，现价{current_price:.2f}，EMA={ema_val:.2f}，前{m_check_count}天均在EMA之上，前{pullback_above_lookback}天中{above_threshold_count}天超过EMA×(1+{pullback_above_pct})={threshold_price:.2f}"

    # 3. EMA超跌 → 直接买入
    if not signal:
        oversold_mult = cfg.get("ema_oversold_multiplier", 0.2)
        if current_price <= latest_ema * (1 - oversold_mult):
            signal = "ema_oversold"
            signal_reason = f"EMA超跌，现价{current_price:.2f}<=EMA×(1-{oversold_mult})，直接买入"

# 当日跌幅买入（合并 hang_drop_pct + buy_drop_pct，取较大值）
# 当日跌幅买入（合并 hang_drop_pct + buy_drop_pct，取较大值）
    # buy_drop_pct：跌幅买入阈值（由 buy_check 检查）
    # 二者合并，取跌幅更大者作为触发条件
    if not signal:
        hang_drop_pct = cfg.get("hang_drop_pct", 0.08)
        buy_drop_pct = cfg.get("buy_drop_pct", 0.08)
        drop_pct = max(hang_drop_pct, buy_drop_pct)
# 当日跌幅买入（合并 hang_drop_pct + buy_drop_pct，取较大值）

        if drop_pct > 0:
            trigger_price = prev_close * (1 - drop_pct)
            if current_price < trigger_price:
                ema_filter = cfg.get("buy_drop_ema_filter", False)
                ema_ok = True
                if ema_filter and signal not in ("ema_breakout", "ema_pullback"):
                    ema_ok = False
                if ema_ok:
                    signal = "daily_drop_buy"
                    filter_note = "（EMA信号确认）" if ema_filter else "（直接触发）"
                    signal_reason = (f"跌幅买入，现价${current_price:.2f}<昨收${prev_close:.2f}×{1-drop_pct:.2%}"
                                     f"=${trigger_price:.2f}（来源:{trigger_source}）{filter_note}")
                elif ema_filter and not ema_ok:
                    notif_content = f"""**【{symbol} 跌幅信号 - 等待EMA确认】**

🏷️ 代码: `{symbol}`
📊 市场: 美股
💰 当前价格: `${current_price:.2f}`
💰 昨收价格: `${prev_close:.2f}`
📊 触发条件: 昨收 × (1 - {drop_pct:.2%}) = `${trigger_price:.2f}`
📐 EMA13: `${latest_ema:.2f}`

⚠️ 跌幅已达标（现价 < ${trigger_price:.2f}），但 EMA 尚未突破/回踩确认，暂时观望。
如后续 EMA 信号确认，将触发买入。"""
                    send_status_notification(symbol, notif_content, color="orange")
                    print(f"[买入检查] {symbol} 跌幅达标（现价${current_price:.2f}<${trigger_price:.2f}），"
                          f"但EMA未确认，仅通知")

    if not signal:
        print(f"[买入检查] {symbol} 无买入信号")
        return False

    print(f"[信号] {symbol}: {signal} - {signal_reason}")

    # 检查是否启用交易
    trade_enabled = cfg.get("trade_enabled", True)
    watch_only = cfg.get("watch_only", False)

    # 如果是仅监控模式（不交易），发送通知后直接返回
    if not trade_enabled or watch_only:
        print(f"[监控] {symbol} 仅监控模式，发送买入信号通知...")
        market = "US"
        currency = "$"

        # 构建通知内容
        notif_content = f"""**【{symbol} 买入信号提醒】**

📈 市场: {market}
🏷️ 代码: `{symbol}`
📝 信号类型: **{signal}**
💰 当前价格: `{currency}{current_price:.2f}`
📊 昨收价格: `{currency}{prev_close:.2f}`
📐 EMA13: `{currency}{latest_ema:.2f}`

📋 信号详情:
{signal_reason}

⚠️ 当前为仅监控模式，不会自动下单。

请人工判断是否需要买入！"""

        # 发送飞书通知
        send_status_notification(symbol, notif_content, color="orange")
        return True

    # 检查持仓（使用统一接口）
    positions = get_positions_unified(symbol, cfg)
    sym_pos = None
    for pos in positions:
        if pos.get("symbol") == symbol:
            sym_pos = pos
            break

    current_qty = int(sym_pos.get("quantity", 0)) if sym_pos else 0
    base_position = cfg.get("base_position", 1)
    trade_qty = cfg.get("trade_qty", 1)

    print(f"[持仓] {symbol}: {current_qty} 股（底仓={base_position}）")

    buy_qty = 0
    if not state.get("base_established"):
        if current_qty < base_position:
            buy_qty = base_position - current_qty
            signal = "init_base"
            signal_reason = f"初始化底仓，买入{buy_qty}股"
        else:
            print(f"[买入检查] {symbol} 底仓已建立")
            state["base_established"] = True
            state["base_qty"] = current_qty
            save_state(state, symbol)
    else:
        if current_qty < state.get("base_qty", base_position):
            buy_qty = state.get("base_qty", base_position) - current_qty
        elif current_qty >= state.get("base_qty", base_position):
            buy_qty = trade_qty

    if buy_qty <= 0:
        print(f"[买入检查] {symbol} 无需买入")
        return False

    # 执行买入（使用统一接口）
    name = cfg.get("name", symbol)
    result = place_buy_order(symbol, name, buy_qty, current_price, signal_reason, cfg)

    if result.get("success"):
        order_id = result.get("order_id", "")
        print(f"[买入] {symbol} 订单已提交，ID: {order_id}")

        log_trade_by_symbol("BUY", current_price, buy_qty, signal_reason, order_id, None, symbol)

        # 记录加仓批次（用于动态底仓和短期止盈跟踪）
        # init_base 不进入 batches，直接更新 base_qty
        if signal != "init_base":
            batch_id = state.get("batch_counter", 0) + 1
            new_batch = {
                "id": batch_id,
                "buy_date": date.today().strftime("%Y-%m-%d"),
                "buy_price": current_price,
                "qty": buy_qty,
                "signal": signal,
                "status": "holding",
                "trade_count": 0
            }
            state.setdefault("batches", []).insert(0, new_batch)
            state["batch_counter"] = batch_id
            print(f"[批次] {symbol} 创建批次 #{batch_id}: {buy_qty}股@{current_price:.2f}, 信号={signal}")

        # 更新底仓状态
        if not state.get("base_established"):
            state["base_established"] = True
            state["base_qty"] = base_position  # init_base：直接设为底仓目标股数
        else:
            state["base_qty"] = state.get("base_qty", 0) + buy_qty  # 加仓批次：累加
        save_state(state, symbol)

        daily_op["buy_count"] = daily_op.get("buy_count", 0) + 1
        daily_op["op_count"] = daily_op.get("op_count", 0) + 1
        save_daily_op_by_symbol(daily_op, symbol)

        # 发送通知
        send_trade_notification(symbol, "BUY", current_price, buy_qty, order_id, signal_reason, {
            "signal": signal,
            "prev_close": prev_close,
            "ema": latest_ema
        })

        return True
    else:
        print(f"[买入] {symbol} 买入失败: {result.get('message', '未知错误')}")

    return False

def do_sell_check(symbol, state, cfg):
    """
    卖出检查
    - A股：使用模拟账户
    - 美股：使用老虎证券
    """
    print(f"\n[卖出检查] {symbol} 开始检查...")

    # 清仓当日禁止交易
    cleared_date = state.get("cleared_date")
    today_str = date.today().strftime("%Y-%m-%d")
    if cleared_date and cleared_date == today_str:
        print(f"[卖出检查] {symbol} 今日已清仓，禁止交易，次日方可重建底仓")
        return False

    daily_op = load_daily_op_by_symbol(symbol)
    if daily_op.get("sell_count", 0) >= cfg.get("max_sell_count", 2):
        print(f"[卖出检查] {symbol} 今日卖出次数已达上限")
        return False

    api = get_tiger_api(cfg)
    if not api:
        print(f"[卖出检查] {symbol} 无法获取老虎API")
        return False

    # 【前置持仓检查】使用统一接口获取持仓
    positions = get_positions_unified(symbol, cfg)
    sym_pos = None
    for pos in positions:
        if pos.get("symbol") == symbol:
            sym_pos = pos
            break

    current_qty = int(sym_pos.get("quantity", 0)) if sym_pos else 0
    base_qty = state.get("base_qty", cfg.get("base_position", 1))
    sellable_qty = current_qty - base_qty

    print(f"[持仓] {symbol}: 当前持仓={current_qty} 股，底仓={base_qty} 股，可卖出={sellable_qty} 股")

    if sellable_qty <= 0:
        print(f"[卖出检查] {symbol} 无可卖出股数，跳过")
        return False

    quote = get_quote(symbol)
    if not quote:
        print(f"[卖出检查] {symbol} 无法获取行情")
        return False

    current_price = quote.get("last_price", 0)

    print(f"[行情] {symbol}: 现价={current_price:.2f}")

    # 获取K线计算EMA
    kline = get_kline(symbol, days=cfg.get("kline_num", 60))
    if kline is None or len(kline) < cfg.get("ema_period", 13) + 5:
        print(f"[卖出检查] {symbol} K线数据不足")
        return False

    kline['ema'] = calc_ema(kline, cfg.get("ema_period", 13))
    latest_ema = kline['ema'].iloc[-1]
    ema_multiplier = cfg.get("ema_sell_high_multiplier", 0.2)

    print(f"[EMA] {symbol}: 当前EMA={latest_ema:.2f}, 卖出线={latest_ema*(1+ema_multiplier):.2f}")

    # 计算持仓成本和盈亏
    unrealized_pnl = 0
    unrealized_pnl_pct = 0
    try:
        if sym_pos:
            avg_cost = float(sym_pos.get("avg_cost", 0))
            if avg_cost > 0:
                unrealized_pnl = (current_price - avg_cost) * current_qty
                unrealized_pnl_pct = (current_price - avg_cost) / avg_cost * 100
    except:
        pass

    print(f"[盈亏] {symbol}: 持仓盈亏=${unrealized_pnl:.2f} ({unrealized_pnl_pct:.2f}%)")

    # 卖出信号判断
    sell_qty = 0
    signal = None
    signal_reason = ""

    # 1. EMA高位卖出
    if current_price >= latest_ema * (1 + ema_multiplier):
        profit_threshold = cfg.get("ema_high_sell_profit_pct", 0.1)
        price_increase_threshold = cfg.get("ema_high_sell_price_increase_pct", 0.05)
        last_sell_price = state.get("last_ema_high_sell_price")

        if unrealized_pnl_pct >= profit_threshold * 100:
            if last_sell_price is None or current_price >= last_sell_price * (1 + price_increase_threshold):
                sell_pct = cfg.get("sell_position_pct", 0.1)
                sell_qty = max(int(current_qty * sell_pct), 1)
                signal = "ema_high_sell"
                signal_reason = f"EMA高位卖出，价格{current_price:.2f} >= EMA×(1+{ema_multiplier})"

                if last_sell_price:
                    signal_reason += f"，本次价格相比上次卖出+{(current_price/last_sell_price-1)*100:.2f}%"

                state["last_ema_high_sell_price"] = current_price

    # 2. 短期止盈
    if not signal:
        today = date.today()
        take_profit_pct = cfg.get("take_profit_short_pct", 0.05)
        max_hold_days = cfg.get("max_hold_days", 2)

        for batch in state.get("batches", []):
            if batch.get("status") == "holding":
                buy_date = datetime.strptime(batch.get("buy_date"), "%Y-%m-%d").date()
                hold_days = (today - buy_date).days

                batch_profit_pct = (current_price - batch.get("buy_price", 0)) / batch.get("buy_price", 1) * 100

                if hold_days <= max_hold_days and batch_profit_pct >= take_profit_pct * 100:
                    sell_qty = batch.get("qty", 1)
                    signal = "short_take_profit"
                    signal_reason = f"短期止盈，持仓{hold_days}天，盈利{batch_profit_pct:.2f}%"
                    batch["status"] = "sold"
                    batch["sell_date"] = today.strftime("%Y-%m-%d")
                    batch["sell_price"] = current_price
                    batch["profit_pct"] = batch_profit_pct
                    break

    # 3. 盈利清仓（全部卖出，含底仓）
    if not signal:
        mega_profit_pct = cfg.get("mega_profit_pct", 0.3)
        if unrealized_pnl_pct >= mega_profit_pct * 100:
            sell_qty = current_qty  # 全部清仓，包括底仓
            signal = "mega_profit"
            signal_reason = f"盈利清仓，持仓盈利{unrealized_pnl_pct:.2f}% >= {mega_profit_pct*100:.0f}%，清仓全部{current_qty}股"

    if not signal or sell_qty <= 0:
        print(f"[卖出检查] {symbol} 无卖出信号")
        return False

    # mega_profit：清仓全部，跳过浮动仓位上限检查
    is_mega_profit = (signal == "mega_profit")

    if not is_mega_profit:
        sell_qty = min(sell_qty, sellable_qty)  # 普通卖出：不超过可卖量
    if sell_qty <= 0:
        print(f"[卖出检查] {symbol} 无可卖出股数")
        return False

    # 卖出前再次确认老虎账户实际持仓，防止挂单/人工交易导致持仓变化
    real_positions = get_positions(api, ACCOUNT)
    real_pos = None
    for p in real_positions:
        if p.get("symbol") == symbol:
            real_pos = p
            break
    real_qty = int(real_pos.get("quantity", 0)) if real_pos else 0
    real_sellable_qty = real_qty - base_qty
    print(f"[持仓确认] {symbol} 老虎账户实际持仓={real_qty} 股，可卖出={real_sellable_qty} 股")

    if is_mega_profit:
        # 盈利清仓：卖账户里全部实际持仓
        sell_qty = min(sell_qty, real_qty)
        if sell_qty <= 0:
            print(f"[卖出检查] {symbol} 账户无持仓，无需清仓")
            return False
    else:
        if real_sellable_qty <= 0:
            print(f"[卖出检查] {symbol} 账户实际可卖不足，跳过")
            return False
        sell_qty = min(sell_qty, real_sellable_qty)

    # 执行卖出（使用统一接口）
    name = cfg.get("name", symbol)
    result = place_sell_order(symbol, name, sell_qty, current_price, signal_reason, cfg)

    if result.get("success"):
        order_id = result.get("order_id", "")
        print(f"[卖出] {symbol} 订单已提交，ID: {order_id}")

        # 更新盈亏信息（A股模拟账户会返回盈亏）
        if result.get("profit") is not None:
            unrealized_pnl = result.get("profit", 0)
            unrealized_pnl_pct = result.get("profit_pct", 0)

        log_trade_by_symbol("SELL", current_price, sell_qty, signal_reason, order_id, None, symbol)

        daily_op["sell_count"] = daily_op.get("sell_count", 0) + 1
        daily_op["op_count"] = daily_op.get("op_count", 0) + 1
        save_daily_op_by_symbol(daily_op, symbol)

        # mega_profit 盈利清仓：全部卖出，重置 state
        if is_mega_profit:
            today_str = date.today().strftime("%Y-%m-%d")
            for b in state.get("batches", []):
                if b.get("status") == "holding":
                    b["status"] = "sold"
                    b["sell_date"] = today_str
                    b["sell_price"] = current_price
                    b["profit_pct"] = unrealized_pnl_pct
            # 归档并重置 state
            archive_on_clear(symbol, state, "mega_profit")
            state["base_established"] = False
            state["base_qty"] = 0
            state["batches"] = []
            state["cleared_date"] = today_str
            save_state(state, symbol)
            print(f"[盈利清仓] {symbol} 全部持仓已清，state 已重置，今日禁止交易")

        # 发送通知
        send_trade_notification(symbol, "SELL", current_price, sell_qty, order_id, signal_reason, {
            "signal": signal,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "ema": latest_ema
        })

        return True
    else:
        print(f"[卖出] {symbol} 卖出失败: {result.get('message', '未知错误')}")

    return False

def sync_orders(symbol, state, cfg):
    """同步订单状态"""
    print(f"\n[同步] {symbol} 同步订单状态...")

    api = get_tiger_api(cfg)
    if not api:
        return False

    try:
        resp = api.get_orders(account=ACCOUNT)
        if not isinstance(resp, dict):
            if isinstance(resp, list) and len(resp) > 0:
                print(f"[同步] {symbol} 查询返回列表（无待处理订单）")
            else:
                print(f"[同步] {symbol} 查询返回无效: {type(resp).__name__}")
            return True
        if resp.get("code") == 0:
            data = resp.get("data", {})
            if not isinstance(data, dict):
                data = {}
            for order in data.get("items", []):
                if order.get("symbol") == symbol:
                    status = order.get("status")
                    order_id = str(order.get("id"))
                    filled_qty = int(order.get("filled_quantity", 0))
                    avg_price = float(order.get("avg_fill_price", 0))
                    action = order.get("action", "")

                    if status == "filled" and filled_qty > 0:
                        print(f"[同步] {symbol} 订单{order_id}已成交: {action} {filled_qty}股 @ ${avg_price:.2f}")

                        log_trade_by_symbol(action, avg_price, filled_qty, "订单成交", order_id, None, symbol)

                        # 更新状态
                        if action == "BUY":
                            state["base_qty"] = state.get("base_qty", 0) + filled_qty
                            state["base_established"] = True
                        elif action == "SELL":
                            state["base_qty"] = max(0, state.get("base_qty", 0) - filled_qty)

                        save_state(state, symbol)

                        # 发送通知
                        send_trade_notification(symbol, action, avg_price, filled_qty, order_id, "订单成交")

    except Exception as e:
        print(f"[同步] {symbol} 查询失败: {e}")

    return True

def show_status(symbol, state, cfg):
    """显示状态"""
    print(f"\n{'='*60}")
    print(f"{symbol} 策略状态 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    print(f"\n[基本信息]")
    print(f"  标的名称: {cfg.get('name', symbol)}")
    print(f"  市场: {cfg.get('market', 'US')}")
    print(f"  底仓数量: {cfg.get('base_position', 1)}")
    print(f"  交易数量: {cfg.get('trade_qty', 1)}")

    api = get_tiger_api(cfg)
    positions = get_positions(api, ACCOUNT) if api else []

    print(f"\n[持仓状态]")
    print(f"  底仓已建立: {'是' if state.get('base_established') else '否'}")
    print(f"  底仓股数: {state.get('base_qty', 0)}")

    sym_pos = None
    for pos in positions:
        if pos.get("symbol") == symbol:
            sym_pos = pos
            break

    if sym_pos:
        current_qty = int(sym_pos.get("quantity", 0))
        avg_cost = float(sym_pos.get("avg_cost", 0))
        unrealized_pnl = float(sym_pos.get("unrealized_pnl", 0))

        print(f"  当前持仓: {current_qty} 股")
        print(f"  成本价: ${avg_cost:.2f}")
        print(f"  浮动盈亏: ${unrealized_pnl:.2f}")

        quote = get_quote(symbol)
        if quote:
            current_price = quote.get("last_price", 0)
            profit_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
            print(f"  当前价: ${current_price:.2f}")
            print(f"  盈亏比例: {profit_pct:.2f}%")

    # 获取K线
    kline = get_kline(symbol, days=20)
    if kline is not None and len(kline) > 0:
        kline['ema'] = calc_ema(kline, 13)
        print(f"\n[K线]")
        print(f"  最新收盘: ${kline['close'].iloc[-1]:.2f}")
        print(f"  EMA13: ${kline['ema'].iloc[-1]:.2f}")

    print(f"\n{'='*60}")

# ============================================================
# 主入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n可用参数:")
        print("  --symbol=XXX --init         初始化底仓")
        print("  --symbol=XXX --buy-check    买入检查")
        print("  --symbol=XXX --sell-check  卖出检查")
        print("  --symbol=XXX --sync         同步订单")
        print("  --symbol=XXX --status       查看状态")
        print("  --hang-all                 批量处理所有股票")
        sys.exit(1)

    # 解析参数
    cmd = None
    for arg in sys.argv[1:]:
        if arg == "--init":
            cmd = "init"
        elif arg == "--buy-check":
            cmd = "buy_check"
        elif arg == "--sell-check":
            cmd = "sell_check"
        elif arg == "--sync":
            cmd = "sync"
        elif arg == "--status":
            cmd = "status"

    if not cmd:
        print("错误: 未指定操作命令")
        sys.exit(1)

    # 批量处理模式
    if is_hang_all_mode():
        config = load_config()
        symbols = config.get("enabled_symbols", [])

        # 市场过滤
        market_filter = get_market_filter()
        if market_filter:
            filtered = [s for s in symbols if market_data.is_chinese_market(s) == (market_filter == "CN")]
            if filtered:
                print(f"[批量] 市场过滤: {market_filter}, {len(symbols)} -> {len(filtered)} 个股票: {filtered}")
                symbols = filtered
            else:
                print(f"[批量] 市场过滤: {market_filter}, 无匹配标的，跳过")
                return

        print(f"[批量] 将处理 {len(symbols)} 个股票: {symbols}")

        for symbol in symbols:
            try:
                cfg = get_symbol_config(symbol)
                state = load_state(symbol)

                if cmd == "buy_check":
                    do_buy_check(symbol, state, cfg)
                elif cmd == "sell_check":
                    do_sell_check(symbol, state, cfg)
                elif cmd == "sync":
                    sync_orders(symbol, state, cfg)

            except Exception as e:
                print(f"[错误] {symbol}: {e}")

        return

    # 单股票模式
    if not SYMBOL:
        print("错误: 请指定 --symbol=XXX")
        sys.exit(1)

    state = load_state(SYMBOL)

    if cmd == "init":
        print(f"[初始化] {SYMBOL}")
        api = get_tiger_api(CONFIG)
        if api:
            positions = get_positions(api, ACCOUNT)
            sym_pos = None
            for pos in positions:
                if pos.get("symbol") == SYMBOL:
                    sym_pos = pos
                    break
            if sym_pos:
                current_qty = int(sym_pos.get("quantity", 0))
                print(f"[初始化] {SYMBOL} 当前持仓: {current_qty} 股")
                state["base_established"] = True
                state["base_qty"] = current_qty
                save_state(state)
                print(f"[初始化] {SYMBOL} 底仓初始化完成")
            else:
                print(f"[初始化] {SYMBOL} 无持仓")
        else:
            print(f"[初始化] {SYMBOL} 无法获取API")

    elif cmd == "buy_check":
        do_buy_check(SYMBOL, state, CONFIG)

    elif cmd == "sell_check":
        do_sell_check(SYMBOL, state, CONFIG)

    elif cmd == "sync":
        sync_orders(SYMBOL, state, CONFIG)

    elif cmd == "status":
        show_status(SYMBOL, state, CONFIG)

if __name__ == "__main__":
    main()