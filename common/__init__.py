# -*- coding: utf-8 -*-
"""
D:\workspace\QClaw\common
飞书推送公共模块

使用方法:
    from common import send, FeishuCardBuilder
    
    # 方式1：直接发送文本
    send("消息内容", title="标题", card=True)
    
    # 方式2：构建卡片后发送
    builder = FeishuCardBuilder(title="标题", color="blue")
    builder.add_markdown("**加粗文本**\n\n内容")
    builder.add_divider()
    builder.add_note("备注")
    send(card_dict=builder.build())
    
    # 交易通知
    from common import send_trade
    send_trade(symbol="LITE", name="Lumentum", action="BUY", price=75.5, qty=10)
    
    # 持仓报告
    from common import send_positions
    send_positions(positions=[...], total_assets=10000, cash=5000, ...)
"""

from .notification import (
    # 核心函数
    send,
    send_text,
    send_card,
    
    # 便捷函数
    send_trade,
    send_positions,
    send_error,
    send_stock_news,
    
    # 卡片构建器
    FeishuCardBuilder,
    
    # 配置
    get_webhook,
    set_webhook,
    set_webhook_by_name,
    DEFAULT_WEBHOOK,
)

__all__ = [
    "send",
    "send_text",
    "send_card",
    "send_trade",
    "send_positions",
    "send_error",
    "send_stock_news",
    "FeishuCardBuilder",
    "get_webhook",
    "set_webhook",
    "set_webhook_by_name",
    "DEFAULT_WEBHOOK",
]

__version__ = "1.0.0"
