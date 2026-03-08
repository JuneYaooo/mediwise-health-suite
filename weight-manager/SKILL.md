---
name: weight-manager
description: >-
  体重管理、减脂增重目标、运动记录与身体指标分析。用于设定体重目标、追踪进度、
  计算 BMI/BMR/TDEE、分析热量收支，并结合 `diet-tracker` 与 `mediwise-health-tracker`
  形成饮食、运动、体重和围度的管理闭环。
  Use when setting weight goals, tracking progress, logging exercise, or analyzing
  calorie balance and body composition.
---

# weight-manager

## 概述

提供体重目标设定、进度追踪、趋势分析、热量收支计算、达标预测、BMI/BMR/TDEE 计算、运动记录和身体围度记录功能。体重数据复用 `health_metrics` 表（weight 类型），饮食热量数据来自 `diet_records` 表，运动消耗数据来自 `exercise_records` 表，身体围度数据复用 `health_metrics` 表，形成完整的"饮食 → 运动 → 热量 → 体重 → 身体成分"管理闭环。

## 数据模型

### weight_goals（体重目标）
| 字段 | 说明 |
|------|------|
| id | 目标 ID |
| member_id | 成员 ID |
| goal_type | 目标类型: lose/gain/maintain |
| start_weight | 起始体重 kg |
| target_weight | 目标体重 kg |
| start_date | 开始日期 |
| target_date | 目标日期 |
| daily_calorie_target | 每日热量目标 kcal |
| status | 状态: active/completed/abandoned |
| note | 备注 |

### exercise_records（运动记录）
| 字段 | 说明 |
|------|------|
| id | 记录 ID |
| member_id | 成员 ID |
| exercise_type | 运动类型: running/walking/cycling/swimming/strength/yoga/hiit/other |
| exercise_name | 自定义名称 |
| duration | 时长（分钟） |
| calories_burned | 消耗热量 kcal |
| exercise_date | 运动日期 YYYY-MM-DD |
| exercise_time | 运动时间 HH:MM |
| intensity | 强度: low/medium/high |
| note | 备注 |

> 体重记录复用 `health_metrics` 表的 weight 类型，不重复建表。
> 身体围度记录复用 `health_metrics` 表，metric_type 为 waist/hip/chest/arm/thigh/body_fat。

## 功能列表

### weight_goal.py — 目标管理

| 动作 | 子命令 | 必要参数 | 可选参数 | 说明 |
|------|--------|----------|----------|------|
| set-goal | set | --member-id, --goal-type, --start-weight, --target-weight | --start-date, --target-date, --daily-calorie-target, --activity-level, --note | 设定减重/增重/维持目标，未指定热量目标时自动根据 BMR/TDEE 推算 |
| view-goal | view | --member-id | | 查看当前活跃目标 |
| update-goal | update | --goal-id | --target-weight, --target-date, --daily-calorie-target, --note | 修改目标参数 |
| complete-goal | complete | --goal-id | | 标记目标完成 |
| abandon-goal | abandon | --goal-id | | 放弃目标 |

### weight_analysis.py — 进度分析

| 动作 | 子命令 | 必要参数 | 可选参数 | 说明 |
|------|--------|----------|----------|------|
| weight-progress | progress | --member-id | | 当前进度（已减/增多少，完成百分比） |
| weight-trend | trend | --member-id | --days (默认 30) | 体重趋势（N 天变化，平均变化速率） |
| calorie-balance | calorie-balance | --member-id | --days (默认 7) | 热量收支（含饮食摄入 + 运动消耗 + TDEE 估算） |
| weekly-report | weekly-report | --member-id | --end-date | 周报（体重变化 + 饮食热量 + 运动统计 + 建议） |
| weight-projection | projection | --member-id | | 按当前速度预测达标日期 |

### exercise.py — 运动记录

| 动作 | 子命令 | 必要参数 | 可选参数 | 说明 |
|------|--------|----------|----------|------|
| add-exercise | add | --member-id, --exercise-type | --exercise-name, --duration, --calories-burned, --exercise-date, --exercise-time, --intensity, --note | 添加运动记录 |
| list-exercises | list | --member-id | --exercise-type, --start-date, --end-date, --limit | 查看运动记录 |
| delete-exercise | delete | --id | | 删除运动记录 |
| exercise-summary | daily-summary | --member-id | --date | 某日运动摘要 |

### body_stats.py — 身体指标与围度

| 动作 | 子命令 | 必要参数 | 可选参数 | 说明 |
|------|--------|----------|----------|------|
| calculate-bmi | bmi | --member-id | | 计算 BMI（中国标准分级） |
| calculate-bmr-tdee | bmr-tdee | --member-id | --activity-level | 计算 BMR 和 TDEE（Mifflin-St Jeor 公式） |
| suggest-calories | suggest-calories | --member-id | --activity-level, --goal-type | 根据 TDEE + 目标类型推算每日热量目标 |
| add-measurement | add-measurement | --member-id, --type, --value | --measured-at, --note | 记录身体围度 |
| list-measurements | list-measurements | --member-id | --type, --limit | 查看围度记录历史 |
| body-summary | body-summary | --member-id | | 综合身体报告（BMI + 围度变化 + 体脂率趋势） |

## BMI/BMR/TDEE 说明

### BMI 分级（中国标准）
- < 18.5：偏瘦
- 18.5 - 24：正常
- 24 - 28：超重
- >= 28：肥胖

### BMR 公式（Mifflin-St Jeor）
- 男: BMR = 10 × 体重(kg) + 6.25 × 身高(cm) - 5 × 年龄 + 5
- 女: BMR = 10 × 体重(kg) + 6.25 × 身高(cm) - 5 × 年龄 - 161

### TDEE 活动系数
| 活动水平 | 系数 | 说明 |
|----------|------|------|
| sedentary | 1.2 | 久坐不动 |
| light | 1.375 | 轻度活动（每周1-3次） |
| moderate | 1.55 | 中度活动（每周3-5次） |
| active | 1.725 | 高度活动（每周6-7次） |
| very_active | 1.9 | 极高活动（高强度体力劳动） |

### 热量推算规则
- 减重: TDEE - 500 kcal（约每周减 0.45kg）
- 增重: TDEE + 300 kcal
- 维持: TDEE
- 最低限制: 男 1500 kcal / 女 1200 kcal

## 身体围度类型

| 类型 | 说明 | 单位 | 范围 |
|------|------|------|------|
| waist | 腰围 | cm | 30-200 |
| hip | 臀围 | cm | 30-200 |
| chest | 胸围 | cm | 30-200 |
| arm | 臂围 | cm | 10-80 |
| thigh | 大腿围 | cm | 20-100 |
| body_fat | 体脂率 | % | 2-60 |

## 使用流程

1. 确认成员身份
2. 记录身高体重（health_metric add --type weight / --type height）
3. 使用 `calculate-bmi` 计算 BMI
4. 使用 `calculate-bmr-tdee` 计算基础代谢和每日总消耗
5. 使用 `set-goal` 设定体重管理目标（自动推算热量目标）
6. 定期通过 `mediwise-health-tracker` 记录体重
7. 通过 `diet-tracker` 记录每日饮食
8. 通过 `add-exercise` 记录运动消耗
9. 使用 `calorie-balance` 查看热量收支（含运动消耗）
10. 使用 `add-measurement` 记录身体围度
11. 使用 `body-summary` 查看综合身体报告
12. 使用 `weekly-report` 获取综合周报（含运动统计）
13. 使用 `weight-projection` 预测达标日期

## 注意事项

- goal_type 支持: lose（减重）、gain（增重）、maintain（维持）
- 每个成员同时只能有一个 active 状态的目标
- 体重数据通过 health_metrics 表记录，本 skill 只读取不写入体重数据
- 热量收支分析需要 diet-tracker 的饮食记录支持
- 运动消耗数据通过 exercise_records 表记录
- BMI/BMR/TDEE 计算需要成员有身高、体重、性别和出生日期信息
- 身体围度数据存储在 health_metrics 表中，与其他健康指标共用
- 预测功能基于近期体重变化趋势，仅供参考
- **附件管理**：身材照片、运动截图等文件的上传和管理通过 `mediwise-health-tracker` 的附件功能完成（`attachment.py`），本 skill 不直接处理文件存储。使用 `add-attachment` 动作并指定 category 为 `body_photo` 或 `exercise_photo`
