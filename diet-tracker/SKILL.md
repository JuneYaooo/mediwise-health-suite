---
name: diet-tracker
description: >-
  日常饮食记录与营养分析。用于记录每餐、维护食物条目、查看每日或每周营养摘要、
  分析热量趋势，并与 `mediwise-health-tracker`、`weight-manager` 联动形成饮食与体重闭环。
  Use when recording meals, managing food items, reviewing nutrition summaries,
  or analyzing calorie trends for a family member.
---

# diet-tracker

## 概述

提供每餐饮食记录、食物条目管理、每日/每周营养摘要、热量趋势分析等功能。与 `mediwise-health-tracker` 共享数据库，可与 `weight-manager` 联动形成"饮食 → 热量 → 体重"完整闭环。

## 数据模型

### diet_records（一餐记录）
| 字段 | 说明 |
|------|------|
| id | 记录 ID |
| member_id | 成员 ID |
| meal_type | 餐次: breakfast/lunch/dinner/snack |
| meal_date | 日期 YYYY-MM-DD |
| meal_time | 时间 HH:MM（可选） |
| total_calories | 总热量 kcal |
| total_protein | 总蛋白质 g |
| total_fat | 总脂肪 g |
| total_carbs | 总碳水 g |
| total_fiber | 总膳食纤维 g |
| note | 备注 |

### diet_items（食物条目）
| 字段 | 说明 |
|------|------|
| id | 条目 ID |
| record_id | 关联 diet_records.id |
| food_name | 食物名称 |
| amount | 数量 |
| unit | 单位（g/ml/份/个等） |
| calories | 热量 kcal |
| protein | 蛋白质 g |
| fat | 脂肪 g |
| carbs | 碳水 g |
| fiber | 膳食纤维 g |
| note | 备注 |

## 功能列表

### diet.py — 饮食记录 CRUD

| 动作 | 子命令 | 必要参数 | 可选参数 | 说明 |
|------|--------|----------|----------|------|
| add-meal | add-meal | --member-id, --meal-type, --meal-date | --meal-time, --note, --items (JSON) | 添加一餐记录（可同时包含多个食物条目） |
| add-item | add-item | --record-id, --food-name | --amount, --unit, --calories, --protein, --fat, --carbs, --fiber, --note | 向已有餐次追加食物条目 |
| list | list | --member-id | --date, --start-date, --end-date, --meal-type, --limit | 查看饮食记录 |
| delete | delete | --id | --type (record/item) | 删除记录或条目 |
| daily-summary | daily-summary | --member-id, --date | | 某日营养摘要 |

### nutrition.py — 营养分析

| 动作 | 子命令 | 必要参数 | 可选参数 | 说明 |
|------|--------|----------|----------|------|
| weekly-summary | weekly-summary | --member-id | --end-date | 一周营养趋势（每日热量、平均三大营养素） |
| calorie-trend | calorie-trend | --member-id | --days (默认 7) | 热量趋势分析（N 天每日总热量） |
| nutrition-balance | nutrition-balance | --member-id | --days (默认 7) | 三大营养素比例分析 |

## 使用流程

1. 确认成员身份（通过 mediwise-health-tracker 的 list-members）
2. 使用 `add-meal` 记录一餐，通过 `--items` JSON 一次录入多个食物
3. 如需追加食物，使用 `add-item` 向已有餐次添加
4. 使用 `daily-summary` 查看当天营养摄入
5. 使用 `weekly-summary` 或 `calorie-trend` 查看长期趋势

## items JSON 格式

`--items` 参数接受 JSON 数组：
```json
[
  {"food_name": "米饭", "amount": 200, "unit": "g", "calories": 232, "protein": 4.6, "fat": 0.6, "carbs": 51.5, "fiber": 0.3},
  {"food_name": "炒青菜", "amount": 150, "unit": "g", "calories": 45, "protein": 2.1, "fat": 2.5, "carbs": 3.2, "fiber": 1.8}
]
```

## 注意事项

- 热量和营养素数值由 AI 估算或用户手动输入，不保证精确
- 建议 AI 在记录时主动帮用户估算常见食物的营养成分
- meal_type 支持: breakfast（早餐）、lunch（午餐）、dinner（晚餐）、snack（加餐/零食）
