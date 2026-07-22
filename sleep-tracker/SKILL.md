---
name: sleep-tracker
description: >-
  睡眠追踪与质量分析。记录每晚睡眠时长和各阶段（深睡/浅睡/REM/清醒），
  评估睡眠质量评分，查看每日详情和每周趋势。支持手动录入和可穿戴设备自动同步。
  Sleep tracking and quality analysis. Records nightly sleep duration and stages
  (deep/light/REM/awake), scores sleep quality, and shows daily details and weekly trends.
  关键词：睡眠记录、睡眠质量、深睡、REM、睡眠趋势、睡眠分析、失眠、睡了多久、昨晚睡眠。
---

# MediWise · 睡眠追踪 Skill

记录和汇总睡眠数据，展示睡眠规律和与内置参考值的差异。评分只用于记录展示，不是医学判断，也不提供改善或治疗建议。

## 睡眠质量评分标准

| 评分 | 标签 | 说明 |
|------|------|------|
| 85-100 | 高匹配 | 与内置参考值匹配较多 |
| 70-84 | 较高匹配 | 与内置参考值存在少量差异 |
| 55-69 | 部分匹配 | 与内置参考值存在多项差异 |
| 0-54 | 低匹配 | 与内置参考值差异较多 |

**内置展示参考值（不用于医学判断）：**
- 总时长：7-9 小时
- 深睡比例：13-23%
- REM 比例：20-25%
- 清醒时间：<10%

## 核心工作流

> **强制规则**：每次调用脚本必须携带 `--owner-id`，从会话上下文获取发送者 ID（格式 `<channel>:<user_id>`，如 `feishu:ou_xxx` 或 `qqbot:12345`），不得省略。

### 1. 手动录入睡眠

用户说「昨晚睡了7小时」「记录睡眠」时使用：

```bash
# 录入总时长（最简方式，其他阶段留空）
python3 {baseDir}/scripts/sleep.py log --member-id <id> --duration 420

# 带阶段详情录入
python3 {baseDir}/scripts/sleep.py log --member-id <id> --duration 480 \
  --deep 90 --light 240 --rem 100 --awake 30

# 指定日期（默认昨天）
python3 {baseDir}/scripts/sleep.py log --member-id <id> --duration 450 --date 2026-03-26
```

**时长换算提示：**
- 用户说「7小时」→ duration=420
- 用户说「7.5小时」→ duration=450
- 用户说「7小时30分」→ duration=450

### 2. 查看每日睡眠

用户说「昨晚睡得怎么样」「查看睡眠」时使用：

```bash
# 查看昨晚（默认）
python3 {baseDir}/scripts/sleep.py daily --member-id <id>

# 查看指定日期
python3 {baseDir}/scripts/sleep.py daily --member-id <id> --date 2026-03-26
```

### 3. 每周睡眠趋势

用户说「这周睡眠怎么样」「睡眠趋势」时使用：

```bash
# 近7天（默认）
python3 {baseDir}/scripts/sleep.py weekly --member-id <id>

# 近14天
python3 {baseDir}/scripts/sleep.py weekly --member-id <id> --days 14
```

### 4. 历史记录

```bash
# 最近14条（默认）
python3 {baseDir}/scripts/sleep.py list --member-id <id>

# 最近30条
python3 {baseDir}/scripts/sleep.py list --member-id <id> --limit 30
```

## 数据来源

睡眠数据来自两个渠道：
1. **手动录入**：通过 `sleep-log` action 直接输入
2. **可穿戴同步**：通过 wearable-sync 从 Apple Health / Gadgetbridge 自动导入

两种来源均存储在 `health_metrics` 表（`metric_type='sleep'`），查询时统一处理。

## 反模式

- **不要重复录入同一天** — 系统会显示多条，建议先 daily 确认再录入
- **阶段时长之和不能超过总时长** — 否则录入报错
- **手动录入不需要精确到分钟** — 大致时长即可，质量评分有容忍范围
