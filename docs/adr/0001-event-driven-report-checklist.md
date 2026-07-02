# ADR-0001：事件驱动报告更新与 `checklist.md`

| 字段 | 值 |
|------|-----|
| 状态 | 已采纳 |
| 日期 | 2026-07-02 |
| 决策者 | 黄金预测流水线维护者 |

## 背景

伦敦金报告由五模块打分 + **沃什因子**合成，数据源分三类：

1. **自动抓取**（`python -m gold_forecast.cli fetch`）：金价、DXY、实际利率、CPI、社融/M1、库存等
2. **配置文件**（人工）：`config/warsh_factor.yaml`、权重与阈值
3. **事件表**（人工）：`data/raw/market_events.csv`（地缘/突发）

宏观发布与 FOMC 等 **时点事件** 会在数小时至数日内改变模块分数，但流水线不会自动感知日历。需要一份 **按月滚动、按时间排序** 的检查清单，在事件前后触发标准化更新动作，避免漏跑报告或忘记改沃什因子。

## 决策

1. 在 `docs/events/checklist.md` 维护 **未来约 30 天** 的关键事件清单（美东/北京时间注明）。
2. 每条事件绑定 **更新动作**（`fetch` / `report` / 改 `warsh_factor` / 改 `market_events` / 改 `gold_inventory.csv`）。
3. 事件结束后在清单中勾选 `[x]`，并在备注栏记录报告归档路径或配置变更。
4. 每月初（或 FOMC 后） **滚动刷新** 清单窗口，旧清单移入 `docs/events/archive/YYYY-MM.md`（可选，首版不强制归档脚本）。

## 事件分级

| 级别 | 含义 | 默认动作 |
|------|------|----------|
| P0 | FOMC、主席发布会、核心 CPI/PCE | fetch → report；必要时更新沃什因子 |
| P1 | NFP、PPI、中国社融/M1/PMI、FOMC 纪要 | fetch → report |
| P2 | 地缘观察、库存手工维护、Beige Book | 视情况 fetch 或仅改 events/库存 CSV |

## 标准命令

```bash
# 全量：抓数 + 月视角报告（推荐 P0/P1 后执行）
python -m gold_forecast.cli run -o reports/monthly.md --horizon month

# 仅抓数（数据已发布、先入库）
python -m gold_forecast.cli fetch

# 仅报告（数据已在 live.csv）
python -m gold_forecast.cli report -i data/raw/live.csv -o reports/monthly.md --horizon month
```

## 配置触发表

| 触发场景 | 修改文件 | 说明 |
|----------|----------|------|
| 主席重要讲话 / FOMC 发布会 | `config/warsh_factor.yaml` | 更新 `dimensions`、`meta.speech_date`、`meta.valid_until` |
| 地缘升级/缓和 | `data/raw/market_events.csv` | `score` ∈ [-1,1]，confidence A/B/C |
| LME/COMEX 库存滞后 | `data/raw/gold_inventory.csv` | 每周或库存异动时 |

## 后果

### 正面

- 报告更新与宏观日历对齐，沃什因子与 FOMC 窗口同步
- 人工步骤可审计（勾选 + 备注）
- 与现有 MVP 兼容，无需改代码

### 负面

- 清单需人工滚动维护，日期以官方日历为准
- 不替代实时行情监控；P2 地缘仍依赖主观判断

## 相关文件

- 活动清单：[`docs/events/checklist.md`](../events/checklist.md)
- 沃什因子：[`config/warsh_factor.yaml`](../../config/warsh_factor.yaml)
- 市场事件：[`data/raw/market_events.csv`](../../data/raw/market_events.csv)
