# 伦敦金走势判断报告

生成日期：2026-06-30 15:09
数据截止：2026-06-30

## 结论

1 周判断：**中性**
1 月判断：**中性**
总分：**+0.013**（中性）
置信度：**0%**
数据健康度：**85%**


## 模块分数

| 模块 | 分数 | 状态 |
|---|---:|---|
| 实物需求 | +1.000 | 🟢 强多（缺口: 2） |
| 库存现货 | +0.500 | 🟢 强多（缺口: 2） |
| 美元利率/通胀 | -0.333 | 🟠 偏空 |
| 金融流动 | +0.480 | 🟡 偏多（缺口: 2） |
| 价格趋势 | -1.000 | 🔴 强空 |

## A/B 交叉验证

结论：**相互背离**。A/B 两组方向冲突，方向置信度应下调

| 组别 | 模块 | 分数 | 方向 |
|---|---|---:|---|
| 基本面/现货组 | 实物需求、库存现货、金融流动 | +0.658 | 看多 |
| 宏观/价格组 | 美元利率/通胀、价格趋势 | -0.515 | 看空 |

## 主要支撑

1. [physical_demand] Social financing / M1 improving
2. [physical_demand] New orders PMI 51.8
3. [physical_demand] China PMI mom +0.3

## 主要压制

1. [trend] Price 4046.3 <= MA60 (4507.6)
2. [trend] Price 4046.3 <= MA20 (4223.5)
3. [trend] Price 4046.3 <= MA120 (4514.2)

## 风险提示

1. 多空模块严重分裂，方向判断不确定性较高
2. inventory 存在数据缺口: lme_inventory missing, comex_inventory missing
3. physical_demand 存在数据缺口: central_bank_gold_net_buy missing, gold_jewelry_demand_yoy missing

## 判断失效条件

1. 任一核心模块分数突破 ±0.5 将触发方向调整
2. 库存或宏观流动性出现单边趋势性变化
3. 实物需求或金融流动出现方向性拐点

## 数据异常

1. [pending] lme_gold_price (2026-01-26): Gold price outside 800-5000 USD/oz range
2. [pending] lme_gold_price (2026-01-27): Gold price outside 800-5000 USD/oz range
3. [pending] lme_gold_price (2026-01-28): Gold price outside 800-5000 USD/oz range
4. [pending] lme_gold_price (2026-01-29): Gold price outside 800-5000 USD/oz range
5. [pending] lme_gold_price (2026-02-09): Gold price outside 800-5000 USD/oz range
6. [pending] lme_gold_price (2026-02-10): Gold price outside 800-5000 USD/oz range
7. [pending] lme_gold_price (2026-02-11): Gold price outside 800-5000 USD/oz range
8. [pending] lme_gold_price (2026-02-13): Gold price outside 800-5000 USD/oz range
9. [pending] lme_gold_price (2026-02-20): Gold price outside 800-5000 USD/oz range
10. [pending] lme_gold_price (2026-02-23): Gold price outside 800-5000 USD/oz range

## 缺失数据源

| 指标 | 预期来源 | 状态 | 说明 |
|---|---|---|---|
| central_bank_gold_net_buy | WGC | 未接入自动抓取 | World Gold Council central bank demand report; no automated fetcher yet |
| gold_etf_holdings_chg | WGC | 未接入自动抓取 | World Gold Council ETF holdings tracker; no automated fetcher yet |
| gold_jewelry_demand_yoy | WGC | 未接入自动抓取 | World Gold Council jewelry demand statistics; no automated fetcher yet |
| spec_net_long_gold | CFTC | 未接入自动抓取 | CFTC Commitments of Traders managed-money net long; no automated fetcher yet |
| comex_inventory | CME Group | 数据集中缺失 | — |
| lme_inventory | 东方财富-LME | 数据集中缺失 | — |

## 模块信号明细

### 实物需求

- [+1] China PMI 50.3
- [+1] China PMI mom +0.3
- [+1] New orders PMI 51.8
- [+1] Social financing / M1 improving
- ⚠ 数据缺口: central_bank_gold_net_buy missing, gold_jewelry_demand_yoy missing

### 库存现货

- [+1] Global inventory 20d change -0.02%
- [-1] Global inventory 60d change +4.69%
- [+1] Spot premium +57.2 (contango/premium)
- [+1] Term structure: backwardation
- ⚠ 数据缺口: lme_inventory missing, comex_inventory missing

### 美元利率/通胀

- [-1] DXY 20d change +2.14%
- [-1] DXY 60d change +1.29%
- [-1] US 10Y real rate 20d change +5.83%
- [-1] US 10Y real rate 60d change +7.92%
- [+1] US CPI YoY 4.27%
- [+1] US CPI YoY mom +0.32pp

### 金融流动

- [+0] Geopolitical risk supports safe-haven demand (source: news)
- ⚠ 数据缺口: gold_etf_holdings_chg missing, spec_net_long_gold missing

### 价格趋势

- [-1] Price 4046.3 <= MA20 (4223.5)
- [-1] Price 4046.3 <= MA60 (4507.6)
- [-1] Price 4046.3 <= MA120 (4514.2)
- [-1] 20d return -9.58%
- [-1] 60d return -13.01%

---
*本报告由 gold-forecast MVP 生成，仅供研究参考，不构成投资建议。*