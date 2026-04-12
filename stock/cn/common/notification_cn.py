"""
A股通知模块 - 完全自包含版本（飞书 + 微信）

不依赖任何 common 模块，所有渠道实现内嵌于此文件。

用法:
    import notification_cn as notification

    notification.init(channels=["feishu"], feishu_webhook="https://...")

    builder = notification.FeishuCardBuilder(title="标题", color="green")
    builder.add_key_value("标的", "603773")
    builder.add_key_value("价格", "¥120.50")
    notification.send_card(builder.build())
"""

import sys
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import requests

logger = logging.getLogger(__name__)

DEFAULT_FEISHU_WEBHOOK = os.environ.get(
    "FEISHU_WEBHOOK",
    "https://open.feishu.cn/open-apis/bot/v2/hook/89a829de-fc60-4a7c-ade0-e4a422e9434b"
)
DEFAULT_CHANNELS = ["feishu"]

# ============================================================
# 飞书渠道
# ============================================================

class FeishuChannel:
    """飞书 Webhook 通知渠道"""

    name = "feishu"

    def __init__(self, webhook: str = None):
        self.webhook = webhook
        self.available = bool(webhook)

    def is_available(self) -> bool:
        return self.available

    def send_text(self, text: str) -> bool:
        if not self.available:
            return False
        try:
            payload = {"msg_type": "text", "content": {"text": text}}
            resp = requests.post(self.webhook, json=payload, timeout=10)
            result = resp.json()
            return result.get("code") == 0 or result.get("StatusCode") == 0
        except Exception as e:
            logger.error(f"[飞书] 发送异常: {e}")
            return False

    def send_card(self, card: Dict) -> bool:
        if not self.available:
            return False
        try:
            resp = requests.post(self.webhook, json=card, timeout=10)
            result = resp.json()
            return result.get("code") == 0 or result.get("StatusCode") == 0
        except Exception as e:
            logger.error(f"[飞书] 发送异常: {e}")
            return False


# ============================================================
# 微信渠道
# ============================================================

_QUEUE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".notification_queue")


class WeixinChannel:
    """微信通知渠道（通过 OpenClaw message 工具）"""

    name = "weixin"

    def __init__(self, target: str = None, account_id: str = None):
        self.target = target or os.environ.get("WEIXIN_DEFAULT_TARGET", "")
        self.account_id = account_id or os.environ.get("WEIXIN_DEFAULT_ACCOUNT_ID", "")
        self.available = bool(self.target)
        self._queue_dir = _QUEUE_DIR

    def is_available(self) -> bool:
        return self.available

    def _get_queue_dir(self) -> str:
        os.makedirs(self._queue_dir, exist_ok=True)
        return self._queue_dir

    def _enqueue(self, message_data: Dict) -> bool:
        if not self.available:
            return False
        try:
            queue_dir = self._get_queue_dir()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            queue_file = os.path.join(queue_dir, f"weixin_{ts}.json")
            payload = {
                "channel": "message",
                "type": "weixin",
                "target": self.target,
                "account_id": self.account_id,
                "data": message_data,
                "created_at": datetime.now().isoformat()
            }
            with open(queue_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(f"[微信] 消息已入队: {queue_file}")
            return True
        except Exception as e:
            logger.error(f"[微信] 入队失败: {e}")
            return False

    def send_text(self, text: str) -> bool:
        return self._enqueue({"msg_type": "text", "content": text})

    def send_card(self, card: Dict) -> bool:
        return self._enqueue({"msg_type": "text", "content": self._card_to_text(card)})

    def _card_to_text(self, card: Dict) -> str:
        lines = []
        card_data = card.get("card", card)
        header = card_data.get("header", {})
        if header:
            title = header.get("title", {}).get("content", "")
            if title:
                lines.append(f"【{title}】")
                lines.append("")
        for elem in card_data.get("elements", []):
            tag = elem.get("tag", "")
            if tag == "markdown":
                lines.append(elem.get("content", ""))
            elif tag == "note":
                for ne in elem.get("elements", []):
                    lines.append(ne.get("content", ""))
        return "\n".join(lines)


# ============================================================
# 飞书卡片构建器
# ============================================================

class FeishuCardBuilder:
    """飞书卡片构建器"""

    def __init__(self, title: str = "", color: str = "blue"):
        self.title = title
        self.color = color
        self.elements: List[Dict] = []
        self.header: Dict = {}

    def add_header(self, title: str, color: str = "blue") -> "FeishuCardBuilder":
        self.header = {"title": {"tag": "plain_text", "content": title}, "template": color}
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
        self.elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": content}]})
        return self

    def add_key_value(self, key: str, value: str) -> "FeishuCardBuilder":
        self.elements.append({"tag": "markdown", "content": f"**{key}**: {value}"})
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
        if self.header and not self.title:
            card["card"]["header"] = self.header
        if self.elements:
            card["card"]["elements"] = self.elements
        return card


# ============================================================
# 通知管理器
# ============================================================

class NotificationManager:
    """A股策略多渠道通知管理器"""

    def __init__(self):
        self.channels: Dict[str, Any] = {}
        self.enabled = True
        self.default_channels: List[str] = DEFAULT_CHANNELS.copy()
        self._feishu_webhook: Optional[str] = None
        self._weixin_target: Optional[str] = None
        self._weixin_account_id: Optional[str] = None

    def configure(self, **kwargs):
        if "channels" in kwargs:
            self.default_channels = kwargs["channels"]
        if "feishu_webhook" in kwargs:
            self._feishu_webhook = kwargs["feishu_webhook"]
        if "weixin_target" in kwargs:
            self._weixin_target = kwargs["weixin_target"]
        if "weixin_account_id" in kwargs:
            self._weixin_account_id = kwargs["weixin_account_id"]
        if "enabled" in kwargs:
            self.enabled = kwargs["enabled"]

    def _get_channels(self, channels: List[str] = None) -> Dict[str, Any]:
        targets = channels or self.default_channels
        result = {}
        for name in targets:
            if name in self.channels:
                result[name] = self.channels[name]
                continue
            try:
                if name == "feishu":
                    ch = FeishuChannel(webhook=self._feishu_webhook or DEFAULT_FEISHU_WEBHOOK)
                elif name == "weixin":
                    ch = WeixinChannel(target=self._weixin_target,
                                       account_id=self._weixin_account_id)
                else:
                    continue
                self.channels[name] = ch
                result[name] = ch
            except Exception as e:
                logger.error(f"[通知] 初始化渠道 {name} 失败: {e}")
        return result

    def send_text(self, text: str, channels: List[str] = None) -> bool:
        if not self.enabled:
            return False
        any_ok = False
        for name, ch in self._get_channels(channels).items():
            try:
                ok = ch.send_text(text)
                if ok:
                    any_ok = True
                    logger.info(f"[通知] [{name}] 发送成功")
            except Exception as e:
                logger.error(f"[通知] [{name}] 异常: {e}")
        return any_ok

    def send_card(self, card: Dict, channels: List[str] = None) -> bool:
        if not self.enabled:
            return False
        any_ok = False
        for name, ch in self._get_channels(channels).items():
            try:
                ok = ch.send_card(card) if hasattr(ch, "send_card") else ch.send_text(str(card))
                if ok:
                    any_ok = True
                    logger.info(f"[通知] [{name}] 卡片发送成功")
            except Exception as e:
                logger.error(f"[通知] [{name}] 异常: {e}")
        return any_ok


_manager = NotificationManager()
_enabled = True


def init(channels: List[str] = None, webhook: str = None, enabled: bool = True,
         feishu_webhook: str = None, weixin_target: str = None,
         weixin_account_id: str = None):
    global _enabled
    _enabled = enabled
    _manager.configure(
        channels=channels or DEFAULT_CHANNELS,
        feishu_webhook=feishu_webhook or webhook,
        weixin_target=weixin_target,
        weixin_account_id=weixin_account_id,
        enabled=enabled
    )


def send_card(card: Dict, enabled: bool = None, channels: List[str] = None) -> bool:
    if enabled is False or (enabled is None and not _enabled):
        return False
    return _manager.send_card(card, channels=channels)


def send_text(text: str, enabled: bool = None, channels: List[str] = None) -> bool:
    if enabled is False or (enabled is None and not _enabled):
        return False
    return _manager.send_text(text, channels=channels)


def build_status_card(title: str, content: str, color: str = "blue",
                      strategy_name: str = "A股定投策略") -> Dict:
    builder = FeishuCardBuilder(title=title, color=color)
    builder.add_markdown(content)
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy_name} | 自动通知")
    return builder.build()


def build_trade_card(symbol: str, name: str, action: str, price: float,
                     qty: int, order_id: str = "", extra_info: Dict = None,
                     strategy_name: str = "A股定投策略") -> Dict:
    action_text = "买入" if action == "BUY" else "卖出"
    color = "green" if action == "BUY" else "red"
    builder = FeishuCardBuilder(title=f"[{strategy_name}] {action_text} - {symbol} ({name})", color=color)
    builder.add_key_value("交易方向", f"**{action_text}**")
    builder.add_key_value("成交价格", f"`¥{price:.2f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    builder.add_key_value("订单ID", f"`{order_id or 'N/A'}`")
    if extra_info:
        builder.add_divider()
        for k, v in extra_info.items():
            builder.add_key_value(str(k), str(v))
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy_name} | 自动通知")
    return builder.build()


def build_profit_card(symbol: str, name: str, buy_price: float, sell_price: float,
                      qty: int, buy_date: str = "", sell_date: str = "",
                      strategy_name: str = "A股定投策略") -> Dict:
    profit_amount = (sell_price - buy_price) * qty
    profit_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    is_profit = profit_amount >= 0
    color = "green" if is_profit else "red"
    emoji = "🟢" if is_profit else "🔴"
    builder = FeishuCardBuilder(title=f"[{strategy_name}] 卖出 - {symbol} ({name})", color=color)
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
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy_name} | 自动通知")
    return builder.build()


def build_error_card(title: str, error: str, context: str = "",
                     color: str = "red", strategy_name: str = "A股定投策略") -> Dict:
    builder = FeishuCardBuilder(title=title, color=color)
    builder.add_markdown(f"**错误类型**: `{context or 'Unknown'}`")
    builder.add_markdown(f"**错误信息**: ```{error}```")
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy_name} | 自动通知")
    return builder.build()


class NotificationConfig:
    def __init__(self, webhook: str = None, enabled: bool = True,
                 channels: List[str] = None, feishu_webhook: str = None,
                 weixin_target: str = None, weixin_account_id: str = None):
        self.webhook = webhook or feishu_webhook
        self.enabled = enabled
        self.channels = channels or DEFAULT_CHANNELS
        self.feishu_webhook = feishu_webhook or webhook
        self.weixin_target = weixin_target
        self.weixin_account_id = weixin_account_id


def create_config(**kwargs) -> NotificationConfig:
    return NotificationConfig(**kwargs)


# 模块初始化
init()
