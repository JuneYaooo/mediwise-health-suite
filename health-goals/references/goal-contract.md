# 健康目标契约

## 目标创建

`confirmed=true` 是硬性写入门槛。Agent 必须先把标题、目标类型、目标值、周期、开始日期和来源复述给用户；含糊的“我应该多运动吗”不是确认。

目标只描述可记录的行动：

| 字段 | 允许值或含义 |
|---|---|
| `domain` | `activity`、`sleep`、`records`、`custom` |
| `goal_type` | `weekly_frequency`、`weekly_duration`、`cumulative_count`、`cumulative_duration` |
| `target_value` | 正数；频次目标单位为次，时长目标单位为分钟 |
| `total_periods` | 周目标的整体周期数，默认 4；累计目标忽略此字段 |
| `week_start` | 0–6，分别表示周一至周日 |
| `source` | `user_defined`、`professional_defined`、`imported_plan` |
| `rules` | 仅保存用户明确提出的中性匹配条件；不可放入推导出的医疗阈值 |

同一成员和领域只允许一个 `active` 目标。暂停目标可以恢复，但恢复时仍需满足唯一活动目标约束；已完成或已放弃目标不能直接恢复。

## 打卡证据

频次目标每条打卡计 1 次；时长目标使用 `duration_minutes`，不以设备热量或步数换算时长。`occurred_at` 代表行动发生时间，而非导入时间。

来源关联必须成对提供 `source_record_type` 和 `source_record_id`。数据库对同一目标和来源身份建立唯一约束，因此设备重复同步、命令重试或网络重试不会重复累计。

支持的当前自动来源：

- `exercise_record`：新提交的手动运动记录。
- `health_metric_activity`：新提交且规范化类型明确为 `activity` 的设备记录。

`steps` 等普通连续指标不自动形成打卡。

## 进度语义

周目标同时返回：当前周期完成值、当前周期比例、已完成周期数、整体周期比例。累计目标返回累计值和整体比例。比例最高显示为 100%，但原始打卡继续作为事实保留。

只有带 `total_periods` 的周目标或累计目标可以自动完成。目标整体比例达到 100% 后状态变为 `completed`。

## 有意义阶段

里程碑不是进度日志。第一次普通打卡、每个普通完成周期、25% 和 75% 都不创建收藏卡节点。允许的阶段：

| 类型 | 最低证据 | 幂等键 |
|---|---|---|
| `rhythm` | 首个完整周周期；或累计目标的三次行动分布在至少三个日期、跨至少两天 | `rhythm-established` |
| `recovery` | 首次相邻记录间隔至少 14 天后再次记录 | `recovery` |
| `consistency` | 连续 2/4/8 个相邻周期达标 | `consistency-N` |
| `halfway` | 周目标至少 4 周、累计次数至少 6 次或累计时长至少 120 分钟，并首次越过 50% | `halfway` |
| `completion` | 整体进度首次达到 100% | `completion` |

同一条行动最多创建一个阶段，按 `completion > recovery > consistency > rhythm > halfway` 选择。较强含义覆盖同一时点的较弱含义，避免一条打卡连续弹出多张卡。

每个里程碑由 `goal_id + milestone_key + goal_version` 唯一标识。重新计算进度不会重复创建同一阶段；目标规则未来若显式修订，应提升 `goal_version`，不得篡改旧证据。

`evidence.schema_version=2` 表示冻结快照。它至少保存触发当时的目标标题、目标类型、目标值、打卡数、行动日期摘要、周期完成数、整体进度和剩余量。卡片必须读取此快照，不能用后续当前进度覆盖旧阶段。
