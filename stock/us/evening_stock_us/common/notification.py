"""
通知模块 - 美股（飞书 + 微信）
"""
import os
import json
import requests
from datetime import datetime

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/89a829de-fc60-4a7c-ade0-e4a422e9434b"
WEIXIN_TARGET = "o9cq80-aiozlTjCmF5CjVtM5Mhyw@im.wechat"

class FeishuCardBuilder:
    def __init__(self, title="", color="blue"):
        self.title = title
        self.color = color
        self.elements = []
        self.header = None
        if title:
            color_map = {"green": "0", "red": "1", "yellow": "2", "blue": "3", "purple": "4", "gray": "5", "orange": "6"}
            self.header = {
                "title": {"tag": "plain_text", "content": title},
                "template": color_map.get(color, "3")
            }

    def add_key_value(self, key, value):
        self.elements.append({
            "tag": "markdown",
            "content": f"**{key}**: {value}"
        })
        return self

    def add_divider(self):
        self.elements.append({"tag": "hr"})
        return self

    def add_note(self, text):
        self.elements.append({
            "tag": "markdown",
            "content": f"<note>{text}</note>"
        })
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

def build_status_card(title, content, color="blue"):
    builder = FeishuCardBuilder(title=title, color=color)
    builder.add_markdown(content)
    return builder.build()

def send_card(card, enabled=True, channels=None):
    """发送飞书卡片"""
    if not enabled:
        return False
    channels = channels or ["feishu"]
    results = []
    if "feishu" in channels:
        try:
            resp = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
            results.append(("feishu", resp.status_code == 200))
        except Exception as e:
            print(f"[通知] 飞书发送失败: {e}")
            results.append(("feishu", False))
    return results

def create_config(webhook=None, enabled=True, channels=None, weixin_target=None, weixin_account_id=None):
    class NotifConfig:
        def __init__(self):
            self.enabled = enabled
            self.channels = channels or ["feishu"]
            self.weixin_target = weixin_target or WEIXIN_TARGET
    return NotifConfig()
