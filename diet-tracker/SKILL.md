---
name: diet-tracker
description: "Diet and nutrition tracking: log meals, manage food items, view daily/weekly nutrition summaries, analyze calorie trends. Integrates with mediwise-health-tracker and weight-manager."
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

### food_lookup.py — 食物营养查询

| 动作 | 子命令 | 必要参数 | 可选参数 | 说明 |
|------|--------|----------|----------|------|
| food-lookup | search | params.query | params.limit (默认5), params.source (auto/cfcd/brands/usda) | 三层数据源搜索食物营养（CFCD6 → 中国品牌外食 → USDA） |
| food-stats | stats | — | — | 查看食物数据库概况（各数据源条目数） |

数据来源（按优先级）：
1. **CFCD6**（离线）：《中国食物成分表标准版第6版》1657 条，覆盖粮谷、肉蛋奶、蔬果、水产等
2. **cn-brands**（离线）：339 条，奶茶、外卖、便利店、火锅等外食场景
3. **USDA FoodData Central**（在线）：国际食材兜底，需配置 `USDA_API_KEY` 环境变量

## 使用流程

**记录一餐的标准流程（不得跳步）：**

1. 确认成员身份（通过 mediwise-health-tracker 的 list-members）
2. **逐一查询每种食物的营养数据**（`food-lookup search`，见下方"强制规则"）
3. 用查询到的营养数据调用 `add-meal`，通过 `--items` JSON 一次录入多个食物
4. 如需追加食物，使用 `add-item` 向已有餐次添加
5. 使用 `daily-summary` 查看当天营养摄入
6. 使用 `weekly-summary` 或 `calorie-trend` 查看长期趋势

## 营养数据强制规则

**禁止用 AI 自身知识直接估算营养数值写入数据库。** 记录每种食物之前，必须先调用 `food-lookup search` 查询，用数据库返回的数据填充 `--items`。

> **自动填充说明**：若 `--items` 中某条目未提供热量数据，`diet.py` 会自动调用内部 food_lookup 数据库补全营养值，并在 `note` 字段标注 `[自动填充]` 及数据来源。此行为仅查询本地数据库（不调用外部 API），补全结果与显式 `food-lookup search` 一致。agent 仍应优先显式查询以便向用户展示候选项，但自动填充是兜底保障而非绕过规则。

```bash
# 步骤 1：先查每种食物
python3 {baseDir}/scripts/food_lookup.py search --query "炸排骨" --owner-id "<sender_id>"
python3 {baseDir}/scripts/food_lookup.py search --query "米饭" --owner-id "<sender_id>"

# 步骤 2：用查询结果里的营养数据填 --items，再记录
python3 {baseDir}/scripts/diet.py add-meal \
  --member-id <id> --meal-type lunch --meal-date 2025-03-15 \
  --items '[{"food_name":"炸排骨","amount":150,"unit":"g","calories":298,"protein":21.2,"fat":19.3,"carbs":9.1,"note":"来源:CFCD6"}]' \
  --owner-id "<sender_id>"
```

**查询未命中时的处理：**
- 三层数据源（CFCD6 → 中国品牌外食 → USDA）都未找到时，告知用户"未查到该食物的营养数据"，**询问用户是否手动输入营养值，或跳过该条目**，不得自行估算后直接写入。
- 查到多个候选项时，展示给用户确认，选择最贴近的后再录入。
- 记录时在 `note` 字段写明数据来源（如"来源：CFCD6"、"来源：用户手动输入"）。

## items JSON 格式

`--items` 参数接受 JSON 数组。**所有营养字段必须来自 `food-lookup search` 的查询结果**，不得由 AI 自行估算填充：
```json
[
  {"food_name": "鸡胸脯肉", "amount": 150, "unit": "g", "calories": 158, "protein": 31.6, "fat": 3.2, "carbs": 0.0, "note": "来源:CFCD6"},
  {"food_name": "米饭", "amount": 200, "unit": "g", "calories": 232, "protein": 4.6, "fat": 0.6, "carbs": 51.5, "note": "来源:CFCD6"}
]
```

自动换算规则：CFCD6/USDA 数据按 `amount`（克）换算；中国品牌/外食数据按每份直接使用。

## 注意事项

- **每次调用脚本必须携带 `--owner-id`（强制）**：从会话上下文获取发送者 ID（格式 `<channel>:<user_id>`，如 `feishu:ou_xxx` 或 `qqbot:12345`），作为所有脚本的 `--owner-id` 参数，不得省略。
- **禁止 AI 估算营养数据**：所有热量/蛋白质/脂肪/碳水/膳食纤维数值必须来自 `food-lookup search`，或经用户明确确认的手动输入，不得由 AI 凭自身知识估算后直接写入。
- `note` 字段必须记录数据来源，便于用户事后核查。
- meal_type 支持: breakfast（早餐）、lunch（午餐）、dinner（晚餐）、snack（加餐/零食）
