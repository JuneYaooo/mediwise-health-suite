---
name: weight-manager
description: "Weight management: set goals, track progress, translate daily fluctuations into robust trends, generate personalized share-safe Weight Story cards across 24 dynamic styles, preserve legacy weight truth cards, log exercise, calculate BMI/BMR/TDEE, and analyze body composition. Integrates with diet-tracker and mediwise-health-tracker."
---

# MediWise · 体重与运动 Skill

## 概述

提供体重目标设定、进度追踪、趋势分析、体重波动翻译、可分享图卡、热量估算、BMI/BMR/TDEE 估算、运动记录和身体围度记录功能。体重数据复用 `health_metrics` 表（weight 类型），饮食热量数据来自 `diet_records` 表，运动消耗数据来自 `exercise_records` 表。

本 Skill 只记录和展示数据、用户目标差异与模型估算，不提供减重、增重、饮食、运动或其他健康指导。运动消耗只代表已记录活动；缺少完整基础代谢与日常活动数据时，不得把结果表述为真实热量缺口或预测治疗效果。

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
| set-goal | set | --member-id, --goal-type, --start-weight, --target-weight | --start-date, --target-date, --daily-calorie-target, --note | 记录用户自行确定的减重/增重/维持目标；不会自动生成热量目标 |
| view-goal | view | --member-id | | 查看当前活跃目标 |
| update-goal | update | --goal-id | --target-weight, --target-date, --daily-calorie-target, --note | 修改目标参数 |
| complete-goal | complete | --goal-id | | 标记目标完成 |
| abandon-goal | abandon | --goal-id | | 放弃目标 |

### weight_analysis.py — 进度分析

| 动作 | 子命令 | 必要参数 | 可选参数 | 说明 |
|------|--------|----------|----------|------|
| weight-progress | progress | --member-id | | 当前进度（已减/增多少，完成百分比） |
| weight-trend | trend | --member-id | --days (默认 30) | 体重趋势（N 天变化，平均变化速率） |
| calorie-balance | calorie-balance | --member-id | --days (默认 7) | 分别汇总已记录饮食摄入和运动消耗，不计算热量缺口 |
| weekly-report | weekly-report | --member-id | --end-date | 周报（体重变化 + 饮食热量 + 运动记录 + 目标差异） |
| weight-projection | projection | --member-id | | 按当前速度预测达标日期 |

### weight_truth_card.py — 体重翻译与分享卡片

| 动作 | 子命令 | 必要参数 | 可选参数 | 说明 |
|------|--------|----------|----------|------|
| weight-truth | analyze | --member-id | --days（默认 14）、--as-of | 将单日变化和稳健长期趋势分开解释，返回结构化分析，不生成处方 |
| select-weight-card-style | select-style | --member-id | --domain（weight/sleep/vitals/intake/activity/adherence/records/family，默认 weight）、--days、--scene、--tone、--density、--preferred-style、--disliked-style、--recent-style、--pinned-style、--surprise-level、--seed | 为健康译报从共享模板中进行可解释、非均匀、可复现的选择；旧动作名作为兼容外壳保留，只返回选择结果，不冒充已经渲染的卡片 |
| weight-card-preferences | get | --member-id |  | 读取本地风格偏好与最近生成历史，不读取或返回健康数值 |
| update-weight-card-preferences | update | --member-id | --tone、--density、--surprise-level、--like-style、--dislike-style、--neutral-style、--pin-style、--clear-pin、--generated-style、--clear-history | 更新私有风格记忆；成员 ID 摘要存储，文件权限为 0600 |
| generate-weight-story-card | generate-story | --member-id | --domain（weight/sleep/vitals/intake/activity/adherence/records/family，默认 weight）、--days、--scene、--tone、--density、--style（默认 auto）、--format（html/png/svg/both/all）、隐私开关、偏好/历史、--seed、--no-save-history | 生成「MediWise 健康译报」：观察所选域的真实记录，选择共享模板之一，导出 HTML/PNG/动画 SVG 并记录最近风格；旧动作名作为兼容外壳保留 |
| generate-weight-card | generate | --member-id | --days、--format（html/png/both）、--show-exact-weight、--show-member-name、--show-exact-date、--context | 生成 1080×1440 的「体重真相卡」；默认脱敏，可导出 HTML 和 PNG |

分析会先把同一天的多次体重测量聚合为中位数，再使用 Theil–Sen 稳健斜率估计长期方向。少于 7 个记录日或覆盖跨度不足 7 天时，只显示“记录不足”，不宣称趋势已经形成。新体重译报还会并列分析同期已有的饮食摄入、运动和睡眠记录，生成一段综合解读，并依据真实模式形成「阶段肖像」和默认脱敏的分享包装。分享结构采用结论先行、数字证明、完整分析、保存理由，但必须返回 `clickbait: false`。饮食只统计有营养数据的记录日，未记录日不按 0 kcal；运动消耗不冒充全天总能量消耗，也不与摄入相减生成热量缺口；睡眠只描述记录时长。同期变化只作为线索，不得写成体重变化的原因。文案由确定性规则产生，不调用模型自由发挥，也不预测达标日期。

`--format svg` 额外导出一张动画 SVG：24 套模板各自带一种动作模式，动画时间轴对应日历时间轴，未记录的日子表现为真实的停顿，不做插值。冻结后的海报帧与静态 HTML 卡逐像素一致，因此动画不会改变卡片对数据的断言。`prefers-reduced-motion: reduce` 时直接退化为该冻结帧，闪烁频率不超过 3 次/秒。动画卡与静态卡使用同一组隐私开关；在脱敏模式下，记录间隔按桶量化，不暴露精确天数。`--format both` 仍是原来的 html+png，`all` 才是三种产物都要。

分享卡默认隐藏姓名、绝对体重、目标体重、精确日期、用药、检验和其他医疗数据。仅在用户明确要求时，才通过 `show_exact_weight`、`show_member_name` 或 `show_exact_date` 展示对应字段。`context` 只能用于展示已经记录的中性事实；不得把时间上同时发生的饮食、睡眠或运动记录写成体重变化原因。

风格选择器包含 12 个叙事家族、24 套动态模板。每套都有唯一 `layout-mode`、唯一内容角色，以及体重、摄入、运动、睡眠、记录行为或综合分析中的一个主导任务。选择器综合当前可用信号、数据资格、使用场景、语气/密度偏好、用户明确喜欢或拒绝、最近生成历史和 8%～18% 的探索概率。它可以识别「故事序章」「剧情反转」「信号变清楚」「双重曝光」「长线视野」等记录时刻，并生成只基于记录行为的安全人格标签。不得用 BMI、绝对体重、趋势方向、性别、年龄、疾病、用药或目标完成度选择审美。

对外统一把八域完整链路称为 **「MediWise 健康译报」**；当 `domain=weight` 时可称为 **「MediWise 体重译报」展示案例**。`generate-weight-story-card` 与 `select-weight-card-style` 是为兼容保留的动作名，不传 `--domain` 时仍默认 `weight`。旧 `weight-truth` 和 `generate-weight-card` 是纯体重兼容入口，必须保持原行为，不得静默改名或改变输出结构。

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
| suggest-calories | suggest-calories | --member-id | | 兼容入口；明确说明 MediWise 不生成每日热量建议 |
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

### 热量目标边界

MediWise 不根据 TDEE 自动生成减重、增重或维持所需的每日热量目标。`daily_calorie_target` 只记录用户本人或专业人员已经确定的目标。

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
2. 记录身高体重（通过 `mediwise-health-tracker` 的 `add-metric` 动作，type 填 weight / height）
3. 使用 `calculate-bmi` 计算 BMI
4. 使用 `calculate-bmr-tdee` 计算基础代谢和每日总消耗
5. 使用 `set-goal` 记录用户已经确定的体重目标；如用户或专业人员已确定每日热量目标，可一并记录
6. 定期通过 `mediwise-health-tracker` 记录体重
7. 通过 `diet-tracker` 记录每日饮食
8. 通过 `add-exercise` 记录运动消耗
9. 使用 `calorie-balance` 查看热量收支（含运动消耗）
10. 使用 `add-measurement` 记录身体围度
11. 使用 `body-summary` 查看综合身体报告
12. 使用 `weekly-report` 获取综合周报（含运动统计）
13. 使用 `weight-projection` 预测达标日期
14. 使用 `weight-truth` 区分单日波动和稳健长期趋势
15. 需要个性化视觉建议时使用 `select-weight-card-style`，按用户请求传入八域之一的 `--domain`，解释选择原因和数据资格
16. 需要完整生成时使用 `generate-weight-story-card` 并传入对应 `--domain`；除非用户明确要求，否则保留默认脱敏设置
17. 用户明确要求旧版体重真相卡或兼容流程时使用 `generate-weight-card`

## 注意事项

- 当前公开版本只用于个人本地档案；身份隔离由安装时的个人模式和 action 适配层处理，不向普通用户暴露或索取 `owner_id`。
- goal_type 支持: lose（减重）、gain（增重）、maintain（维持）
- 每个成员同时只能有一个 active 状态的目标
- 体重数据通过 health_metrics 表记录，本 skill 只读取不写入体重数据
- 热量收支分析需要 diet-tracker 的饮食记录支持
- 运动消耗数据通过 exercise_records 表记录
- BMI/BMR/TDEE 计算需要成员有身高、体重、性别和出生日期信息
- 身体围度数据存储在 health_metrics 表中，与其他健康指标共用
- 预测功能基于近期体重变化趋势，仅供参考
- 「健康译报」聚焦所选域的观察叙事；其中体重展示案例和旧「体重真相卡」聚焦体重波动。它们都不替代包含完整私密信息的「健康记录卡片」
- 所有健康译报和旧体重卡片都只陈述记录事实和统计趋势；相关线索不代表因果，不得据此自动生成饮食、热量或运动处方
- PNG 导出需要 Chrome/Chromium；未安装时仍会返回可直接打开的本地 HTML
- **附件管理**：身材照片、运动截图等文件的上传和管理通过 `mediwise-health-tracker` 的附件功能完成（`attachment.py`），本 skill 不直接处理文件存储。使用 `add-attachment` 动作并指定 category 为 `body_photo` 或 `exercise_photo`
