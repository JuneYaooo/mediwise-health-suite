---
name: health-monitor
description: >-
  智能健康监测与告警。基于阈值检测、趋势分析和多级告警系统，
  对家庭成员的健康指标进行持续监测，发现异常时及时预警。
  Intelligent health monitoring and alerting. Uses threshold detection,
  trend analysis, and multi-level alert system to continuously monitor
  family members' health metrics and warn on anomalies.
  关键词：健康监测、异常告警、指标预警、趋势分析、健康报告、心率异常、血压异常、血氧低、告警管理。
---

# Health Monitor - 智能健康监测

持续监测健康指标，多级阈值告警 + 趋势分析，发现异常及时通知。

## 告警级别

| 级别 | 含义 | 处理方式 |
|------|------|----------|
| info | 信息记录 | 仅记录，不主动推送 |
| warning | 预警 | 创建 reminder 推送 |
| urgent | 紧急 | 推送 + 标记高优先级 |
| emergency | 危急 | 推送 + 联动 first-aid skill 急救指引 |

## 默认阈值

| 指标 | warning | urgent | emergency |
|------|---------|--------|-----------|
| 心率（高）| >100 bpm | >120 bpm | >150 bpm |
| 心率（低）| <55 bpm | <45 bpm | <35 bpm |
| 血氧（低）| <95% | <90% | <85% |
| 收缩压（高）| >140 mmHg | >160 mmHg | >180 mmHg |
| 舒张压（高）| >90 mmHg | >100 mmHg | >110 mmHg |
| 体温（高）| >37.3°C | >38.5°C | >39.5°C |
| 血糖空腹（高）| >6.1 mmol/L | >7.8 mmol/L | >11.1 mmol/L |

支持按年龄自动调整，支持用户自定义覆盖。

## 核心工作流

### 1. 阈值管理

```bash
# 查看阈值配置（含默认+自定义）
python3 {baseDir}/scripts/threshold.py list --member-id <id>

# 自定义阈值
python3 {baseDir}/scripts/threshold.py set --member-id <id> --type heart_rate --level warning --direction above --value 110

# 恢复默认
python3 {baseDir}/scripts/threshold.py reset --member-id <id> --type heart_rate
```

### 2. 异常检测

```bash
# 检查单个成员
python3 {baseDir}/scripts/check.py run --member-id <id>

# 检查所有成员
python3 {baseDir}/scripts/check.py run-all

# 检查最近指定时间窗口
python3 {baseDir}/scripts/check.py run --member-id <id> --window 24h
```

### 3. 趋势分析

```bash
# 单指标趋势
python3 {baseDir}/scripts/trend.py analyze --member-id <id> --type heart_rate --days 7

# 全指标摘要
python3 {baseDir}/scripts/trend.py report --member-id <id>
```

### 4. 告警管理

```bash
# 查看未解决告警
python3 {baseDir}/scripts/alert.py list --member-id <id>

# 按级别筛选
python3 {baseDir}/scripts/alert.py list --member-id <id> --level urgent

# 标记已解决
python3 {baseDir}/scripts/alert.py resolve --alert-id <id>

# 告警历史
python3 {baseDir}/scripts/alert.py history --member-id <id> --limit 20
```

## 定时检测

配合 wearable-sync 使用时，每次数据同步完成后会自动触发检测。
也可单独通过 cron 定时运行：

```bash
# 每小时检测一次
0 * * * * cd /path/to/health-monitor/scripts && python3 check.py run-all --window 1h
```

## 反模式

- **不要将阈值设得过于敏感** — 容易产生告警疲劳
- **不要忽略 emergency 级别告警** — 应立即关注
- **趋势分析需要足够数据** — 少于 3 天数据时趋势不可靠
