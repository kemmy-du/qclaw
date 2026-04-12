"""
A股模拟账户持仓报告 - 多渠道推送

用法:
  python push_positions_cn.py                       # 默认飞书
  python push_positions_cn.py --channels=feishu    # 仅飞书
  python push_positions_cn.py --channels=weixin    # 仅微信

每天下午16点自动发送持仓报告（参考 cron 定时任务）
"""

import sys
import os
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json

# 导入 CN common 通知模块
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PARENT)

from common.notification_cn import FeishuCardBuilder, send_card, init
import cn_sim_account as cn_sim


def parse_channels():
    for arg in sys.argv:
        if arg.startswith("--channels="):
            return [c.strip() for c in arg.split("=", 1)[1].split(",")]
    return None


def load_notification_config():
    config_path = os.path.join(_PARENT, "config.json")
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
                feishu_webhook=notify_cfg.get("feishu_webhook") or
                               config.get("global_defaults", {}).get("feishu_webhook"),
                enabled=True
            )
    except Exception as e:
        print(f"[通知] 加载配置失败: {e}")


def build_positions_context(now: datetime) -> dict:
    """构建持仓报告上下文"""
    account_info = cn_sim.get_account_info()
    positions = cn_sim.get_positions()

    total_assets = account_info.get("total_assets", 0)
    cash = account_info.get("cash", 0)
    initial_capital = account_info.get("initial_capital", 0)
    total_profit = account_info.get("total_profit", 0)
    profit_pct = account_info.get("profit_pct", 0)
    total_trades = account_info.get("total_trades", 0)
    win_trades = account_info.get("win_trades", 0)
    lose_trades = account_info.get("lose_trades", 0)
    total_market_value = sum(p.get("market_value", 0) for p in positions)
    position_ratio = (total_market_value / total_assets * 100) if total_assets > 0 else 0

    position_details = []
    for pos in positions:
        symbol = pos.get("symbol", "")
        name = pos.get("name", symbol)
        qty = pos.get("quantity", 0)
        avg_cost = pos.get("avg_cost", 0)
        current_price = pos.get("market_price", avg_cost)
        market_value = pos.get("market_value", 0)
        profit = (current_price - avg_cost) * qty if avg_cost > 0 else 0
        profit_pct_single = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
        profit_emoji = "🟢" if profit >= 0 else "🔴"
        profit_sign = "+" if profit >= 0 else ""

        position_details.append({
            "symbol": symbol,
            "name": name,
            "qty": qty,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "market_value": market_value,
            "profit": profit,
            "profit_pct": profit_pct_single,
            "profit_emoji": profit_emoji,
            "profit_sign": profit_sign,
        })

    daily_pnl_emoji = "🟢" if total_profit >= 0 else "🔴"
    daily_pnl_sign = "+" if total_profit >= 0 else ""
    color = "green" if total_profit >= 0 else "red"

    date_str = now.strftime("%Y年%m月%d日")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "strategy_name": "A股模拟账户",
        "date": date_str,
        "timestamp": timestamp,
        "color": color,
        "total_assets": total_assets,
        "cash": cash,
        "initial_capital": initial_capital,
        "total_market_value": total_market_value,
        "position_ratio": position_ratio,
        "daily_pnl": total_profit,
        "daily_pnl_pct": profit_pct,
        "daily_pnl_emoji": daily_pnl_emoji,
        "daily_pnl_sign": daily_pnl_sign,
        "total_trades": total_trades,
        "win_trades": win_trades,
        "lose_trades": lose_trades,
        "position_count": len(positions),
        "position_details": position_details,
    }


def send_notification(context: dict, channels=None) -> bool:
    """发送持仓报告"""
    pos_lines = []
    for p in context["position_details"]:
        pos_lines.append(
            f"{p['profit_emoji']} {p['symbol']} {p['name']}\n"
            f"  持仓: {p['qty']}股 | 成本¥{p['avg_cost']:.2f} | "
            f"现价¥{p['current_price']:.2f} ({p['profit_sign']}{p['profit_pct']:.1f}%) "
            f"盈亏{p['profit_sign']}¥{int(round(p['profit']))}"
        )

    content = f"""📊 **账户总览**

💰 初始资金: `¥{context['initial_capital']:,.0f}`
💵 可用现金: `¥{context['cash']:,.0f}`
📈 持仓市值: `¥{context['total_market_value']:,.0f}`
🏦 总资产:   `¥{context['total_assets']:,.0f}`

📉 累计盈亏: {context['daily_pnl_emoji']} {context['daily_pnl_sign']}¥{context['daily_pnl']:,.0f} ({context['daily_pnl_sign']}{context['daily_pnl_pct']:.2f}%)

📝 交易统计: {context['total_trades']} 次
   盈利: {context['win_trades']} 次 | 亏损: {context['lose_trades']} 次"""

    if pos_lines:
        content += f"\n\n📋 **持仓明细** ({context['position_count']}只)\n" + "\n\n".join(pos_lines)
    else:
        content += "\n\n⚠️ 当前无持仓"

    card = FeishuCardBuilder(
        title=f"[{context['strategy_name']}] 持仓报告",
        color=context["color"]
    )
    card.add_markdown(content)
    card.add_divider()
    card.add_note(f"{context['timestamp']} | A股定投策略 | 自动通知")

    return send_card(card.build(), channels=channels)


def main():
    channels = parse_channels()
    now = datetime.now()

    print(f"\n{'='*60}")
    print(f"A股模拟账户持仓报告 - {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if channels:
        print(f"通知渠道: {channels}")
    print(f"{'='*60}")

    print("\n[1] 获取账户信息...")
    context = build_positions_context(now)

    print(f"  总资产: ¥{context['total_assets']:,.0f}")
    print(f"  可用现金: ¥{context['cash']:,.0f}")
    print(f"  持仓市值: ¥{context['total_market_value']:,.0f}")
    print(f"  累计盈亏: {context['daily_pnl_emoji']} {context['daily_pnl_sign']}¥{context['daily_pnl']:,.0f}")
    print(f"  持仓数量: {context['position_count']}只")

    print(f"\n[2] 发送通知...")
    ok = send_notification(context, channels=channels)
    print(f"  {'发送成功' if ok else '发送失败'}")


if __name__ == "__main__":
    load_notification_config()
    main()
