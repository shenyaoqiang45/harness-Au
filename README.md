# 伦敦金走势预测系统 (MVP)

研究辅助 / 交易决策参考 / 风险预警系统。判断伦敦金未来多空力量强弱，不预测精确点位。

## 快速开始

```bash
pip install -e ".[dev]"

# 1) 拉取真实数据 → data/raw/live.csv
python -m gold_forecast.cli fetch

# 2) 生成 1 个月重点评估报告（自动按执行日期归档）
python -m gold_forecast.cli report -i data/raw/live.csv -o reports/monthly.md

# 2b) 生成综合权重报告
python -m gold_forecast.cli report -i data/raw/live.csv -o reports/monthly.md --horizon aggregate

# 或一步完成（报告自动归档到 reports/YYYY-MM-DD/）
python -m gold_forecast.cli run

# 3) Walk-forward 回测：每日用截至当日数据打分，对照未来 1 周 / 1 月金价
python -m gold_forecast.cli backtest
python -m gold_forecast.cli backtest -i data/raw/history.csv -o reports/backtest.md
```

### 数据源

| 指标 | 来源 |
|------|------|
| 金价（COMEX 代理） | Yahoo `GC=F`（USD/oz） |
| DXY | Yahoo `DX-Y.NYB` |
| 美国 10Y 实际利率 | FRED `DFII10`（可用 `FRED_API_KEY`） |
| 美国 CPI 同比 | FRED `CPIAUCNS` 未季调同比（对齐 BLS headline；可用 `FRED_API_KEY`） |
| 美国 PCE / 核心 PCE 同比 | FRED `PCEPI` / `PCEPILFE` 季调同比（对齐 BEA；Fed 首选通胀） |
| 中国 社融 / M1 | 东方财富 / akshare |
| LME / SHFE / COMEX 黄金库存 | 东方财富 LME 金库存、akshare 沪金仓单、CME `Gold_Stocks.xls` |
| 现货升贴水 / 期限结构 | SHFE AU0 vs COMEX GC=F 衍生 |
| 地缘事件 | `data/raw/market_events.csv`（人工维护） |

复制 `.env.example` 为 `.env` 并填入 `FRED_API_KEY`（可选）。

黄金相对铜更依赖宏观流动性（美元、实际利率、美国通胀）。实物需求模块以中国社融/M1 为代表，金融流动模块目前以地缘事件为主。

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
reports/         # Markdown 报告（按执行日期归档，避免覆盖）
src/gold_forecast/   # 打分、报告、抓数、回测
tests/
```

## 模块权重（默认 / 1 个月视角）

| 模块 | 默认 | 1 个月 | 说明 |
|------|------|--------|------|
| 美元利率/通胀 | 35% | 40% | DXY、实际利率、美国 CPI/PCE 同比 |
| 沃什因子 | 5% | 5% | 主席公开表态（窗口外归零） |
| 价格趋势 | 15% | 25% | 金价均线与动量 |
| 金融流动 | 20% | 15% | 地缘事件 |
| 实物需求 | 15% | 5% | 中国社融/M1 |
| 库存现货 | 10% | 10% | 三所库存、升贴水、期限结构 |

1 个月视角合计仍为 100%。权重未经样本外检验，用 `cli backtest` 对照未来金价方向校准，**不要**把一次回测结果直接写回 yaml。

## 回测评估

`cli backtest` 做 walk-forward：每个交易日 t 只用 `date <= t`（月度序列再按 `config/publication_lag.yaml` 推迟发布日）重算当前打分函数，对照未来 5 / 21 个交易日金价。输出命中率、Spearman、按置信度/A/B 分层、模块秩相关、权重方案对比，以及历史报告回放。报告归档到 `reports/YYYY-MM-DD/backtest_*.md`（附 JSON）。

已知限制：沃什因子只有当前 yaml 窗口；样本期若偏牛，「永远做多」是必比基线。

## MVP 范围

已实现：CSV 读取、数据校验、六模块打分、总分与置信度、Markdown 报告、异常日志、多源自动抓数、walk-forward 回测。

未实现：机器学习、Web 前端、自动交易、自动改权重。

基于 [harness-Cu](../harness-Cu) 铜价预测系统改造，保留相同流水线架构，替换为黄金专用指标与数据源。
