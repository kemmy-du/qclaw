"""
A股定投策略 - 主程序入口

适用市场：A股（上交所/深交所）
交易方式：本地模拟账户
行情数据：东方财富网

用法:
  python stock_t_cn.py --symbol=603773 --init           # 初始化底仓
  python stock_t_cn.py --symbol=603773 --buy-check     # 买入检查
  python stock_t_cn.py --symbol=603773 --sell-check    # 卖出检查
  python stock_t_cn.py --symbol=603773 --status        # 查看状态

  # 批量操作
  python stock_t_cn.py --hang-all                      # 所有A股挂单
  python stock_t_cn.py --market=CN --hang-all          # 仅A股标的
"""

import sys
import os
import json
import shutil
from datetime import datetime, timedelta, date

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd

# 导入 CN common（行情 + 通知）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import market_data_cn
from common import notification_cn as notification

# 行情数据快捷方式
from common.market_data_cn import (
    get_quote, get_kline, calculate_ema, is_chinese_market,
    EastmoneySource
)

# A股模拟账户
import cn_sim_account as cn_sim


# ============================================================
# 配置加载
# ============================================================

STRATEGY_NAME = "A股定投策略"


def get_symbol_from_args():
    for arg in sys.argv:
        if arg.startswith("--symbol="):
            return arg.split("=", 1)[1]
    return None


def is_hang_all_mode():
    return any(arg == "--hang-all" for arg in sys.argv)


def get_market_filter():
    for arg in sys.argv:
        if arg.startswith("--market="):
            return arg.split("=", 1)[1].upper()
    return None


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_symbol_config(symbol: str):
    cfg = load_config()
    sym_cfg = cfg["symbol_configs"].get(symbol)
    if not sym_cfg:
        raise ValueError(f"股票配置不存在: {symbol}")

    # 合并全局默认
    result = sym_cfg.copy()
    global_defaults = cfg.get("global_defaults", {})
    for key in ["feishu_webhook", "notification", "send_to_feishu"]:
        if key not in result:
            result[key] = global_defaults.get(key)

    # 构建通知配置
    notif_cfg = result.get("notification") or global_defaults.get("notification") or {}
    channels = notif_cfg.get("channels") or ["feishu"]
    result["_notification_config"] = notification.create_config(
        webhook=result.get("feishu_webhook"),
        enabled=cfg.get("send_to_feishu", True),
        channels=channels,
        weixin_target=notif_cfg.get("weixin_target"),
        weixin_account_id=notif_cfg.get("weixin_account_id")
    )
    return result


SYMBOL = get_symbol_from_args()
if not SYMBOL and not is_hang_all_mode():
    print("错误: 请指定股票代码，例如 --symbol=603773")
    sys.exit(1)

CONFIG = get_symbol_config(SYMBOL) if SYMBOL else load_config()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
ARCHIVE_DIR = os.path.join(LOGS_DIR, "archive")


def get_state_file(symbol):
    return os.path.join(DATA_DIR, f"{symbol}_state.json")


def get_daily_op_file(symbol):
    return os.path.join(DATA_DIR, f"{symbol}_daily_op.json")


def get_trades_log(symbol):
    return os.path.join(LOGS_DIR, f"{symbol}_trades.jsonl")


def get_archive_file(symbol):
    return os.path.join(DATA_DIR, f"{symbol}_archive.jsonl")


# ============================================================
# 通知
# ============================================================

def _notif_kwargs(cfg):
    nc = cfg.get("_notification_config")
    if nc:
        return {"enabled": nc.enabled, "channels": nc.channels}
    return {"enabled": False}


def send_trade_notification(symbol, action, price, qty, order_id="", reason="", extra_info=None):
    cfg = get_symbol_config(symbol)
    name = cfg.get("name", symbol)
    action_text = "买入" if action == "BUY" else "卖出"
    color = "green" if action == "BUY" else "red"

    builder = notification.FeishuCardBuilder(
        title=f"[{STRATEGY_NAME}] {action_text} - {symbol} ({name})", color=color
    )
    builder.add_key_value("交易方向", f"**{action_text}**")
    builder.add_key_value("成交价格", f"`¥{price:.2f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    builder.add_key_value("订单ID", f"`{order_id or 'N/A'}`")
    if extra_info:
        builder.add_divider()
        for k, v in extra_info.items():
            builder.add_key_value(str(k), str(v))
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {STRATEGY_NAME} | 自动通知")

    return notification.send_card(builder.build(), **_notif_kwargs(cfg))


def send_status_notification(symbol, content, color="blue"):
    cfg = get_symbol_config(symbol)
    name = cfg.get("name", symbol)
    card = notification.build_status_card(
        title=f"[{STRATEGY_NAME}] {symbol} ({name})",
        content=content,
        color=color
    )
    return notification.send_card(card, **_notif_kwargs(cfg))


def send_profit_notification(symbol, buy_price, sell_price, qty, buy_date="", sell_date=""):
    cfg = get_symbol_config(symbol)
    name = cfg.get("name", symbol)
    profit_amount = (sell_price - buy_price) * qty
    profit_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    is_profit = profit_amount >= 0
    color = "green" if is_profit else "red"
    emoji = "🟢" if is_profit else "🔴"

    builder = notification.FeishuCardBuilder(
        title=f"[{STRATEGY_NAME}] 卖出 - {symbol} ({name})", color=color
    )
    builder.add_markdown(f"{emoji} **盈亏: `¥{profit_amount:.2f}` ({profit_pct:+.2f}%)**")
    builder.add_divider()
    if buy_date:
        builder.add_key_value("买入日期", buy_date)
    if sell_date:
        builder.add_key_value("卖出日期", sell_date)
    builder.add_key_value("买入价", f"`¥{buy_price:.2f}`")
    builder.add_key_value("卖出价", f"`¥{sell_price:.2f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    builder.add_key_value("持仓盈亏", f"{emoji} `¥{profit_amount:.2f}`")
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {STRATEGY_NAME} | 自动通知")

    return notification.send_card(builder.build(), **_notif_kwargs(cfg))


# ============================================================
# 状态管理
# ============================================================

def load_state(symbol):
    state_file = get_state_file(symbol)
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
            state.setdefault("hang_limit_price", None)
            state.setdefault("last_ema_high_sell_price", None)
            state.setdefault("cleared_date", None)
            for b in state.get("batches", []):
                if "trade_count" not in b:
                    b["trade_count"] = 0
            return state
    return {
        "base_established": False, "base_qty": 0, "batches": [],
        "batch_counter": 0, "pending_orders": [],
        "hang_order_id": None, "hang_order_date": None,
        "hang_limit_price": None, "last_ema_high_sell_price": None,
        "cleared_date": None
    }


def save_state(state, symbol):
    state_file = get_state_file(symbol)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_daily_op(symbol):
    daily_file = get_daily_op_file(symbol)
    today_str = date.today().strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(daily_file), exist_ok=True)
    if os.path.exists(daily_file):
        with open(daily_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("date") == today_str:
                return data
    return {
        "date": today_str, "sold": False, "bought": False,
        "hang_order_placed": False, "op_count": 0,
        "buy_count": 0, "sell_count": 0
    }


def save_daily_op(data, symbol):
    daily_file = get_daily_op_file(symbol)
    os.makedirs(os.path.dirname(daily_file), exist_ok=True)
    with open(daily_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log_trade(action, price, qty, reason="", order_id="", batch_id=None, symbol=None):
    sym = symbol or SYMBOL
    trade_log = get_trades_log(sym)
    cfg = get_symbol_config(sym)
    os.makedirs(os.path.dirname(trade_log), exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(),
        "action": action, "symbol": sym,
        "name": cfg.get("name", sym), "price": price, "qty": qty,
        "reason": reason, "order_id": order_id, "batch_id": batch_id
    }
    with open(trade_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_config_base_position(symbol, new_base_qty):
    try:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            full_config = json.load(f)
        if symbol in full_config.get("symbol_configs", {}):
            old = full_config["symbol_configs"][symbol].get("base_position", 0)
            full_config["symbol_configs"][symbol]["base_position"] = new_base_qty
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(full_config, f, ensure_ascii=False, indent=2)
            print(f"[底仓] {symbol} base_position: {old} -> {new_base_qty}")
            return True
    except Exception as e:
        print(f"[底仓] {symbol} 更新配置失败: {e}")
    return False


def archive_on_clear(symbol, state):
    today_str = date.today().strftime("%Y-%m-%d")
    trades_log = get_trades_log(symbol)

    if os.path.exists(trades_log):
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        archive_log = os.path.join(ARCHIVE_DIR, f"{symbol}_trades_{today_str}.jsonl")
        shutil.move(trades_log, archive_log)
        print(f"[归档] 交易日志 -> {archive_log}")

    archive_records = []
    for b in state.get("batches", []):
        if b.get("status") == "sold":
            archive_records.append({
                "batch_id": b.get("id"), "buy_date": b.get("buy_date"),
                "buy_price": b.get("buy_price"), "qty": b.get("qty"),
                "sell_date": b.get("sell_date"), "sell_price": b.get("sell_price"),
                "profit_pct": b.get("profit_pct"), "signal": b.get("signal"),
                "archive_date": today_str
            })

    archive_file = get_archive_file(symbol)
    if archive_records:
        os.makedirs(os.path.dirname(archive_file), exist_ok=True)
        with open(archive_file, "a", encoding="utf-8") as f:
            for r in archive_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[归档] 买卖记录 {len(archive_records)} 条 -> {archive_file}")


# ============================================================
# 交易操作
# ============================================================

def get_cn_positions(symbol: str = None):
    return cn_sim.get_positions(symbol)


def cn_buy(symbol: str, name: str, qty: int, price: float, reason: str = "") -> dict:
    """A股买入（自动调整为100的整数倍）"""
    if qty % 100 != 0:
        qty = ((qty // 100) + 1) * 100
        print(f"[A股] 买入数量调整为 {qty} 股（100的整数倍）")
    result = cn_sim.buy(symbol, name, qty, price, reason)
    return result


def cn_sell(symbol: str, qty: int, price: float, reason: str = "") -> dict:
    """A股卖出（自动调整为100的整数倍）"""
    if qty % 100 != 0:
        qty = (qty // 100) * 100
        if qty <= 0:
            return {"success": False, "message": "卖出数量不足100股"}
        print(f"[A股] 卖出数量调整为 {qty} 股（100的整数倍）")
    result = cn_sim.sell(symbol, qty, price, reason)
    return result


def place_buy_order(symbol: str, name: str, qty: int, price: float, reason: str, cfg: dict) -> dict:
    result = cn_buy(symbol, name, qty, price, reason)
    if result.get("success"):
        log_trade("BUY", price, qty, reason, result.get("order_id", ""), None, symbol)
    return result


def place_sell_order(symbol: str, name: str, qty: int, price: float, reason: str, cfg: dict) -> dict:
    result = cn_sell(symbol, qty, price, reason)
    if result.get("success"):
        log_trade("SELL", price, qty, reason, result.get("order_id", ""), None, symbol)
    return result


# ============================================================
# 核心交易逻辑
# ============================================================

def promote_batches_to_base(symbol, state, cfg):
    """动态底仓：持仓超期的批次自动升级为底仓"""
    dynamic_days = cfg.get("dynamic_base_days", 0)
    if dynamic_days <= 0:
        return

    today = date.today()
    promoted = []
    total = 0

    for batch in state.get("batches", []):
        if batch.get("status") != "holding":
            continue
        buy_date = datetime.strptime(batch.get("buy_date"), "%Y-%m-%d").date()
        if (today - buy_date).days >= dynamic_days:
            batch_qty = batch.get("qty", 0)
            batch["status"] = "promoted"
            batch["promote_date"] = today.strftime("%Y-%m-%d")
            batch["promote_price"] = batch.get("buy_price", 0)
            promoted.append(batch.get("id"))
            total += batch_qty

    if total > 0:
        old_base = state.get("base_qty", 0)
        state["base_qty"] = old_base + total
        save_state(state, symbol)
        print(f"[动态底仓] {symbol} 升级 {len(promoted)} 个批次({'/'.join(map(str, promoted))}) "
              f"共{total}股 -> base_qty: {old_base} -> {state['base_qty']}")


def do_buy_check(symbol, state, cfg):
    """买入检查（EMA信号 + 底仓管理）"""
    print(f"\n[买入检查] {symbol} 开始检查...")

    # 清仓当日禁止交易
    cleared_date = state.get("cleared_date")
    today_str = date.today().strftime("%Y-%m-%d")
    if cleared_date and cleared_date == today_str:
        print(f"[买入检查] {symbol} 今日已清仓，禁止交易，次日方可重建底仓")
        return False

    daily_op = load_daily_op(symbol)
    if daily_op.get("buy_count", 0) >= cfg.get("max_buy_count", 2):
        print(f"[买入检查] {symbol} 今日买入次数已达上限")
        return False

    promote_batches_to_base(symbol, state, cfg)

    quote = get_quote(symbol)
    if not quote:
        print(f"[买入检查] {symbol} 无法获取行情")
        return False

    current_price = quote.get("last_price", 0)
    prev_close = quote.get("prev_close", current_price)

    print(f"[行情] {symbol}: 现价=¥{current_price:.2f}, 昨收=¥{prev_close:.2f}")

    kline = get_kline(symbol, days=cfg.get("kline_num", 60))
    if kline is None or len(kline) < cfg.get("ema_period", 13) + 5:
        print(f"[买入检查] {symbol} K线数据不足（可能停牌）")
        if not cfg.get("trade_enabled", True) or cfg.get("watch_only", False):
            market = "A股"
            change_pct = (current_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
            notif_content = f"""**【{symbol} 行情提醒】**

📈 市场: {market}
🏷️ 代码: `{symbol}`
💰 当前价格: `¥{current_price:.2f}`
📊 昨收价格: `¥{prev_close:.2f}`
📊 涨跌额: `¥{current_price - prev_close:.4f}`
📊 涨跌幅: `{change_pct:+.2f}%`

⚠️ K线数据暂不可用（可能停牌）

请人工判断交易时机！"""
            send_status_notification(symbol, notif_content, color="blue")
        return False

    kline["ema"] = calculate_ema(kline, cfg.get("ema_period", 13))
    latest_ema = kline["ema"].iloc[-1]
    print(f"[EMA] {symbol}: 当前EMA13=¥{latest_ema:.2f}")

    signal = None
    signal_reason = ""

    # EMA突破
    if not signal:
        breakout_all_lookback = cfg.get("ema_breakout_all_lookback", 10)
        breakout_lookback = cfg.get("ema_breakout_lookback", 5)
        breakout_threshold = cfg.get("ema_breakout_threshold", 0.03)

        if current_price >= latest_ema:
            all_below = True
            m_check = 0
            for i in range(-breakout_all_lookback, 0):
                if -i <= len(kline):
                    if kline["close"].iloc[i] >= kline["ema"].iloc[i]:
                        all_below = False
                        break
                    m_check += 1

            below_count = 0
            threshold_price = 0
            if all_below and m_check > 0:
                for i in range(-breakout_lookback, 0):
                    if -i <= len(kline):
                        ema_val = kline["ema"].iloc[i]
                        close_val = kline["close"].iloc[i]
                        tp = ema_val * (1 - breakout_threshold)
                        if close_val < tp:
                            below_count += 1
                            threshold_price = tp

            if all_below and below_count > 0:
                signal = "ema_breakout"
                signal_reason = (f"EMA突破，现价{current_price:.2f}>=EMA={latest_ema:.2f}，"
                                 f"前{m_check}天均在EMA之下，前{breakout_lookback}天中{below_count}天"
                                 f"低于EMA×(1-{breakout_threshold})={threshold_price:.2f}")

    # EMA回踩
    if not signal:
        pullback_high = cfg.get("ema_pullback_high_threshold", 0.03)
        pullback_low = cfg.get("ema_pullback_low_threshold", 0.03)
        pullback_all_above_lookback = cfg.get("ema_pullback_all_above_lookback", 10)
        pullback_above_lookback = cfg.get("ema_pullback_above_lookback", 5)
        pullback_above_pct = cfg.get("ema_pullback_above_pct", 0.05)

        all_above = True
        m_count = 0
        for i in range(-pullback_all_above_lookback, 0):
            if -i <= len(kline):
                if kline["close"].iloc[i] < kline["ema"].iloc[i]:
                    all_above = False
                    break
                m_count += 1

        above_count = 0
        threshold_price = 0
        if all_above and m_count > 0:
            for i in range(-pullback_above_lookback, 0):
                if -i <= len(kline):
                    ema_val = kline["ema"].iloc[i]
                    close_val = kline["close"].iloc[i]
                    tp = ema_val * (1 + pullback_above_pct)
                    if close_val > tp:
                        above_count += 1
                        threshold_price = tp

        if all_above and above_count > 0:
            ema_val = kline["ema"].iloc[-1]
            if ema_val * (1 - pullback_low) <= current_price <= ema_val * (1 + pullback_high):
                signal = "ema_pullback"
                signal_reason = (f"EMA回踩，现价{current_price:.2f}，EMA={ema_val:.2f}，"
                                 f"前{m_count}天均在EMA之上，前{pullback_above_lookback}天中"
                                 f"{above_count}天超过EMA×(1+{pullback_above_pct})={threshold_price:.2f}")

    # EMA超跌 → 直接买入
    if not signal:
        oversold_mult = cfg.get("ema_oversold_multiplier", 0.2)
        if current_price <= latest_ema * (1 - oversold_mult):
            signal = "ema_oversold"
            signal_reason = f"EMA超跌，现价{current_price:.2f}<=EMA×(1-{oversold_mult})，直接买入"

    # 二者合并，取跌幅更大者作为触发条件
    if not signal:
        buy_drop_pct = cfg.get("buy_drop_pct", 0.08)

        if drop_pct > 0:
            trigger_price = round(prev_close * (1 - drop_pct), 2)
            if current_price < trigger_price:
                ema_filter = cfg.get("buy_drop_ema_filter", False)
                ema_ok = True
                if ema_filter and signal not in ("ema_breakout", "ema_pullback"):
                    ema_ok = False
                if ema_ok:
                    signal = "daily_drop_buy"
                    filter_note = "（EMA信号确认）" if ema_filter else "（直接触发）"
                    signal_reason = (f"跌幅买入，现价¥{current_price:.2f}<昨收¥{prev_close:.2f}×{1-drop_pct:.2%}"
                                     f"=¥{trigger_price:.2f}{filter_note}")
                elif ema_filter and not ema_ok:
                    notif_content = f"""**【{symbol} 跌幅信号 - 等待EMA确认】**

🏷️ 代码: `{symbol}`
📊 市场: A股
💰 当前价格: `¥{current_price:.2f}`
💰 昨收价格: `¥{prev_close:.2f}`
📊 触发条件: 昨收 × (1 - {drop_pct:.2%}) = `¥{trigger_price:.2f}`
📐 EMA13: `¥{latest_ema:.2f}`

⚠️ 跌幅已达标（现价 < ¥{trigger_price:.2f}），但 EMA 尚未突破/回踩确认，暂时观望。
如后续 EMA 信号确认，将触发买入。"""
                    send_status_notification(symbol, notif_content, color="orange")
                    print(f"[买入检查] {symbol} 跌幅达标（现价¥{current_price:.2f}<¥{trigger_price:.2f}），"
                          f"但EMA未确认，仅通知")

    if not signal:
        print(f"[买入检查] {symbol} 无买入信号")
        return False

    print(f"[信号] {symbol}: {signal} - {signal_reason}")

    if not cfg.get("trade_enabled", True) or cfg.get("watch_only", False):
        print(f"[监控] {symbol} 仅监控模式，发送信号通知...")
        notif_content = f"""**【{symbol} 买入信号提醒】**

📈 市场: A股
🏷️ 代码: `{symbol}`
📝 信号类型: **{signal}**
💰 当前价格: `¥{current_price:.2f}`
📊 昨收价格: `¥{prev_close:.2f}`
📐 EMA13: `¥{latest_ema:.2f}`

📋 信号详情:
{signal_reason}

⚠️ 当前为仅监控模式，不会自动下单。

请人工判断是否需要买入！"""
        send_status_notification(symbol, notif_content, color="orange")
        return True

    # 检查持仓
    positions = get_cn_positions(symbol)
    sym_pos = positions[0] if positions else None
    current_qty = int(sym_pos.get("quantity", 0)) if sym_pos else 0
    base_position = cfg.get("base_position", 100)
    trade_qty = cfg.get("trade_qty", 100)

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

    name = cfg.get("name", symbol)
    result = place_buy_order(symbol, name, buy_qty, current_price, signal_reason, cfg)

    if result.get("success"):
        order_id = result.get("order_id", "")
        print(f"[买入] {symbol} 订单已提交，ID: {order_id}")
        log_trade("BUY", current_price, buy_qty, signal_reason, order_id, None, symbol)

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
            print(f"[批次] {symbol} 创建批次 #{batch_id}: {buy_qty}股@¥{current_price:.2f}, 信号={signal}")

        if not state.get("base_established"):
            state["base_established"] = True
            state["base_qty"] = base_position
        else:
            state["base_qty"] = state.get("base_qty", 0) + buy_qty
        save_state(state, symbol)

        daily_op["buy_count"] = daily_op.get("buy_count", 0) + 1
        daily_op["op_count"] = daily_op.get("op_count", 0) + 1
        save_daily_op(daily_op, symbol)

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
    """卖出检查（EMA高位 + 短期止盈 + 盈利清仓）"""
    print(f"\n[卖出检查] {symbol} 开始检查...")

    # 清仓当日禁止交易
    cleared_date = state.get("cleared_date")
    today_str = date.today().strftime("%Y-%m-%d")
    if cleared_date and cleared_date == today_str:
        print(f"[卖出检查] {symbol} 今日已清仓，禁止交易，次日方可重建底仓")
        return False

    daily_op = load_daily_op(symbol)
    if daily_op.get("sell_count", 0) >= cfg.get("max_sell_count", 2):
        print(f"[卖出检查] {symbol} 今日卖出次数已达上限")
        return False

    positions = get_cn_positions(symbol)
    sym_pos = positions[0] if positions else None
    current_qty = int(sym_pos.get("quantity", 0)) if sym_pos else 0
    base_qty = state.get("base_qty", cfg.get("base_position", 100))
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
    print(f"[行情] {symbol}: 现价=¥{current_price:.2f}")

    kline = get_kline(symbol, days=cfg.get("kline_num", 60))
    if kline is None or len(kline) < cfg.get("ema_period", 13) + 5:
        print(f"[卖出检查] {symbol} K线数据不足")
        return False

    kline["ema"] = calculate_ema(kline, cfg.get("ema_period", 13))
    latest_ema = kline["ema"].iloc[-1]
    ema_multiplier = cfg.get("ema_sell_high_multiplier", 0.2)

    print(f"[EMA] {symbol}: 当前EMA=¥{latest_ema:.2f}, 卖出线=¥{latest_ema*(1+ema_multiplier):.2f}")

    unrealized_pnl = 0
    unrealized_pnl_pct = 0
    if sym_pos:
        avg_cost = float(sym_pos.get("avg_cost", 0))
        if avg_cost > 0:
            unrealized_pnl = (current_price - avg_cost) * current_qty
            unrealized_pnl_pct = (current_price - avg_cost) / avg_cost * 100

    print(f"[盈亏] {symbol}: 持仓盈亏=¥{unrealized_pnl:.2f} ({unrealized_pnl_pct:.2f}%)")

    sell_qty = 0
    signal = None
    signal_reason = ""
    is_mega_profit = False

    # 盈利清仓（全部，含底仓）
    if not signal:
        mega_profit_pct = cfg.get("mega_profit_pct", 0.1)
        if unrealized_pnl_pct >= mega_profit_pct * 100:
            sell_qty = current_qty
            signal = "mega_profit"
            signal_reason = (f"盈利清仓，持仓盈利{unrealized_pnl_pct:.2f}%>="
                            f"{mega_profit_pct*100:.0f}%，清仓全部{current_qty}股")
            is_mega_profit = True

    # EMA高位卖出
    if not signal:
        profit_threshold = cfg.get("ema_high_sell_profit_pct", 0.1)
        price_increase_threshold = cfg.get("ema_high_sell_price_increase_pct", 0.05)
        last_sell_price = state.get("last_ema_high_sell_price")

        if unrealized_pnl_pct >= profit_threshold * 100:
            if last_sell_price is None or current_price >= last_sell_price * (1 + price_increase_threshold):
                sell_pct = cfg.get("sell_position_pct", 0.1)
                sell_qty = max(int(current_qty * sell_pct), 100)
                signal = "ema_high_sell"
                signal_reason = (f"EMA高位卖出，价格{current_price:.2f}>=EMA×(1+{ema_multiplier})")
                if last_sell_price:
                    signal_reason += f"，本次价格相比上次卖出+{(current_price/last_sell_price-1)*100:.2f}%"
                state["last_ema_high_sell_price"] = current_price

    # 短期止盈
    if not signal:
        today = date.today()
        take_profit_pct = cfg.get("take_profit_short_pct", 0.03)
        max_hold_days = cfg.get("max_hold_days", 3)

        for batch in state.get("batches", []):
            if batch.get("status") == "holding":
                buy_date = datetime.strptime(batch.get("buy_date"), "%Y-%m-%d").date()
                hold_days = (today - buy_date).days
                batch_profit_pct = (
                    (current_price - batch.get("buy_price", 0)) / batch.get("buy_price", 1) * 100
                )

                if hold_days <= max_hold_days and batch_profit_pct >= take_profit_pct * 100:
                    sell_qty = batch.get("qty", 100)
                    signal = "short_take_profit"
                    signal_reason = f"短期止盈，持仓{hold_days}天，盈利{batch_profit_pct:.2f}%"
                    batch["status"] = "sold"
                    batch["sell_date"] = today.strftime("%Y-%m-%d")
                    batch["sell_price"] = current_price
                    batch["profit_pct"] = batch_profit_pct
                    break

    if not signal or sell_qty <= 0:
        print(f"[卖出检查] {symbol} 无卖出信号")
        return False

    if is_mega_profit:
        sell_qty = min(sell_qty, current_qty)
    else:
        sell_qty = min(sell_qty, sellable_qty)

    if sell_qty <= 0:
        print(f"[卖出检查] {symbol} 无可卖出股数")
        return False

    # 再次确认实际持仓
    real_positions = get_cn_positions(symbol)
    real_pos = real_positions[0] if real_positions else None
    real_qty = int(real_pos.get("quantity", 0)) if real_pos else 0
    real_sellable_qty = real_qty - base_qty
    print(f"[持仓确认] {symbol} 实际持仓={real_qty} 股，可卖出={real_sellable_qty} 股")

    if is_mega_profit:
        sell_qty = min(sell_qty, real_qty)
        if sell_qty <= 0:
            print(f"[卖出检查] {symbol} 账户无持仓，无需清仓")
            return False
    else:
        if real_sellable_qty <= 0:
            print(f"[卖出检查] {symbol} 账户实际可卖不足，跳过")
            return False
        sell_qty = min(sell_qty, real_sellable_qty)

    # A股卖出必须是100整数倍
    if sell_qty % 100 != 0:
        sell_qty = (sell_qty // 100) * 100

    name = cfg.get("name", symbol)
    result = place_sell_order(symbol, name, sell_qty, current_price, signal_reason, cfg)

    if result.get("success"):
        order_id = result.get("order_id", "")
        print(f"[卖出] {symbol} 订单已提交，ID: {order_id}")

        if result.get("profit") is not None:
            unrealized_pnl = result.get("profit", 0)
            unrealized_pnl_pct = result.get("profit_pct", 0)

        log_trade("SELL", current_price, sell_qty, signal_reason, order_id, None, symbol)

        daily_op["sell_count"] = daily_op.get("sell_count", 0) + 1
        daily_op["op_count"] = daily_op.get("op_count", 0) + 1
        save_daily_op(daily_op, symbol)

        if is_mega_profit:
            today_str = date.today().strftime("%Y-%m-%d")
            for b in state.get("batches", []):
                if b.get("status") == "holding":
                    b["status"] = "sold"
                    b["sell_date"] = today_str
                    b["sell_price"] = current_price
                    b["profit_pct"] = unrealized_pnl_pct
            archive_on_clear(symbol, state)
            state["base_established"] = False
            state["base_qty"] = 0
            state["batches"] = []
            state["cleared_date"] = today_str
            save_state(state, symbol)
            print(f"[盈利清仓] {symbol} 全部持仓已清，state 已重置，今日禁止交易")

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


def show_status(symbol, state, cfg):
    print(f"\n{'='*60}")
    print(f"{symbol} 策略状态 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    print(f"\n[基本信息]")
    print(f"  标的名称: {cfg.get('name', symbol)}")
    print(f"  市场: A股")
    print(f"  底仓数量: {cfg.get('base_position', 100)}")
    print(f"  交易数量: {cfg.get('trade_qty', 100)}")

    positions = get_cn_positions(symbol)
    sym_pos = positions[0] if positions else None

    print(f"\n[持仓状态]")
    print(f"  底仓已建立: {'是' if state.get('base_established') else '否'}")
    print(f"  底仓股数: {state.get('base_qty', 0)}")

    if sym_pos:
        current_qty = int(sym_pos.get("quantity", 0))
        avg_cost = float(sym_pos.get("avg_cost", 0))
        unrealized_pnl = (quote.get("last_price", avg_cost) - avg_cost) * current_qty if avg_cost > 0 else 0

        quote = get_quote(symbol)
        current_price = quote.get("last_price", avg_cost) if quote else avg_cost
        profit_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0

        print(f"  当前持仓: {current_qty} 股")
        print(f"  成本价: ¥{avg_cost:.2f}")
        print(f"  当前价: ¥{current_price:.2f}")
        print(f"  浮动盈亏: ¥{unrealized_pnl:.2f} ({profit_pct:.2f}%)")

    kline = get_kline(symbol, days=20)
    if kline is not None and len(kline) > 0:
        kline["ema"] = calculate_ema(kline, 13)
        print(f"\n[K线]")
        print(f"  最新收盘: ¥{kline['close'].iloc[-1]:.2f}")
        print(f"  EMA13: ¥{kline['ema'].iloc[-1]:.2f}")

    print(f"\n{'='*60}")


# ============================================================
# 主入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = None
    for arg in sys.argv[1:]:
        if arg == "--init": cmd = "init"
        elif arg == "--buy-check": cmd = "buy_check"
        elif arg == "--sell-check": cmd = "sell_check"
        elif arg == "--status": cmd = "status"

    if not cmd:
        print("错误: 未指定操作命令")
        sys.exit(1)

    # 批量处理模式
    if is_hang_all_mode():
        config = load_config()
        symbols = config.get("enabled_symbols", [])
        market_filter = get_market_filter()

        if market_filter:
            filtered = [s for s in symbols if is_chinese_market(s) == (market_filter == "CN")]
            if filtered:
                print(f"[批量] 市场过滤: {market_filter}, {len(symbols)} -> {len(filtered)} 个: {filtered}")
                symbols = filtered
            else:
                print(f"[批量] 市场过滤: {market_filter}, 无匹配标的")
                return

        print(f"[批量] 将处理 {len(symbols)} 个股票: {symbols}")

        for sym in symbols:
            try:
                cfg = get_symbol_config(sym)
                state = load_state(sym)

                if cmd == "buy_check":
                    do_buy_check(sym, state, cfg)
                elif cmd == "sell_check":
                    do_sell_check(sym, state, cfg)
            except Exception as e:
                print(f"[错误] {sym}: {e}")

        return

    # 单股票模式
    if not SYMBOL:
        print("错误: 请指定 --symbol=XXX")
        sys.exit(1)

    state = load_state(SYMBOL)

    if cmd == "init":
        print(f"[初始化] {SYMBOL}")
        positions = get_cn_positions(SYMBOL)
        sym_pos = positions[0] if positions else None
        if sym_pos:
            current_qty = int(sym_pos.get("quantity", 0))
            print(f"[初始化] {SYMBOL} 当前持仓: {current_qty} 股")
            state["base_established"] = True
            state["base_qty"] = current_qty
            save_state(state, SYMBOL)
            print(f"[初始化] {SYMBOL} 底仓初始化完成")
        else:
            print(f"[初始化] {SYMBOL} 无持仓")


    elif cmd == "buy_check":
        do_buy_check(SYMBOL, state, CONFIG)

    elif cmd == "sell_check":
        do_sell_check(SYMBOL, state, CONFIG)


    elif cmd == "status":
        show_status(SYMBOL, state, CONFIG)


if __name__ == "__main__":
    main()
