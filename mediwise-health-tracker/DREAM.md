---
name: mediwise-dream
description: 健康做梦机制 — 每日健康信息回顾与记忆整合 skill。在夜间回顾当日健康素材，提炼规律和隐患，将洞察写入持久化记忆。
trigger: scheduled (nightly ~22:00, ≥20h since last dream)
---

# MediWise 健康做梦 (Dream) Skill

> **核心理念**：做梦不是实时操作，而是深夜的回顾与沉淀。
> agent 以"做梦者"身份收集当日健康原始素材，对比历史趋势，
> 提炼出值得记录的规律与隐患，以结构化健康备注的形式持久化。

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
- 提及的内容与今日指标或告警是否有关联？（如"今天有点晕"+ 血压偏高）
- 是否有反复提及的症状，暗示问题比单次描述更严重？

**指标分析**
- 今日的核心指标（血压/血糖/心率/睡眠/步数）是否在正常范围？
- 与近期趋势相比是好转、稳定还是恶化？（需查快照历史对比）
- 是否有单次异常但未触发告警的值？（如血压偶尔偏高）

```bash
# 若需对比近期趋势
python3 {baseDir}/scripts/daily_snapshot.py history --member-id <id> --days 7 --owner-id "<owner_id>"
```

**告警分析**
- 本次做梦周期内出现了哪些告警？严重程度？
- 是偶发性异常还是持续性问题？

**待跟进备注**
- 哪些健康备注已超过跟进日期，但未被标记解决？
- 是否有新增的、值得主动记录的观察？

**综合判断**
- 本次做梦周期的整体健康状态：稳定 / 需关注 / 需及时处理
- 是否有需要在下次简报中重点突出的事项？

---

### Phase 4 — Write（持久化洞察）

只有当存在**值得记录的非平凡发现**时，才写入健康备注。
**不要为"今日一切正常"创建备注**。

#### 4a. 触发写入的条件（满足任一即写）

| 条件 | 示例 |
|------|------|
| 连续 N 天某指标偏高/偏低 | 血压连续 3 天 >140/90 |
| 告警已触发但还未记录备注 | 心率持续偏高，无已有备注 |
| 未解决备注超期 7 天以上 | 膝盖疼痛已提及 10 天未跟进 |
| 多个指标同时出现轻度异常 | 睡眠差 + 步数下降 + 轻度心率偏高 |
| 新诊断/用药与当日指标有关联 | 开始降压药第 3 天，今日血压数据 |

#### 4b. 写入健康备注

```bash
python3 {baseDir}/scripts/health_memory.py log \
  --member-id <id> \
  --owner-id "<owner_id>" \
  --content "<观察内容，具体描述模式或隐患>" \
  --category observation \
  --follow-up-days <N>
```

**写作规范**：
- `content` 应具体，包含数值和日期范围：
  - ✓ "连续3天晨间血压 145-152/92-96，均高于正常上限，已在降压药调整期"
  - ✗ "血压偏高"
- `--follow-up-days`：
  - 持续告警 → 3 天
  - 轻度异常模式 → 7 天
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
这些备注会在次日早晨 8:00 的简报中自动出现（`health_advisor.py briefing` 会读取待跟进备注）。

例外：若发现**严重的、需要立即关注的隐患**（如连续 5 天心率异常），可发送一条简短提醒：

> "夜间健康回顾发现：[成员名]连续多日[指标名]异常，建议尽快关注或就医。详见今日简报。"

---

## 约束与原则

1. **只读健康数据，只写健康备注** — 不修改就诊记录、不删除历史指标
2. **不重复创建备注** — 写入前检查是否已有同类未解决备注
3. **无有效发现时静默退出** — 宁可少写，不要写噪音
4. **失败时必须回滚锁** — 防止锁超期后下次无法触发
5. **不展示中间过程** — 不要向用户输出做梦过程的详细日志，只输出最终结果

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
