# 伦敦金走势预测系统 (MVP)

研究辅助 / 交易决策参考 / 风险预警系统。判断伦敦金未来多空力量强弱，不预测精确点位。

## 快速开始

```bash
pip install -e ".[dev]"

# 1) 拉取真实数据 → data/raw/live.csv
python -m gold_forecast.cli fetch

# 2) 生成报告（默认综合权重）
python -m gold_forecast.cli report -i data/raw/live.csv -o reports/latest.md

# 2b) 生成 1 个月重点评估报告（宏观/趋势权重更高，输出核心月度指标摘要）
python -m gold_forecast.cli report -i data/raw/live.csv -o reports/monthly.md --horizon month

# 或一步完成
python -m gold_forecast.cli run

# 一步完成并输出 1 个月重点报告
python -m gold_forecast.cli run -o reports/monthly.md --horizon month
```

### 数据源

| 指标 | 来源 |
|------|------|
| 金价（COMEX 代理） | Yahoo `GC=F`（USD/oz） |
| DXY | Yahoo `DX-Y.NYB` |
| 美国 10Y 实际利率 | FRED `DFII10`（可用 `FRED_API_KEY`） |
| 美国 CPI 同比 | FRED `CPIAUCSL` 衍生同比（可用 `FRED_API_KEY`） |
| 中国 PMI / 社融 / M1 | 东方财富 / akshare |
| LME / SHFE / COMEX 黄金库存 | 东方财富 LME 金库存、akshare 沪金仓单、CME `Gold_Stocks.xls` |
| 现货升贴水 / 期限结构 | SHFE AU0 vs COMEX GC=F 衍生 |
| 央行购金 / 首饰需求 / ETF / 投机持仓 | WGC / CFTC（**未接入自动抓取**，见 `data/audit/missing_sources.json`） |
| ISM / 全球 PMI | ISM 待接入；全球 PMI 由已抓取 PMI 衍生 |

复制 `.env.example` 为 `.env` 并填入 `FRED_API_KEY`（可选）。

黄金相对铜更依赖宏观流动性（美元、实际利率、美国通胀）与金融流动（ETF、投机持仓），实物需求模块侧重中国 PMI、社融及央行/首饰消费人工数据。

### A/B 交叉验证

报告将模块分成两组做交叉验证：

- A 组：基本面/现货组（实物需求、库存现货、金融流动）
- B 组：宏观/价格组（美元利率/通胀、价格趋势）

两组分别按模块权重归一化打分。若 A/B 同向，说明信号相互确认；若背离，说明基本面与宏观/价格信号冲突，方向置信度应谨慎解读。

## 数据格式

CSV 必须包含以下列：

```text
date,indicator,value,unit,source,source_url,updated_at,frequency,confidence
```

核心规则：**无来源不入库、单位不明不入库、异常数据进入待复核**。

## 项目结构

```text
config/          # 指标、权重、校验规则
data/raw/        # 原始输入
data/validated/  # 校验后数据
data/clean/      # 模型使用的 confirmed 数据
data/audit/      # 异常日志、抓取日志、缺失数据源清单
reports/         # Markdown 报告
src/gold_forecast/
tests/
```

## 模块权重（默认）

| 模块 | 权重 | 说明 |
|------|------|------|
| 美元利率/通胀 | 40% | DXY、实际利率、美国 CPI 同比（黄金核心驱动） |
| 金融流动 | 20% | ETF 持仓变化、投机净多、地缘事件 |
| 实物需求 | 15% | 中国 PMI/社融、央行购金、首饰消费 |
| 价格趋势 | 15% | 金价均线与动量 |
| 库存现货 | 10% | 三所库存、升贴水、期限结构 |

## MVP 范围

已实现：CSV 读取、数据校验、五模块打分、总分与置信度、Markdown 报告、异常日志、多源自动抓数。

未实现：机器学习、Web 前端、自动交易。

基于 [harness-Cu](../harness-Cu) 铜价预测系统改造，保留相同流水线架构，替换为黄金专用指标与数据源。
