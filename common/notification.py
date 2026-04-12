# -*- coding: utf-8 -*-
"""
飞书推送公共模块
统一管理飞书群 Webhook，所有模块发送消息到飞书群时使用此模块

使用方式:
    import sys
    sys.path.insert(0, r"D:\workspace\QClaw\common")
    from notification import send, FeishuCardBuilder
    
    # 发送文本
    send("消息内容")
    
    # 发送卡片
    builder = FeishuCardBuilder(title="标题")
    builder.add_markdown("**内容**")
    send(card_dict=builder.build())
"""

import sys
import os
import json
import logging
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any, Union

# Windows UTF-8 输出
if sys.platform == "win32":
    import io
    try:
        if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'buffer') and not isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass  # 忽略重定向错误

logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================

# 默认飞书 Webhook（美股定投策略群）
DEFAULT_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/89a829de-fc60-4a7c-ade0-e4a422e9434b"

def get_webhook() -> str:
    """获取飞书 Webhook URL"""
    # 优先级：环境变量 > 默认配置
    webhook = os.environ.get("FEISHU_WEBHOOK", "")
    if webhook:
        return webhook
    return DEFAULT_WEBHOOK

def set_webhook(webhook: str):
    """设置飞书 Webhook URL"""
    os.environ["FEISHU_WEBHOOK"] = webhook
    logger.info(f"飞书 Webhook 已更新")

def set_webhook_by_name(name: str) -> bool:
    """
    通过名称切换预设的飞书群
    目前支持的群：
    - us / us_strategy / 美股定投 - 美股定投策略群
    """
    presets = {
        "us": DEFAULT_WEBHOOK,
        "us_strategy": DEFAULT_WEBHOOK,
        "美股定投": DEFAULT_WEBHOOK,
    }
    
    webhook = presets.get(name)
    if webhook:
        set_webhook(webhook)
        return True
    return False

# ============================================================
# 飞书卡片构建器
# ============================================================

class FeishuCardBuilder:
    """飞书卡片构建器"""

    COLORS = {
        "blue": "blue",
        "green": "green",
        "red": "red",
        "yellow": "yellow",
        "purple": "purple",
        "orange": "orange",
        "gray": "gray",
        "indigo": "indigo",
    }

    def __init__(self, title: str = "", color: str = "blue"):
        self.title = title
        self.color = self.COLORS.get(color, "blue")
        self.elements: List[Dict] = []
        self.header: Dict = {}

    def add_header(self, title: str, color: str = "blue") -> "FeishuCardBuilder":
        self.header = {
            "title": {"tag": "plain_text", "content": title},
            "template": self.COLORS.get(color, "blue")
        }
        return self

    def add_markdown(self, content: str) -> "FeishuCardBuilder":
        self.elements.append({"tag": "markdown", "content": content})
        return self

    def add_text(self, content: str) -> "FeishuCardBuilder":
        self.elements.append({"tag": "plain_text", "content": content})
        return self

    def add_divider(self) -> "FeishuCardBuilder":
        self.elements.append({"tag": "hr"})
        return self

    def add_note(self, content: str) -> "FeishuCardBuilder":
        self.elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": content}]
        })
        return self

    def add_key_value(self, key: str, value: str) -> "FeishuCardBuilder":
        self.elements.append({
            "tag": "markdown",
            "content": f"**{key}**: {value}"
        })
        return self

    def add_table(self, headers: List[str], rows: List[List[str]]) -> "FeishuCardBuilder":
        table_content = "| " + " | ".join(headers) + " |\n"
        table_content += "| " + " | ".join(["---"] * len(headers)) + " |\n"
        for row in rows:
            table_content += "| " + " | ".join(str(c) for c in row) + " |\n"
        self.elements.append({"tag": "markdown", "content": table_content})
        return self

    def build(self) -> Dict:
        card = {"msg_type": "interactive", "card": {}}
        if self.title:
            card["card"]["header"] = {
                "title": {"tag": "plain_text", "content": self.title},
                "template": self.color
            }
        elif self.header:
            card["card"]["header"] = self.header
        if self.elements:
            card["card"]["elements"] = self.elements
        return card


# ============================================================
# 飞书推送核心函数
# ============================================================

def send_text(text: str, webhook: str = None) -> bool:
    """发送文本消息到飞书群"""
    url = webhook or get_webhook()
    try:
        payload = {
            "msg_type": "text",
            "content": {"text": text}
        }
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        success = result.get("code") == 0 or result.get("StatusCode") == 0
        if success:
            logger.info("[飞书] 文本消息发送成功")
        else:
            logger.warning(f"[飞书] 发送失败: {result}")
        return success
    except Exception as e:
        logger.error(f"[飞书] 发送异常: {e}")
        return False


def send_card(card: Dict, webhook: str = None) -> bool:
    """发送卡片消息到飞书群"""
    url = webhook or get_webhook()
    try:
        resp = requests.post(url, json=card, timeout=10)
        result = resp.json()
        success = result.get("code") == 0 or result.get("StatusCode") == 0
        if success:
            logger.info("[飞书] 卡片消息发送成功")
        else:
            logger.warning(f"[飞书] 卡片发送失败: {result}")
        return success
    except Exception as e:
        logger.error(f"[飞书] 卡片发送异常: {e}")
        return False


def send(
    content: str = "",
    title: str = "",
    card: bool = False,
    color: str = "blue",
    webhook: str = None,
    footer: str = "",
    card_dict: Dict = None  # 支持直接传入卡片字典
) -> bool:
    """
    统一的发送接口

    Args:
        content: 消息内容（支持 Markdown）
        title: 卡片标题
        card: 是否使用卡片格式
        color: 卡片颜色（blue/green/red/yellow/purple）
        webhook: 可选，指定 Webhook URL
        footer: 卡片底部备注
        card_dict: 直接传入卡片字典

    Returns:
        bool: 是否发送成功
    """
    # 如果直接传入了卡片字典，直接发送
    if card_dict:
        return send_card(card_dict, webhook)

    if not card:
        # 纯文本模式
        return send_text(content, webhook)

    # 卡片模式
    if not title:
        title = "通知"

    if not footer:
        footer = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    builder = FeishuCardBuilder(title=title, color=color)
    builder.add_markdown(content)
    builder.add_divider()
    builder.add_note(footer)

    return send_card(builder.build(), webhook)


def send_trade(
    symbol: str,
    name: str,
    action: str,
    price: float,
    qty: int,
    order_id: str = "",
    extra_info: Dict = None,
    strategy: str = "交易通知",
    webhook: str = None
) -> bool:
    """发送交易通知卡片"""
    action_text = "买入" if action == "BUY" else "卖出"
    color = "green" if action == "BUY" else "red"

    builder = FeishuCardBuilder(
        title=f"[{strategy}] {action_text} - {symbol} ({name})",
        color=color
    )
    builder.add_key_value("交易方向", f"**{action_text}**")
    builder.add_key_value("成交价格", f"`${price:.2f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    if order_id:
        builder.add_key_value("订单ID", f"`{order_id}`")
    if extra_info:
        builder.add_divider()
        for k, v in extra_info.items():
            builder.add_key_value(str(k), str(v))
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy} | 自动通知")

    return send_card(builder.build(), webhook)


def send_positions(
    positions: List[Dict] = None,
    total_assets: float = 0,
    cash: float = 0,
    daily_pnl: float = 0,
    daily_pnl_pct: float = 0,
    open_orders: List[Dict] = None,
    strategy: str = "持仓报告",
    webhook: str = None
) -> bool:
    """发送持仓报告卡片"""
    positions = positions or []
    open_orders = open_orders or []

    is_profit = daily_pnl >= 0
    color = "green" if is_profit else "red"
    emoji = "🟢" if is_profit else "🔴"
    sign = "+" if is_profit else ""

    # 计算持仓市值和比例
    total_mv = 0
    position_lines = []
    for pos in positions:
        sym = pos.get("symbol", "")
        qty = pos.get("qty", 0)
        cost = pos.get("cost_price", 0)
        last_price = pos.get("last_price", 0)
        if not last_price:
            mv = pos.get("market_value", 0)
            last_price = mv / qty if qty > 0 else 0
        mv = last_price * qty
        total_mv += mv
        profit = (last_price - cost) * qty if cost > 0 else 0
        profit_pct = (last_price - cost) / cost * 100 if cost > 0 else 0
        pe = "🟢" if profit >= 0 else "🔴"
        position_lines.append(
            f"{pe} {sym}\n  持仓: {qty}股 | 成本${cost:.2f} | 现价${last_price:.2f} ({sign}{profit_pct:.1f}%)"
        )

    pos_ratio = total_mv / total_assets * 100 if total_assets > 0 else 0

    content = f"""💰 **账户总览**

总资产: `${total_assets:,.2f}`
💵 可用现金: `${cash:,.2f}`
📈 持仓市值: `${total_mv:,.2f}` ({pos_ratio:.1f}%)

📉 今日盈亏: {emoji} `{sign}${daily_pnl:,.2f}` ({sign}{daily_pnl_pct:.2f}%)
📋 活跃挂单: `{len(open_orders)}` 笔"""

    if positions:
        content += "\n\n📋 **持仓明细**\n" + "\n".join(position_lines)
    else:
        content += "\n\n⚠️ 当前无持仓"

    builder = FeishuCardBuilder(title=f"[{strategy}] 持仓报告", color=color)
    builder.add_markdown(content)
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy} | 自动通知")

    return send_card(builder.build(), webhook)


def send_error(
    title: str,
    error: str,
    context: str = "",
    strategy: str = "错误通知",
    webhook: str = None
) -> bool:
    """发送错误通知卡片"""
    builder = FeishuCardBuilder(title=title, color="red")
    builder.add_markdown(f"**错误类型**: `{context or 'Unknown'}`")
    builder.add_markdown(f"**错误信息**: ```{error}```")
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy} | 自动通知")

    return send_card(builder.build(), webhook)


def send_stock_news(
    stocks: List[Dict],
    news: Dict = None,
    announcements: Dict = None,
    financial: Dict = None,
    webhook: str = None
) -> bool:
    """发送个股资讯卡片"""
    builder = FeishuCardBuilder(title="📈 个股资讯日报", color="blue")

    content_parts = []

    for stock in stocks:
        name = stock.get("name", "")
        code = stock.get("code", "")
        content_parts.append(f"**{name} ({code})**")
        content_parts.append("")

        # 新闻
        stock_news = (news or {}).get(name, [])
        if stock_news:
            content_parts.append("📰 **最新新闻**")
            for item in stock_news[:3]:
                title = item.get("title", "")
                date = item.get("publishTime", "")
                if date:
                    date = date[:10]
                content_parts.append(f"• {title} {date}")
            content_parts.append("")

        # 公告
        stock_ann = (announcements or {}).get(name, [])
        if stock_ann:
            content_parts.append("📋 **公告**")
            for item in stock_ann[:3]:
                title = item.get("title", "")
                content_parts.append(f"• {title}")
            content_parts.append("")

    content = "\n".join(content_parts)
    builder.add_markdown(content)
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 个股资讯 | 自动推送")

    return send_card(builder.build(), webhook)


# ============================================================
# 模块测试
# ============================================================

if __name__ == "__main__":
    print("飞书推送模块测试")
    print(f"当前 Webhook: {get_webhook()}")

    # 测试发送
    print("\n发送测试消息...")
    result = send(
        content="✅ **飞书推送模块测试成功！**\n\n这是来自公共模块的测试消息。",
        title="🧪 模块测试",
        card=True
    )
    print(f"发送结果: {'成功' if result else '失败'}")

    # 测试交易卡片
    print("\n发送交易卡片测试...")
    result = send_trade(
        symbol="LITE",
        name="Lumentum",
        action="BUY",
        price=75.50,
        qty=10,
        order_id="TEST-001",
        strategy="测试策略"
    )
    print(f"发送结果: {'成功' if result else '失败'}")
