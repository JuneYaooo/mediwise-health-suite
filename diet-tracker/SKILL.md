---
name: diet-tracker
description: "Diet and nutrition tracking: log meals, manage food items, view daily/weekly nutrition summaries, analyze calorie trends. Integrates with mediwise-health-tracker and weight-manager."
---

# MediWise · 饮食追踪 Skill

## 概述

提供每餐饮食记录、食物条目管理、每日/每周营养摘要、热量趋势分析等功能。与 `mediwise-health-tracker` 共享数据库，可与 `weight-manager` 联动形成"饮食 → 热量 → 体重"完整闭环。

本 Skill 只记录和展示饮食数据、数据来源、用户目标差异与记录完整度，不提供营养治疗或饮食指导。内置参考区间只用于客观对比，不据此推荐用户增加、减少或替换食物。

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
| food-lookup | search | params.query | params.limit (默认5), params.source (auto/cfcd/brands/usda/openfoodfacts/off/all) | 按可用数据源搜索食物营养（本地数据包 → USDA → Open Food Facts） |
| food-stats | stats | — | — | 查看食物数据库概况（各数据源条目数） |

数据来源（按优先级）：
1. **CFCD6 / cn-brands 本地数据包**（可选）：仓库不捆绑这些数据；只有在确认来源授权后，将兼容格式的数据安装到 `diet-tracker/data/` 才会启用
2. **USDA FoodData Central**（在线）：需配置 `USDA_API_KEY` 环境变量
3. **Open Food Facts**（在线，包装/品牌食品）：免 Key，但需显式设置 `OPENFOODFACTS_ENABLED=1`；数据采用 ODbL 1.0，结果会返回产品页和许可证。正式使用应按官方文档填写 API usage form、设置可联系的 User-Agent，并避免搜索即输入等高频调用

`food-stats` 会返回每个数据源的可用状态、来源网址、许可证和本地数据目录。所有在线来源都可用 `MEDIWISE_FOOD_ONLINE_ENABLED=0` 强制关闭。远程 API 只收到食物查询词及语言/分页参数，不得发送 `owner_id`、`member_id`、餐次记录或健康数据。没有任何来源可用时，查询返回 `status: unavailable`，不得把“数据源不可用”当成“该食物不存在”。

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

> **自动填充说明**：若 `--items` 中某条目未提供热量数据，`diet.py` 会尝试调用本地 food_lookup 数据包补全营养值，并在 `note` 字段标注 `[自动填充]` 及数据来源。仓库默认不捆绑本地数据包；数据源不可用时必须请用户补充营养标签或显式配置在线来源，不能凭模型知识写入估算值。

```bash
# 步骤 1：先查每种食物
python3 {baseDir}/scripts/food_lookup.py search --query "炸排骨"
python3 {baseDir}/scripts/food_lookup.py search --query "米饭"

# 步骤 2：用查询结果里的营养数据填 --items，再记录
python3 {baseDir}/scripts/diet.py add-meal \
  --member-id <id> --meal-type lunch --meal-date 2025-03-15 \
  --items '[{"food_name":"炸排骨","amount":150,"unit":"g","calories":298,"protein":21.2,"fat":19.3,"carbs":9.1,"note":"来源:CFCD6"}]'
```

**查询未命中时的处理：**
- 结构化来源（本地数据包 → USDA → Open Food Facts）都未找到时，如运行环境具备网页检索能力，只能查询品牌官网、政府/高校数据库或可核验的官方营养标签页，并在 `note` 保留页面 URL、每 100g/每份基准和访问日期。不得采用博客、营销软文、搜索摘要或模型记忆中的数值。
- 仍无可核验来源时，告知用户“未查到该食物的营养数据”，**询问用户是否按包装标签手动输入，或跳过该条目**，不得自行估算后直接写入。
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

自动换算规则：CFCD6/USDA/Open Food Facts 数据按 `amount`（克）换算；中国品牌/外食本地数据按每份直接使用。使用 Open Food Facts 时应向用户提示其为社区维护数据，并优先核对具体条码对应的产品页。

## 注意事项

- 当前公开版本只用于个人本地档案；身份隔离由安装时的个人模式和 action 适配层处理，不向普通用户暴露或索取 `owner_id`。
- **禁止 AI 估算营养数据**：所有热量/蛋白质/脂肪/碳水/膳食纤维数值必须来自 `food-lookup search`，或经用户明确确认的手动输入，不得由 AI 凭自身知识估算后直接写入。
- `note` 字段必须记录数据来源，便于用户事后核查。
- meal_type 支持: breakfast（早餐）、lunch（午餐）、dinner（晚餐）、snack（加餐/零食）
