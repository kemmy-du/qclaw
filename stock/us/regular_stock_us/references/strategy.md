# EMA 趋势定投策略







> **适用市场**：美股（老虎证券）



> **核心思想**：趋势跟踪 + 网格补仓 + 底仓持有，震荡市稳盈，趋势市跟车







---







## 一、核心理念







**趋势是你的朋友。** 策略不预测价格，只跟随趋势。跌多了不盲目抄底（逆势），涨多了不恐高（顺势）。







---







## 二、仓位体系







### 2.1 底仓（Base Position）







- 目的：长期持有，熊市积累份额，牛市享受复利



- 管理方式：除非触发「盈利清仓线」，底仓永不卖出



- 重建：清仓后，下一次买入信号自动触发底仓初始化







### 2.2 浮动仓位（Batches）







- 目的：趋势行情中追加仓位，滚动操作



- 每批次独立记录：买入日期、价格、数量、信号类型、持仓天数



- **动态底仓**：持仓超过 `dynamic_base_days` 天的批次，自动升级为底仓（份额累加到底仓数量）







```



底仓 (Base)    ████████████████████  永不卖出



浮动批次#1     ████████  第3天卖出（短期止盈）



浮动批次#2     ██████████████  第8天 → 自动转为底仓



浮动批次#3     ████  第1天触发EMA突破买入



```







---







## 三、买入规则（优先级递减）







### 规则 0：底仓初始化（init_base）







账户无持仓时，**首个买入信号**直接建立底仓，不走批次逻辑。







### 规则 1：挂单捡漏（hang_order）







> 适合人群：不想盯盘、接受延迟成交、降低滑点









- 开盘前：挂限价买单（挂单价 = 昨收 × (1 − hang_drop_pct)）



- 收盘时：检查当天最低价是否 ≤ 挂单价



  - 是 → 成交 ✅



  - 否 → 撤销挂单，退回冻结资金 🔙







**美股规则（市价单）：**



- 实时监控，当现价跌至挂单价以下时立即市价买入



- **不依赖持仓**：捡漏本身就意味着买入，无需额外条件







### 规则 2：EMA 突破（ema_breakout）







> 目的：抓住调整后的向上突破







触发条件（同时满足）：



1. 现价 ≥ EMA13（当前已站上EMA）



2. 前 M 天所有收盘价 < EMA13（充分调整，未突破）



3. 前 N 天中有 ≥1 天收盘价 < EMA × (1 − 阈值)（明显回调）







```



   现价 ──────────────── ↑



  EMA13 ──────────────── ─────────────────── ↑



前M天   ████████████████  （全部在EMA下）



回调日  ██  （跌破阈值）



```







### 规则 3：EMA 回踩（ema_pullback）







> 目的：趋势中的逢低加仓







触发条件（同时满足）：



1. 前 M 天所有收盘价 > EMA13（趋势向上）



2. 前 N 天中有 ≥1 天收盘价 > EMA × (1 + 涨幅阈值)（明显上涨）



3. 当前价格在 EMA × (1 − 低) ~ EMA × (1 + 高) 区间内







```



前M天   ▲▲▲▲▲▲▲▲▲▲▲▲  （全部在EMA上）



涨幅日  ▲▲▲  （超过阈值）



回踩点  ↓  现价在EMA附近区间



```







### 规则 4：EMA 超跌（ema_oversold）







> 目的：极端行情下的恐慌买入







触发条件：



- 现价 ≤ EMA13 × (1 − oversold_mult)







**注意**：超跌信号不做交易，仅推送通知，提示关注。







---







## 四、卖出规则（优先级递减）







### 规则 1：盈利清仓（mega_profit）









- 操作：**全部清仓**（含底仓），重置状态



- 使用场景：牛市顶点、个股重大利好、策略退出







### 规则 2：EMA 高位卖出（ema_high_sell）







> 目的：高位减仓，锁定利润







触发条件（同时满足）：



1. 现价 ≥ EMA13 × (1 + ema_sell_high_multiplier)



2. 当前持仓盈利 ≥ `ema_high_sell_profit_pct`（默认 10%）



3. 当前价格 ≥ 上次卖出价 × (1 + price_increase_pct)（每次卖出价格递增，避免踏空）







卖出比例：`sell_position_pct`（默认 10%，即每次卖总持仓的10%）







### 规则 3：短期止盈（short_take_profit）







> 目的：快进快出，锁定短线收益







触发条件（同一批次）：



1. 持仓天数 ≤ `max_hold_days`（默认 2天）



2. 该批次盈利 ≥ `take_profit_short_pct`（默认 3%～5%）







**特点**：



- 卖出**该批次全部数量**，不卖底仓



- 满足条件的批次按顺序处理（从最早持有批次开始）







---







## 五、核心参数说明







| 参数 | 默认值 | 说明 |



|------|--------|------|



| base_position | 10 | 底仓股数 |



| trade_qty | 100 | 10 | 单次加仓股数 |



| mega_profit_pct | 0.10 | 1.0 | 盈利清仓线（盈利比例） |



| max_hold_days | 3 | 2 | 加仓批次最大持仓天数 |



| take_profit_short_pct | 0.03 | 0.05 | 短期止盈线（盈利比例） |



| ema_sell_high_multiplier | 0.20 | 0.20 | EMA 高位卖出系数 |



| ema_high_sell_profit_pct | 0.10 | 0.20 | EMA 高位卖出盈利阈值 |



| ema_high_sell_price_increase_pct | 0.05 | 0.10 | EMA 高位卖出价格递增阈值 |



| sell_position_pct | 0.10 | 0.10 | EMA 高位卖出比例 |



| hang_drop_pct | 0.05 | 0.08 | 挂单跌幅比例 |



| hang_qty | 100 | 10 | 挂单数量 |



| ema_period | 13 | 13 | EMA 均线周期 |



| dynamic_base_days | 20 | 20 | 动态底仓转换天数 |







------

## 六、数据来源

### A股（regular_stock_cn）

| 数据类型 | 数据源 | 说明 |
|---------|-------|------|
| 交易执行 | 本地模拟账户 | 无手续费，100股整数倍 |
| 行情数据 | 东方财富/emf_data | 日K线 |

### 美股（regular_stock_us）

| 数据类型 | 数据源 | 说明 |
|---------|-------|------|
| 实时报价 | Finnhub | 免费限额，延迟15min |
| 历史K线 | Polygon.io | 已复权日K |
| 公司信息 | Finnhub | 名称、行业等 |
| 交易执行 | 老虎证券 | 真实账户 |

---

## 七、通知体系

| 通知类型 | 触发时机 | 内容 |
|---------|---------|------|
| 买入通知 | 买入成交 | 标的、价格、数量、信号 |
| 卖出通知 | 卖出成交 | 标的、价格、数量、盈亏 |
| 挂单通知 | 挂单成功/成交/撤销 | 挂单价格、数量 |
| 持仓报告 | 每日定时 | 账户总览 + 持仓明细 |
| 错误通知 | API异常/交易失败 | 错误详情 |

---

## 八、文件结构

```
stock/                          # 定投策略根目录（A股+美股）
├── us/                         # 美股分支
│   └── regular_stock_us/      # 美股定投策略
│       ├── config.json         # 美股配置（标的 + 老虎账户）
│       ├── regular_stock_us.py # 美股主策略入口
│       ├── tiger_openapi_config.properties  # 老虎API认证
│       ├── common/             # 通用模块
│       │   ├── market_data_us.py
│       │   └── notification_us.py
│       └── scripts/report/
│           └── push_positions.py  # 美股持仓报告
│
└── cn/                         # A股分支
    └── regular_stock_cn/       # A股定投策略
        ├── config.json         # A股配置（标的 + 模拟账户）
        ├── regular_stock_cn.py # A股主策略入口
        ├── cn_sim_account.py   # 模拟账户管理
        └── scripts/report/
            └── push_positions_cn.py  # A股持仓报告
```

---

## 九、运行命令

### 美股策略（路径：D:\workspace\QClaw\stock\us\regular_stock_us）

```powershell
cd D:\workspace\QClaw\stock\us\regular_stock_us

# 单标的操作
python regular_stock_us.py --symbol=LITE --hang-order  # 挂单捡漏
python regular_stock_us.py --symbol=LITE --buy-check   # 买入检查
python regular_stock_us.py --symbol=LITE --sell-check  # 卖出检查
python regular_stock_us.py --symbol=LITE --sync        # 同步订单
python regular_stock_us.py --symbol=LITE --status      # 查看状态
python regular_stock_us.py --symbol=LITE --init        # 初始化底仓

# 批量操作
python regular_stock_us.py --hang-all                  # 所有美股挂单
python regular_stock_us.py --market=US --hang-all     # 仅美股

# 持仓报告
python scripts\report\push_positions.py
```

### A股策略（路径：D:\workspace\QClaw\stock\cn\regular_stock_cn）

```powershell
cd D:\workspace\QClaw\stock\cn\regular_stock_cn

# 单标的操作
python regular_stock_cn.py --symbol=603773 --hang-order  # 挂单捡漏
python regular_stock_cn.py --symbol=603773 --buy-check   # 买入检查
python regular_stock_cn.py --symbol=603773 --sell-check  # 卖出检查
python regular_stock_cn.py --symbol=603773 --status      # 查看状态
python regular_stock_cn.py --symbol=603773 --init        # 初始化底仓

# 批量操作
python regular_stock_cn.py --hang-all                    # 所有A股挂单
python regular_stock_cn.py --market=CN --hang-all       # 仅A股

# 持仓报告
python scripts\report\push_positions_cn.py

# 模拟账户管理
python cn_sim_account.py --status   # 查看模拟账户状态
```
