"""
飞书 Webhook 通知渠道（美股策略自包含版本）

不依赖 common 模块，所有渠道实现内嵌于此文件。
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

# 默认飞书 Webhook
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
            logger.debug("[飞书] 未配置 Webhook")
            return False
        try:
            payload = {"msg_type": "text", "content": {"text": text}}
            resp = requests.post(self.webhook, json=payload, timeout=10)
            result = resp.json()
            success = result.get("code") == 0 or result.get("StatusCode") == 0
            if not success:
                logger.warning(f"[飞书] 发送失败: {result}")
            return success
        except Exception as e:
            logger.error(f"[飞书] 发送异常: {e}")
            return False

    def send_card(self, card: Dict) -> bool:
        if not self.available:
            logger.debug("[飞书] 未配置 Webhook")
            return False
        try:
            resp = requests.post(self.webhook, json=card, timeout=10)
            result = resp.json()
            success = result.get("code") == 0 or result.get("StatusCode") == 0
            if not success:
                logger.warning(f"[飞书] 发送失败: {result}")
            return success
        except Exception as e:
            logger.error(f"[飞书] 发送异常: {e}")
            return False

    def format_message(self, title: str, content: str, color: str = "blue") -> Dict:
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": color
                },
                "elements": [
                    {"tag": "markdown", "content": content},
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {"tag": "plain_text",
                             "content": f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 自动通知"}
                        ]
                    }
                ]
            }
        }


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
            logger.debug("[微信] 未配置 target，跳过发送")
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
        text = self._card_to_text(card)
        return self._enqueue({"msg_type": "text", "content": text})

    def _card_to_text(self, card: Dict) -> str:
        lines = []
        card_data = card.get("card", card)
        header = card_data.get("header", {})
        if header:
            title = header.get("title", {}).get("content", "")
            if title:
                lines.append(f"【{title}】")
                lines.append("")
        elements = card_data.get("elements", [])
        for elem in elements:
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
    """飞书卡片构建器（美股策略自包含版本）"""

    def __init__(self, title: str = "", color: str = "blue"):
        self.title = title
        self.color = color
        self.elements: List[Dict] = []
        self.header: Dict = {}

    def add_header(self, title: str, color: str = "blue") -> "FeishuCardBuilder":
        self.header = {
            "title": {"tag": "plain_text", "content": title},
            "template": color
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
        if self.header and not self.title:
            card["card"]["header"] = self.header
        if self.elements:
            card["card"]["elements"] = self.elements
        return card


# ============================================================
# 多渠道通知管理器（美股策略自包含版本）
# ============================================================

class NotificationManager:
    """美股策略多渠道通知管理器"""

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
        self._build_channels()

    def _build_channels(self):
        self.channels = {}
        if "feishu" in self.default_channels:
            try:
                self.channels["feishu"] = FeishuChannel(
                    webhook=self._feishu_webhook or DEFAULT_FEISHU_WEBHOOK
                )
            except Exception as e:
                logger.error(f"[通知] 初始化飞书渠道失败: {e}")
        if "weixin" in self.default_channels:
            try:
                self.channels["weixin"] = WeixinChannel(
                    target=self._weixin_target,
                    account_id=self._weixin_account_id
                )
            except Exception as e:
                logger.error(f"[通知] 初始化微信渠道失败: {e}")

    def _get_channels(self, channels: List[str] = None) -> Dict[str, Any]:
        targets = channels or self.default_channels
        result = {}
        for name in targets:
            if name in self.channels:
                result[name] = self.channels[name]
                continue
            try:
                kwargs = {}
                if name == "feishu":
                    kwargs["webhook"] = self._feishu_webhook or DEFAULT_FEISHU_WEBHOOK
                elif name == "weixin":
                    kwargs["target"] = self._weixin_target
                    kwargs["account_id"] = self._weixin_account_id
                ch = self._create_channel(name, kwargs)
                if ch:
                    result[name] = ch
                    self.channels[name] = ch
            except Exception as e:
                logger.error(f"[通知] 初始化渠道 {name} 失败: {e}")
        return result

    def _create_channel(self, name: str, kwargs: Dict) -> Optional[Any]:
        if name == "feishu":
            return FeishuChannel(**kwargs)
        elif name == "weixin":
            return WeixinChannel(**kwargs)
        return None

    def send_text(self, text: str, channels: List[str] = None) -> bool:
        if not self.enabled:
            return False
        targets = self._get_channels(channels)
        if not targets:
            return False
        any_ok = False
        for name, ch in targets.items():
            try:
                ok = ch.send_text(text)
                if ok:
                    any_ok = True
                    logger.info(f"[通知] [{name}] 发送成功")
                else:
                    logger.warning(f"[通知] [{name}] 发送失败")
            except Exception as e:
                logger.error(f"[通知] [{name}] 异常: {e}")
        return any_ok

    def send_card(self, card: Dict, channels: List[str] = None) -> bool:
        if not self.enabled:
            return False
        targets = self._get_channels(channels)
        if not targets:
            return False
        any_ok = False
        for name, ch in targets.items():
            try:
                if hasattr(ch, "send_card"):
                    ok = ch.send_card(card)
                else:
                    ok = ch.send_text(self._card_to_text(card))
                if ok:
                    any_ok = True
                    logger.info(f"[通知] [{name}] 卡片发送成功")
                else:
                    logger.warning(f"[通知] [{name}] 卡片发送失败")
            except Exception as e:
                logger.error(f"[通知] [{name}] 异常: {e}")
        return any_ok

    def _card_to_text(self, card: Dict) -> str:
        builder = FeishuCardBuilder()
        lines = []
        card_data = card.get("card", card)
        header = card_data.get("header", {})
        if header:
            title = header.get("title", {}).get("content", "")
            if title:
                lines.append(f"【{title}】")
                lines.append("")
        elements = card_data.get("elements", [])
        for elem in elements:
            tag = elem.get("tag", "")
            if tag == "markdown":
                lines.append(elem.get("content", ""))
            elif tag == "note":
                for ne in elem.get("elements", []):
                    lines.append(ne.get("content", ""))
        return "\n".join(lines)


# ============================================================
# 全局接口
# ============================================================

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


def is_enabled() -> bool:
    return _enabled


def send(text: str, webhook: str = None, enabled: bool = None, channels: List[str] = None) -> bool:
    if enabled is False or (enabled is None and not _enabled):
        return False
    if webhook:
        try:
            ch = FeishuChannel(webhook=webhook)
            return ch.send_text(text)
        except Exception as e:
            logger.error(f"[通知] 发送失败: {e}")
            return False
    return _manager.send_text(text, channels=channels)


def send_card(card: Dict, webhook: str = None, enabled: bool = None, channels: List[str] = None) -> bool:
    if enabled is False or (enabled is None and not _enabled):
        return False
    if webhook:
        try:
            ch = FeishuChannel(webhook=webhook)
            return ch.send_card(card)
        except Exception as e:
            logger.error(f"[通知] 发送失败: {e}")
            return False
    return _manager.send_card(card, channels=channels)


def build_trade_card(
    symbol: str, name: str, action: str, price: float, qty: int,
    order_id: str = "", extra_info: Dict = None,
    strategy_name: str = "美股定投策略"
) -> Dict:
    action_text = "买入" if action == "BUY" else "卖出"
    color = "green" if action == "BUY" else "red"
    builder = FeishuCardBuilder(
        title=f"[{strategy_name}] {action_text} - {symbol} ({name})", color=color
    )
    builder.add_key_value("交易方向", f"**{action_text}**")
    builder.add_key_value("成交价格", f"`${price:.2f}`")
    builder.add_key_value("成交数量", f"`{qty}` 股")
    builder.add_key_value("订单ID", f"`{order_id or 'N/A'}`")
    if extra_info:
        builder.add_divider()
        for k, v in extra_info.items():
            builder.add_key_value(str(k), str(v))
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy_name} | 自动通知")
    return builder.build()


def send_trade(
    data: Dict, webhook: str = None, enabled: bool = None,
    channels: List[str] = None, strategy_name: str = "美股定投策略"
) -> bool:
    if enabled is False or (enabled is None and not _enabled):
        return False
    card = build_trade_card(
        symbol=data.get("symbol", ""),
        name=data.get("name", data.get("symbol", "")),
        action=data.get("action", "BUY"),
        price=data.get("price", 0),
        qty=data.get("qty", 0),
        order_id=data.get("order_id", ""),
        extra_info=data.get("extra"),
        strategy_name=strategy_name
    )
    return send_card(card, webhook=webhook, channels=channels)


def build_profit_card(
    symbol: str, name: str, buy_price: float, sell_price: float, qty: int,
    buy_date: str = "", sell_date: str = "",
    strategy_name: str = "美股定投策略"
) -> Dict:
    profit_amount = (sell_price - buy_price) * qty
    profit_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    is_profit = profit_amount >= 0
    color = "green" if is_profit else "red"
    emoji = "🟢" if is_profit else "🔴"
    builder = FeishuCardBuilder(
        title=f"[{strategy_name}] 卖出 - {symbol} ({name})", color=color
    )
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
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy_name} | 自动通知")
    return builder.build()


def send_profit(
    data: Dict, webhook: str = None, enabled: bool = None,
    channels: List[str] = None, strategy_name: str = "美股定投策略"
) -> bool:
    if enabled is False or (enabled is None and not _enabled):
        return False
    card = build_profit_card(
        symbol=data.get("symbol", ""),
        name=data.get("name", data.get("symbol", "")),
        buy_price=data.get("buy_price", 0),
        sell_price=data.get("sell_price", 0),
        qty=data.get("qty", 0),
        buy_date=data.get("buy_date", ""),
        sell_date=data.get("sell_date", ""),
        strategy_name=strategy_name
    )
    return send_card(card, webhook=webhook, channels=channels)


def build_status_card(
    title: str, content: str, color: str = "blue",
    strategy_name: str = "美股定投策略"
) -> Dict:
    builder = FeishuCardBuilder(title=title, color=color)
    builder.add_markdown(content)
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy_name} | 自动通知")
    return builder.build()


def send_status(
    title: str, content: str, webhook: str = None, enabled: bool = None,
    color: str = "blue", channels: List[str] = None,
    strategy_name: str = "美股定投策略"
) -> bool:
    if enabled is False or (enabled is None and not _enabled):
        return False
    card = build_status_card(title=title, content=content, color=color, strategy_name=strategy_name)
    return send_card(card, webhook=webhook, channels=channels)


def build_positions_card(
    positions=None, account_info=None, open_orders=None, prices=None,
    strategy_name: str = "美股定投策略",
    total_assets: float = 0, cash: float = 0,
    total_market_value: float = None,
    position_ratio: float = None,
    daily_pnl: float = None, daily_pnl_pct: float = None,
    daily_pnl_emoji: str = "🟢", daily_pnl_sign: str = "+",
    order_count: int = None, open_orders_text: str = None,
    position_count: int = None, position_details_content: str = None,
    date: str = None, timestamp: str = None,
    color: str = None, **kwargs
) -> Dict:
    """
    构建持仓报告卡片

    优先使用传入的模板变量，否则自动计算。
    """
    from datetime import datetime as _dt

    now = _dt.now()
    date_str = date or now.strftime("%Y年%m月%d日")
    ts = timestamp or now.strftime("%Y-%m-%d %H:%M:%S")

    # 自动计算
    _total_assets = total_assets or (account_info.get("total_assets", 0) if account_info else 0)
    _cash = cash or (account_info.get("cash", 0) if account_info else 0)
    _total_mv = total_market_value or 0
    _daily_pnl = daily_pnl or 0
    _daily_pnl_pct = daily_pnl_pct or 0
    _pos_count = position_count or (len(positions) if positions else 0)
    _order_count = order_count or (len(open_orders) if open_orders else 0)
    _color = color or ("green" if _daily_pnl >= 0 else "red")
    _pos_ratio = position_ratio or (_total_mv / _total_assets * 100 if _total_assets > 0 else 0)

    # 持仓明细
    position_lines = []
    if position_details_content:
        position_lines = position_details_content.split("\n") if isinstance(position_details_content, str) else []
    elif positions:
        for pos in positions:
            sym = pos.get("symbol", "")
            qty = pos.get("qty", 0)
            cost = pos.get("cost_price", 0)
            price_info = (prices or {}).get(sym, {})
            last_price = price_info.get("last_price", 0) or pos.get("last_price", 0)
            if not last_price:
                mv = pos.get("market_value", 0)
                last_price = mv / qty if qty > 0 else 0
            profit = (last_price - cost) * qty if cost > 0 else 0
            profit_pct = (last_price - cost) / cost * 100 if cost > 0 else 0
            _profit_emoji = "🟢" if profit >= 0 else "🔴"
            _profit_sign = "+" if profit >= 0 else ""
            _total_mv += last_price * qty
            _daily_pnl += profit
            position_lines.append(
                f"{_profit_emoji} {sym}\n  持仓: {qty}股 | "
                f"成本${cost:.2f} | 现价${last_price:.2f} "
                f"({_profit_sign}{profit_pct:.1f}%) 盈亏{_profit_sign}${int(round(profit))}"
            )

    # 挂单
    order_lines = []
    if open_orders:
        for o in open_orders:
            sym = o.get("symbol", "???")
            action_text = "买入" if o.get("action") == "BUY" else "卖出" if o.get("action") == "SELL" else o.get("action", "")
            qty = o.get("quantity", 0) - o.get("filled_qty", 0)
            price = o.get("price", 0)
            price_str = f"${price:.2f}" if price > 0 else "市价"
            order_lines.append(f"  {action_text} {sym} {qty}股 @ {price_str}")

    order_text = open_orders_text or ("(0笔)" if not order_lines else "\n".join(order_lines))

    # 重新计算盈亏颜色
    _daily_pnl_emoji = daily_pnl_emoji or ("🟢" if _daily_pnl >= 0 else "🔴")
    _daily_pnl_sign = daily_pnl_sign or ("+" if _daily_pnl >= 0 else "")
    _color = color or ("green" if _daily_pnl >= 0 else "red")

    content = f"""📊 **账户总览**

💰 总资产: `${_total_assets:,.2f}`
💵 可用现金: `${_cash:,.2f}`
📈 持仓市值: `${_total_mv:,.2f}` ({_pos_ratio:.1f}%)

📉 持仓盈亏: {_daily_pnl_emoji} `{_daily_pnl_sign}${_daily_pnl:,.2f}` ({_daily_pnl_sign}{_daily_pnl_pct:.2f}%)
📋 活跃挂单: `{_order_count}` 笔"""

    if order_lines:
        content += f"\n{order_text}"

    if position_lines:
        content += f"\n\n📋 **持仓明细** ({_pos_count}只)\n" + "\n".join(position_lines)
    else:
        content += "\n\n⚠️ 当前无持仓"

    builder = FeishuCardBuilder(title=f"[{strategy_name}] 持仓报告", color=_color)
    builder.add_markdown(content)
    builder.add_divider()
    builder.add_note(f"{ts} | {strategy_name} | 自动通知")
    return builder.build()


def build_error_card(
    title: str, error: str, context: str = "",
    color: str = "red", strategy_name: str = "美股定投策略"
) -> Dict:
    builder = FeishuCardBuilder(title=title, color=color)
    builder.add_markdown(f"**错误类型**: `{context or 'Unknown'}`")
    builder.add_markdown(f"**错误信息**: ```{error}```")
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {strategy_name} | 自动通知")
    return builder.build()


def send_error(
    title: str, error: str, context: str = "",
    webhook: str = None, enabled: bool = None,
    channels: List[str] = None, strategy_name: str = "美股定投策略"
) -> bool:
    if enabled is False or (enabled is None and not _enabled):
        return False
    card = build_error_card(title=title, error=error, context=context, strategy_name=strategy_name)
    return send_card(card, webhook=webhook, channels=channels)


# ============================================================
# 策略级配置
# ============================================================

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


if __name__ == "__main__":
    print("通知模块测试（未实际发送）")
    print(f"飞书渠道可用: {FeishuChannel().is_available()}")
    print(f"微信渠道可用: {WeixinChannel().is_available()}")
