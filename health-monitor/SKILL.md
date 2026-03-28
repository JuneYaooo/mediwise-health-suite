---
name: health-monitor
description: >-
  智能健康监测与告警。基于阈值检测、趋势分析和多级告警系统，
  对家庭成员的健康指标进行持续监测，发现异常时及时预警。支持全家健康 dashboard 一屏总览。
  Intelligent health monitoring and alerting. Uses threshold detection,
  trend analysis, and multi-level alert system to continuously monitor
  family members' health metrics and warn on anomalies. Supports family dashboard.
  关键词：健康监测、异常告警、指标预警、趋势分析、健康报告、心率异常、血压异常、血氧低、告警管理、全家概览、健康dashboard。
---

# Health Monitor - 智能健康监测

持续监测健康指标，多级阈值告警 + 趋势分析，发现异常及时通知。支持全家健康 dashboard 一屏总览。

## 告警级别

| 级别 | 含义 | 处理方式 |
|------|------|----------|
| info | 信息记录 | 仅记录，不主动推送 |
| warning | 预警 | 创建 reminder 推送 |
| urgent | 紧急 | 推送 + 标记高优先级 |
| emergency | 危急 | 推送 + 建议立即就医或拨打急救电话 |

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

> **强制规则**：每次调用脚本必须携带 `--owner-id`，从会话上下文获取发送者 ID（格式 `<channel>:<user_id>`，如 `feishu:ou_xxx` 或 `qqbot:12345`）。所有查询和写入操作均需携带，不得省略。

### 0. 全家健康 Dashboard（首选入口）

用户说「看看全家健康」「今天家人状态怎样」「健康概览」时，优先调用此接口。
返回所有成员的风险级别、未解决告警数、最新关键指标和趋势警告。

```bash
# 全家健康一屏总览
python3 {baseDir}/scripts/dashboard.py show

# 按 owner 过滤（多租户场景）
python3 {baseDir}/scripts/dashboard.py show --owner-id <owner_id>
```

**返回结构示例：**
```json
{
  "family_risk": "warning",
  "family_risk_label": "需关注",
  "total_open_alerts": 3,
  "summary": "【紧急】张三 有紧急告警；共 3 条未解决告警",
  "members": [
    {
      "name": "张三",
      "risk_level": "urgent",
      "risk_label": "紧急",
      "open_alerts": 2,
      "alerts": [{"level": "urgent", "title": "张三 heart_rate 高于阈值", ...}],
      "latest_metrics": {
        "heart_rate": {"value": 125, "unit": "bpm", "measured_at": "2026-03-27 08:30"},
        "blood_pressure": {"value": "145/95", "unit": "mmHg", "measured_at": "2026-03-27 08:30"}
      },
      "trend_warnings": ["heart_rate 呈上升趋势"]
    }
  ]
}
```

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

## 持续监测 + 消息推送完整配置

### 架构概览

```
iPhone 健康 App
    → 导出 export.zip（手动/Shortcuts 自动）
    → iCloud Drive 同步到 Mac / 直接传输到服务器
    → cron: wearable-sync sync.py（导入数据）
    → cron: health-monitor check.py（检测异常 → 写入 alerts 表）
    → AI agent 查询告警 → 通过 IM Bot 推送给用户
```

### 第一步：配置数据同步（wearable-sync）

参考 wearable-sync/SKILL.md 的「Apple Health 持续更新方案」完成设备绑定和 cron 配置。

### 第二步：配置定时检测

```bash
crontab -e

# 同步数据（每小时整点）
0 * * * * cd /path/to/wearable-sync/scripts && python3 sync.py run-all >> ~/mediwise-sync.log 2>&1

# 检测异常（同步后5分钟，确保数据已写入）
5 * * * * cd /path/to/health-monitor/scripts && python3 check.py run-all --window 2h >> ~/mediwise-check.log 2>&1
```

### 第三步：推送告警

**当前架构：告警写入数据库，由 AI agent 主动查询推送。**

health-monitor 本身不内置 IM 推送 SDK，告警通过以下方式触达用户：

**方式 A：AI agent 定时巡检（推荐）**

在 IM Bot（飞书/企微/钉钉）中，让 AI agent 定时调用 dashboard action 并主动发消息：

```bash
# cron 触发 agent 巡检脚本（示例）
30 7 * * * /path/to/bot-client send-health-report --owner-id feishu:ou_xxx
```

agent 内部执行：
1. `dashboard show` → 获取全家风险概览
2. 若 `family_risk` 为 warning/urgent/emergency → 主动发送 IM 消息
3. `alert-list` → 列出未解决告警，逐条通知

**方式 B：cron 脚本直接调用 Bot API**

```bash
#!/bin/bash
# /path/to/health-alert-push.sh
RESULT=$(python3 /path/to/health-monitor/scripts/dashboard.py show --owner-id "$1")
RISK=$(echo $RESULT | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('family_risk','ok'))")

if [ "$RISK" != "ok" ]; then
  # 调用飞书/企微 Webhook 发送告警
  curl -X POST "$FEISHU_WEBHOOK" \
    -H 'Content-Type: application/json' \
    -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"健康告警：$RISK，请打开 MediWise 查看详情\"}}"
fi
```

**方式 C：用户主动查询（最简单）**

用户在 IM 中随时发送「看看全家健康」，agent 调用 dashboard 返回实时状态，无需后台推送。

### 告警级别与推送策略建议

| 级别 | 建议推送频率 | 建议渠道 |
|------|-------------|----------|
| info | 不推送，仅记录 | — |
| warning | 每日早晨汇总推送一次 | IM 普通消息 |
| urgent | 立即推送 | IM @消息 / 手机通知 |
| emergency | 立即推送 + 重复提醒 | IM @消息 + 电话/短信 |

> **当前限制**：health-monitor 不内置推送 SDK，emergency 级别需要外部脚本或 agent 逻辑实现重复提醒。建议在 agent 层对 emergency 告警做特殊处理（如每15分钟重复发送直到用户确认）。

## 反模式

- **不要将阈值设得过于敏感** — 容易产生告警疲劳
- **不要忽略 emergency 级别告警** — 应立即关注
- **趋势分析需要足够数据** — 少于 3 天数据时趋势不可靠
