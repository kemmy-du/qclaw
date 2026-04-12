# -*- coding: utf-8 -*-
"""
个股信息动态获取脚本
功能：获取个股新闻、公告、财务数据，推送到飞书群
"""
import sys
import os

# Windows 下设置 UTF-8 输出
if sys.platform == "win32":
    import io
    try:
        if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'buffer') and not isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass  # 忽略重定向错误

import json
import requests
from datetime import datetime

# 飞书推送公共模块
sys.path.insert(0, r"D:\workspace\QClaw\common")
from notification import send, FeishuCardBuilder, get_webhook

# 配置
MX_APIKEY = os.environ.get("MX_APIKEY", "")
OUTPUT_DIR = r"D:\workspace\QClaw\FinanceNews\output"
CONFIG_FILE = r"D:\workspace\QClaw\FinanceNews\config.json"

def load_config():
    """加载配置文件"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"stocks": [], "feishu_webhook": ""}

def save_config(config):
    """保存配置文件"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

def search_news(query, limit=5):
    """使用妙想搜索获取资讯"""
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/news-search"
    headers = {
        "apikey": MX_APIKEY,
        "Content-Type": "application/json"
    }
    data = {
        "query": query
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        result = resp.json()
        
        # 解析正确的返回结构
        if result.get("code") == 0 or result.get("success"):
            data = result.get("data", {})
            if isinstance(data, dict):
                inner = data.get("data", {})
                if isinstance(inner, dict):
                    llm_resp = inner.get("llmSearchResponse", {})
                    return llm_resp.get("data", [])
            return []
        else:
            print(f"搜索失败: {result.get('message', result)}")
            return []
    except Exception as e:
        print(f"请求异常: {e}")
        return []

def get_financial_data(stock_name, stock_code):
    """获取个股财务数据（使用 mx-data skill）"""
    import subprocess
    
    # mx-data 脚本路径
    mx_data_script = os.path.join(os.path.expanduser("~"), ".openclaw", "workspace", "skills", "mx-data", "mx_data.py")
    
    if not os.path.exists(mx_data_script):
        return "（mx-data 脚本未找到）"
    
    # 查询财务数据
    query = f"{stock_name} 近一年 净利润 营业收入 每股收益 净资产收益率"
    
    try:
        result = subprocess.run(
            ["python", mx_data_script, query, OUTPUT_DIR],
            capture_output=True,
            timeout=60,
            env={**os.environ, "MX_APIKEY": MX_APIKEY},
            encoding='utf-8',
            errors='replace'
        )
        
        # 解析输出，读取生成的 description 文件
        import glob
        pattern = os.path.join(OUTPUT_DIR, "mx_data_*_description.txt")
        files = glob.glob(pattern)
        
        if files:
            # 读取最新的 description 文件
            latest = max(files, key=os.path.getmtime)
            with open(latest, "r", encoding="utf-8") as f:
                content = f.read()
            # 截取关键财务数据
            lines = content.split("\n")
            key_lines = [l for l in lines if any(k in l for k in ["净利润", "营收", "每股收益", "净资产收益率", "毛利率", "净利率"])]
            if key_lines:
                return "\n  ".join(key_lines[:5])
            return content[:200] if content else "（无数据）"
        else:
            return "（未获取到财务数据）"
    except Exception as e:
        return f"（财务数据获取失败: {e}）"

def format_stock_news(stock_name, stock_code):
    """格式化个股资讯输出"""
    results = []
    
    # 1. 获取新闻
    news = search_news(f"{stock_name} 最新新闻")
    if news:
        results.append(f"📰 【{stock_name} ({stock_code}) 最新新闻】")
        for i, item in enumerate(news[:3], 1):
            title = item.get("title", "")
            date = item.get("publishTime", "")[:10] if item.get("publishTime") else ""
            results.append(f"  {i}. {title} ({date})")
        results.append("")
    
    # 2. 获取公告
    announcements = search_news(f"{stock_name} 公告")
    if announcements:
        results.append(f"📋 【{stock_name} 公告】")
        for i, item in enumerate(announcements[:3], 1):
            title = item.get("title", "")
            results.append(f"  {i}. {title}")
        results.append("")
    
    # 3. 财务数据（使用 mx-data skill）
    results.append(f"💰 【{stock_name} 财务数据】")
    fin_data = get_financial_data(stock_name, stock_code)
    results.append(f"  {fin_data}")
    results.append("")
    
    return "\n".join(results)

def push_to_feishu(card_content: str, webhook: str = None) -> bool:
    """推送到飞书群（使用公共模块）"""
    # 构建卡片
    builder = FeishuCardBuilder(title="📈 个股资讯日报", color="blue")
    builder.add_markdown(card_content)
    builder.add_divider()
    builder.add_note(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 个股资讯 | 自动推送")
    
    # 使用公共模块发送
    return send(card_dict=builder.build(), webhook=webhook)

def main(stocks=None, webhook=None):
    """
    主函数
    stocks: 股票列表，如 [{"name": "茅台", "code": "600519"}]
    webhook: 飞书群 Webhook URL
    """
    # 加载配置
    config = load_config()
    
    if not stocks:
        stocks = config.get("stocks", [])
    
    # 获取飞书 webhook
    webhook = webhook or config.get("feishu_webhook") or FEISHU_WEBHOOK
    
    if not stocks:
        print("请在 config.json 中配置要查询的股票列表")
        print('格式: {"stocks": [{"name": "贵州茅台", "code": "600519"}]}')
        return
    
    print(f"📊 开始获取 {len(stocks)} 只股票的资讯...")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    all_results = []
    for stock in stocks:
        if isinstance(stock, dict):
            name = stock.get("name", "")
            code = stock.get("code", "")
        elif isinstance(stock, str) and "," in stock:
            name, code = stock.split(",")
        else:
            name, code = stock, ""
        
        print(f"🔍 查询: {name} ({code})")
        result = format_stock_news(name, code)
        all_results.append(result)
        print(result)
    
    # 汇总 - 卡片格式
    summary_lines = []
    for stock in stocks:
        if isinstance(stock, dict):
            name = stock.get("name", "")
            code = stock.get("code", "")
        elif isinstance(stock, str) and "," in stock:
            name, code = stock.split(",")
        else:
            name, code = stock, ""
        summary_lines.append(f"**{name} ({code})**")
        summary_lines.append("")
    
    card_content = "\n".join(summary_lines) + "\n\n".join(all_results)
    summary_text = f"个股资讯汇总\n{'='*40}\n\n" + "\n\n".join(all_results)
    
    # 保存到文件
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = os.path.join(OUTPUT_DIR, f"stock_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(summary_text)
    print(f"\n📁 已保存到: {output_file}")
    
    # 推送到飞书
    if webhook:
        print("\n📤 正在推送到飞书群...")
        if push_to_feishu(card_content):
            print("✅ 已推送到飞书群")
        else:
            print("❌ 飞书推送失败")
    else:
        print("\n💡 如需推送到飞书群，请配置:")
        print("   1. 设置环境变量: FEISHU_WEBHOOK=你的飞书机器人Webhook")
        print("   2. 或在 config.json 中添加 feishu_webhook 字段")
        print("\n   飞书机器人创建: 飞书群 -> 设置 -> 群机器人 -> 添加机器人 -> 自定义机器人")

if __name__ == "__main__":
    # 读取命令行参数或使用配置
    import argparse
    parser = argparse.ArgumentParser(description="个股资讯获取")
    parser.add_argument("--stocks", nargs="*", help="股票列表，如 贵州茅台,600519")
    parser.add_argument("--webhook", type=str, help="飞书群 Webhook URL")
    parser.add_argument("--config", action="store_true", help="编辑配置文件")
    args = parser.parse_args()
    
    if args.config:
        print(f"配置文件位置: {CONFIG_FILE}")
        print("请编辑配置文件添加股票和飞书 webhook")
    else:
        main(args.stocks, args.webhook)
