# QClaw

个人股票投资工具集，包含A股/美股策略、资讯获取、飞书推送等模块。

## 目录结构

```
QClaw/
├── common/           # 公共模块
│   ├── __init__.py
│   └── notification.py  # 飞书推送模块
├── FinanceNews/       # A股个股资讯
│   ├── stock_news.py
│   ├── config.json
│   └── run_stock_news.bat
└── stock/            # 股票策略
    ├── cn/           # A股策略
    └── us/           # 美股策略
```

## 模块说明

### common / 飞书推送模块

统一管理飞书群 Webhook，所有模块发送消息使用此模块：

```python
import sys
sys.path.insert(0, r"D:\workspace\QClaw\common")
from notification import send, FeishuCardBuilder

# 发送文本
send("消息内容", title="标题", card=True)

# 构建卡片发送
builder = FeishuCardBuilder(title="标题", color="blue")
builder.add_markdown("**内容**")
send(card_dict=builder.build())
```

### FinanceNews / 个股资讯

获取A股个股新闻、公告、财务数据，推送到飞书群：

```bash
cd D:\workspace\QClaw\FinanceNews
run_stock_news.bat
```

## 环境变量

- `MX_APIKEY` - 东方财富妙想 API Key
