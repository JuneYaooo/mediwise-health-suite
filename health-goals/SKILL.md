---
name: health-goals
description: "Design and manage user-confirmed action-based health goals, voluntary check-ins, progress, and meaning-gated local evidence cards. Use when a user wants to set a walking, exercise, sleep-routine, record-keeping, or custom behavior goal; check in against it; review progress; recognize a real rhythm, recovery, consistency, halfway point, or completion; or generate a shareable goal card. Do not infer a goal from ordinary health readings or issue cards for routine check-ins and arbitrary percentages."
---

# MediWise · 健康目标

把用户自己选择的行动目标整理成可打卡、可计算的过程。只有记录中出现新的行为证据时，才生成值得保存的目标证据卡。普通健康数据不进入目标系统；普通记录只生成健康卡片。

## 工作流

1. 先确认用户是否真的要设定目标。用户只是询问数据、查看记录或生成健康卡片时，不创建目标。
2. 帮用户把意图整理成一句标题、一个可记录动作、一个周期和一个数值。需要医学判断的目标请用户与专业人员确认，本 Skill 不推导处方。
3. 把完整目标复述给用户。只有用户明确确认后，才调用 `create-health-goal` 并传 `confirmed=true`。
4. 用户主动打卡，或新的手动/设备运动记录与进行中的活动目标匹配时，记录一次目标打卡。
5. 用 `health-goal-progress` 展示本周期和整体进度。普通打卡、本周期完成等事件只给轻反馈，不强行生成收藏卡。
6. 只有返回的 `new_milestones` 中出现有意义阶段，才调用 `generate-goal-card`。卡片默认隐藏姓名和精确日期，并使用里程碑触发时冻结的证据快照。

## 目标设计

支持四种目标类型：

- `weekly_frequency`：每周完成 N 次，例如“每周步行 3 次”。
- `weekly_duration`：每周累计 N 分钟，例如“每周运动 150 分钟”。
- `cumulative_count`：累计完成 N 次，例如“完成 20 次康复训练”。
- `cumulative_duration`：累计完成 N 分钟，例如“累计冥想 600 分钟”。

支持 `activity`、`sleep`、`records`、`custom` 四个领域。同一成员、同一领域只保留一个进行中的目标。周目标默认按 4 个完成周期构成整体阶段；用户可另行指定 `total_periods`。

创建前至少确认：目标标题、目标类型、目标值、开始日期；周目标还应确认总周期数。`source` 只能是 `user_defined`、`professional_defined` 或 `imported_plan`。专业人员目标和导入计划只负责原样记录，不代表 MediWise 认可其医学适用性。

目标字段和状态规则详见 [目标契约](references/goal-contract.md)。

## 打卡、进度与里程碑

手动打卡使用 `health-goal-checkin`。频次目标每条有效打卡计一次；时长目标必须提供 `duration_minutes`。通过来源记录自动关联时，同时传 `source_record_type` 与 `source_record_id`，重复导入不会重复计数。

普通第一次打卡不发卡，普通单周期完成也不发卡。系统只为以下行为含义创建幂等里程碑：

- `rhythm`：首次完整完成一个周周期；累计目标则需至少三次行动分布在三个日期且跨越至少两天。
- `recovery`：首次在相隔至少 14 天后重新记录行动；不评价中间的空白。
- `consistency`：连续完成 2、4 或 8 个相邻周期。
- `halfway`：规模足够的目标首次越过 50%，且同一次行动没有更强的阶段含义。
- `completion`：整体目标达到 100%，同时自动将目标标记为完成。

同一次行动最多创建一个可发卡阶段，优先级为：完成、重新接上、连续稳定、节奏建立、走过一半。不要为 25%/75%、普通打卡或重复的每周完成生成卡片。

不要自行补写打卡，不要把步数、体重、心率或其他普通读数自动等同于一次目标行动。当前仅新的手动运动记录和明确标记为 `activity` 的设备活动记录可自动关联进行中的活动目标；普通步数不会自动打卡。

## 目标证据卡

`generate-goal-card` 只生成 HTML/PNG 静态卡，不生成视频。先由里程碑含义限制可用结构，再在兼容结构中结合明确偏好、拒绝项和近期历史做可复现选择：`timeline`、`calendar`、`ledger`、`repair`、`route`、`archive`、`letter`。样式不能覆盖或篡改阶段含义。

每张卡必须回答：发生了什么、为什么值得记录、证据是什么、下一步是什么。下一步只延续用户自己设定的目标，不自动加量或提供医疗建议。卡片从里程碑 `evidence` 冻结快照取值，不从当前进度回填旧卡。默认隐藏成员姓名与精确日期；仅在用户明确要求后传 `show_member_name` 或 `show_exact_date`。卡片边界详见 [卡片边界](references/card-boundaries.md)。

## 动作

| 动作 | 说明 |
|---|---|
| `create-health-goal` | 创建经用户明确确认的目标；必须传 `confirmed=true` |
| `list-health-goals` | 查看成员的进行中/暂停目标 |
| `view-health-goal` | 查看目标定义和当前进度 |
| `health-goal-checkin` | 主动打卡或链接一条来源记录 |
| `health-goal-progress` | 重新计算目标进度并落库新里程碑 |
| `update-health-goal-status` | 切换 `active/paused/completed/abandoned` |
| `list-goal-milestones` | 查看已达成的阶段节点 |
| `generate-goal-card` | 领取或重绘有意义阶段的静态目标证据卡 |
| `list-goal-cards` | 查看目标的本地卡片历史 |
| `goal-card-preferences` | 查看卡片语气、密度和样式偏好 |
| `update-goal-card-preferences` | 更新喜欢、拒绝和中性样式 |

## 边界

- 不根据年龄、性别、疾病、药物、体重、心率、检验结果或设备读数推导目标值。
- 不提供诊断、治疗、运动处方、营养处方或目标是否医学适宜的判断。
- 不因用户查看健康数据而静默创建目标，也不因没有打卡而发送羞辱、恐吓或损失厌恶文案。
- 没有足够证据形成有意义阶段时，宁可不生成卡。
- 数据与卡片在 MediWise 本地数据目录中生成；删除沿用系统现有的软删除语义。
- PNG 导出需要本机 Chrome/Chromium；不可用时仍保留可直接打开的本地 HTML。
