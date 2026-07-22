---
name: health-monitor
description: >-
  智能健康监测与告警。基于阈值检测、趋势分析和多级告警系统，
  按需或在设备同步后检查家庭成员的已记录健康指标。支持全家健康 dashboard 一屏总览。
  Intelligent health monitoring and alerting. Uses threshold detection,
  trend analysis, and multi-level alert records to check recorded family health
  metrics on demand or after wearable imports. Supports a family dashboard.
  关键词：健康监测、异常告警、指标预警、趋势分析、健康报告、心率异常、血压异常、血氧低、告警管理、全家概览、健康dashboard。
---

# MediWise · 健康记录提醒 Skill

按已配置阈值检查健康指标并生成多级记录提醒，支持全家 dashboard 一屏总览。所有级别都只表示规则优先级，不是病情严重程度或临床判断；本 Skill 不提供诊断、治疗或用药指导。

## 告警级别

| 级别 | 含义 | 处理方式 |
|------|------|----------|
| info | 信息记录 | 仅记录 |
| warning | 普通提醒 | 创建普通优先级提醒记录 |
| urgent | 高优先级 | 创建高优先级提醒记录 |
| emergency | 最高优先级 | 创建最高优先级提醒记录 |

## 默认规则阈值

这些数值是可修改的内置提醒规则，不代表诊断标准或医疗建议。用户可根据自己的记录需求调整或关闭；如需医学阈值，应由专业医疗人员确定。

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

> 当前公开版本只用于个人本地档案。身份隔离由安装时的个人模式和 action 适配层处理，不向普通用户暴露或索取 `owner_id`。

### 0. 全家健康 Dashboard（首选入口）

用户说「看看全家健康」「今天家人状态怎样」「健康概览」时，优先调用此接口。
返回所有成员的风险级别、未解决告警数、最新关键指标和趋势警告。

```bash
# 全家健康一屏总览
python3 {baseDir}/scripts/dashboard.py show
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

## 检测触发与提醒边界

- wearable-sync 成功导入数据后可以自动触发一次检查。
- 用户也可以主动请求检查、查看 dashboard 或查询提醒历史。
- health-monitor 只写入本地告警和 reminder 记录，不包含后台守护进程、IM Bot、Webhook、短信或电话推送能力。
- 如当前个人 Agent 自身提供任务调度或通知能力，应使用该平台受支持的配置方式，并保持同一数据目录仅供当前本地用户使用；必须完成任务注册、持久化和一次触发测试后，才能告诉用户会到点主动通知。不要在 Skill 文档中拼接 shell、Webhook 或账号标识。

## 反模式

- **不要把优先级写成病情分级** — warning/urgent/emergency 只是项目内部记录优先级
- **不要声称已发送外部通知** — 项目只创建本地记录，除非当前 Agent 平台确实完成了通知动作
- **趋势分析需要足够数据** — 少于 3 天数据时趋势不可靠
