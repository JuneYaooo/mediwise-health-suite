---
name: mediwise-dream
description: 健康做梦机制 — 每日健康记录回顾与记忆整合 skill。在夜间回顾当日素材，整理重复记录、阈值提醒和待跟进事项。
trigger: scheduled (nightly ~22:00, ≥20h since last dream)
---

# MediWise · 健康回顾 Skill

> **核心理念**：做梦不是实时操作，而是深夜的回顾与沉淀。
> agent 以"做梦者"身份收集当日健康原始素材，对比历史记录，
> 整理重复出现的记录、已触发阈值和到期事项，以结构化健康备注的形式持久化。
> 本流程不作诊断、因果推断、临床判断，也不生成治疗、用药或生活方式建议。

---

## 触发条件

OpenClaw 定时任务在每晚 **22:00** 调用本 skill，触发时先检查是否满足做梦条件：

```bash
python3 {baseDir}/scripts/dream.py status --owner-id "<owner_id>"
```

检查 `ready` 字段：
- `false` → 距上次做梦不足 20 小时，**直接退出，不做任何操作**
- `true`  → 继续执行下面的流程

---

## 执行流程（五阶段）

### Phase 1 — Orient（定向）

尝试获取做梦锁，防止并发：

```bash
python3 {baseDir}/scripts/dream.py lock --owner-id "<owner_id>"
```

- `"acquired": true`  → 继续
- `"acquired": false` → 另一进程正在做梦，**退出**

---

### Phase 2 — Gather（收集素材）

```bash
python3 {baseDir}/scripts/dream.py gather --owner-id "<owner_id>"
```

输出的 `material` 包含：
- `members[]` — 每位成员今日的：
  - `snapshot`：风险等级、摘要、告警计数
  - `metrics`：原始指标列表（血压/心率/睡眠/步数等）
  - `alerts`：自上次做梦以来的告警
  - `today_mentions`：**今日对话中记录的健康提及**（当天 `mentioned_at` 的健康备注）
  - `health_notes`：历史未解决的健康备注（今日之前）
  - `new_since_last_dream`：自上次做梦新增的指标和备注数量
- `last_dream_at`：上次做梦时间
- `days_of_snapshots`：已积累多少天的快照数据

将素材保存在工作记忆中供后续阶段使用。

---

### Phase 3 — Consolidate（深度回顾）

对每位成员，仔细阅读素材，回答以下问题：

**今日对话提及（优先处理）**
- `today_mentions` 中有哪些健康信息是用户今天在对话中随口提到的？
- 这些提及是否已有对应的跟进备注？若没有，需在 Phase 4 中补充记录。
- 提及的内容是否在同一天还伴有阈值提醒？只并列展示，不推断两者存在因果关系。
- 是否有反复提及的同类记录？只统计次数，不判断病情轻重。

**指标分析**
- 今日的核心指标（血压/血糖/心率/睡眠/步数）是否触发已配置阈值？
- 与近期已记录数值相比是上升、持平还是下降？不得称为好转或恶化。
- 是否有明确的报告标记、用户阈值或既有规则提醒未被汇总？

```bash
# 若需对比近期趋势
python3 {baseDir}/scripts/daily_snapshot.py history --member-id <id> --days 7 --owner-id "<owner_id>"
```

**告警分析**
- 本次做梦周期内出现了哪些告警？严重程度？
- 同类提醒出现了几次、持续了几个记录日？不得据此判断病情。

**待跟进备注**
- 哪些健康备注已超过跟进日期，但未被标记解决？
- 是否有新增的、值得主动记录的观察？

**综合汇总**
- 本次周期有哪些重复记录、明确标记、阈值提醒和到期事项？
- 哪些已有信息需要在下一张健康记录卡片中优先展示？

---

### Phase 4 — Write（持久化洞察）

只有当存在**值得记录的重复模式或明确提醒**时，才写入健康备注。
**不要为"今日一切正常"创建备注**。

#### 4a. 触发写入的条件（满足任一即写）

| 条件 | 示例 |
|------|------|
| 连续 N 个记录日触发同一阈值 | 血压连续 3 个记录日触发用户设置阈值 |
| 告警已触发但还未记录备注 | 心率连续触发范围提醒，无已有备注 |
| 未解决备注超期 7 天以上 | 膝盖疼痛已提及 10 天未跟进 |
| 同日出现多个明确提醒 | 睡眠记录、步数记录和心率阈值提醒同日出现 |
| 新诊断/用药与当日指标同日记录 | 开始记录某药第 3 天，同时存在血压记录；只并列，不推断关联 |

#### 4b. 写入健康备注

```bash
python3 {baseDir}/scripts/health_memory.py log \
  --member-id <id> \
  --owner-id "<owner_id>" \
  --content "<观察内容，具体描述记录模式或提醒>" \
  --category observation \
  --follow-up-days <N>
```

**写作规范**：
- `content` 应具体，包含数值和日期范围：
  - ✓ "连续3个记录日晨间血压 145-152/92-96，均触发已配置范围提醒；同期档案记录为用药调整期"
  - ✗ "血压偏高"
- `--follow-up-days`：
  - 持续阈值提醒 → 3 天
  - 重复记录模式 → 7 天
  - 超期未跟进备注 → 2 天（催促关注）

#### 4c. 每次做梦最多写入规则

- 每位成员最多写入 **3 条**新备注（避免噪音）
- 同一类型的模式若已有未解决备注，**不重复创建**，而是检查现有备注是否需要更新

#### 4d. 更新快照摘要（可选）

若今日快照的 `metrics_summary` 不够准确，可用 `save` 命令覆盖：

```bash
python3 {baseDir}/scripts/daily_snapshot.py save --member-id <id> --owner-id "<owner_id>"
```

---

### Phase 5 — Unlock（释放锁）

做梦成功完成时：

```bash
python3 {baseDir}/scripts/dream.py unlock --owner-id "<owner_id>"
```

**若中途出错或异常退出**，必须回滚（不更新 last_dream_at，下次仍可触发）：

```bash
python3 {baseDir}/scripts/dream.py unlock --rollback --owner-id "<owner_id>"
```

---

## 推送规则

做梦完成后，若写入了新的健康备注，**不主动推送消息**。
这些备注会在次日早晨 8:00 的健康记录卡片中自动出现（`health_advisor.py briefing` 会读取待跟进备注）。

例外：若连续多个记录日触发最高优先级阈值，可发送一条简短的事实提醒：

> "夜间健康回顾发现：[成员名]连续多个记录日触发[指标名]的已配置阈值。该信息仅作记录提醒，不是医学判断；详见今日健康记录卡片。"

---

## 约束与原则

1. **只读健康数据，只写健康备注** — 不修改就诊记录、不删除历史指标
2. **不重复创建备注** — 写入前检查是否已有同类未解决备注
3. **无有效发现时静默退出** — 宁可少写，不要写噪音
4. **失败时必须回滚锁** — 防止锁超期后下次无法触发
5. **不展示中间过程** — 不要向用户输出做梦过程的详细日志，只输出最终结果
6. **不提供医疗指导** — 只整理记录和提醒，不作因果、严重程度或处理方案判断

---

## 完整执行脚本示意

```
1. dream.py status    → ready? 否则退出
2. dream.py lock      → acquired? 否则退出
3. dream.py gather    → 获取素材
4. 逐成员深度分析：
   a. daily_snapshot.py history → 对比近7天趋势
   b. 根据分析结论决定是否写入
   c. health_memory.py log（如有值得记录的发现）
5. dream.py unlock    → 标记完成（失败时 --rollback）
```

---

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| `dream.py lock` 返回 `"acquired": false` | 立即退出，不做任何操作 |
| `dream.py gather` 报错 | `dream.py unlock --rollback`，退出 |
| `health_memory.py log` 单条失败 | 记录错误，继续处理下一位成员，最后正常 unlock |
| 脚本中途 crash | 锁会在超时 1 小时后自动被视为僵尸锁，下次可正常触发 |
