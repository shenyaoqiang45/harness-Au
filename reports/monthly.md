# 伦敦金走势判断报告

生成日期：2026-06-30 16:11
数据截止：2026-06-30

## 结论

1 周判断：**偏空**
1 月判断：**偏空**
总分：**-0.328**（偏空）
置信度：**9%**
数据健康度：**95%**


## 1个月核心指标摘要

- **金价 20 日回报**：20d return -9.50%
- **金价 vs MA20**：Price 4050.1 <= MA20 (4223.7)
- **DXY 20d change +2.14%**
- **US 10Y real rate 20d change +5.83%**
- **CPI 同比**：US CPI YoY 4.27%
- **CPI 环比变化**：US CPI YoY mom +0.32pp
- **Global inventory 20d change -0.02%**
- **Spot premium -1.0 (discount)**
- **Term structure: contango**

## 模块分数

| 模块 | 分数 | 状态 |
|---|---:|---|
| 实物需求 | +1.000 | 🟢 强多 |
| 库存现货 | -0.500 | 🔴 强空（缺口: 2） |
| 美元利率/通胀 | -0.333 | 🟠 偏空 |
| 金融流动 | +0.480 | 🟡 偏多 |
| 价格趋势 | -1.000 | 🔴 强空 |

## A/B 交叉验证

结论：**相互背离**。A/B 两组方向冲突，方向置信度应下调

| 组别 | 模块 | 分数 | 方向 |
|---|---|---:|---|
| 基本面/现货组 | 实物需求、库存现货、金融流动 | +0.240 | 偏多 |
| 宏观/价格组 | 美元利率/通胀、价格趋势 | -0.571 | 看空 |

## 主要支撑

1. [physical_demand] Social financing / M1 improving
2. [macro_liquidity] US CPI YoY mom +0.32pp
3. [macro_liquidity] US CPI YoY 4.27%

## 主要压制

1. [trend] Price 4050.1 <= MA60 (4507.7)
2. [trend] Price 4050.1 <= MA20 (4223.7)
3. [trend] Price 4050.1 <= MA120 (4696.6)

## 风险提示

1. 多空模块严重分裂，方向判断不确定性较高
2. inventory 存在数据缺口: lme_inventory missing, comex_inventory missing

## 判断失效条件

1. 全球库存降至三年低位且现货维持升水
2. 央行净购金与 ETF 流入同步走强
3. 美元与实际利率同步下行

## 数据异常

1. 无异常数据

## 缺失数据源

1. 所有已配置自动数据源均已入库

## 模块信号明细

### 实物需求

- [+1] Social financing / M1 improving

### 库存现货

- [+1] Global inventory 20d change -0.02%
- [-1] Global inventory 60d change +4.69%
- [-1] Spot premium -1.0 (discount)
- [-1] Term structure: contango
- ⚠ 数据缺口: lme_inventory missing, comex_inventory missing

### 美元利率/通胀

- [-1] DXY 20d change +2.14%
- [-1] DXY 60d change +1.30%
- [-1] US 10Y real rate 20d change +5.83%
- [-1] US 10Y real rate 60d change +7.92%
- [+1] US CPI YoY 4.27%
- [+1] US CPI YoY mom +0.32pp

### 金融流动

- [+0] Geopolitical risk supports safe-haven demand (source: news)

### 价格趋势

- [-1] Price 4050.1 <= MA20 (4223.7)
- [-1] Price 4050.1 <= MA60 (4507.7)
- [-1] Price 4050.1 <= MA120 (4696.6)
- [-1] 20d return -9.50%
- [-1] 60d return -12.93%

---
*本报告由 gold-forecast MVP 生成，仅供研究参考，不构成投资建议。*