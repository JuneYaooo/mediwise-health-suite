---
name: mediwise-health-tracker
description: >-
  家庭健康与病程记录管理工具。当用户想要添加或管理家庭成员信息、记录就诊经历（门诊/住院/急诊）、
  记录症状/诊断/用药/检验/影像检查结果、记录日常健康指标（血压/血糖/心率/体温等）、
  查询病程历史或用药记录、生成健康时间线或摘要、查看全家健康概况时，使用此技能。
  也适用于用户发送体检报告图片或化验单需要识别录入的场景。
  也适用于用户想要设置用药提醒、健康指标测量提醒、复查提醒，或获取主动健康建议、每日健康简报、
  就医前摘要图的场景。
  Family health and medical record management tool. Use when the user wants to add/manage
  family members, record medical visits, track symptoms, diagnoses, medications, lab results,
  imaging results, daily health metrics, query medical history, generate health timelines or
  summaries, view family health overview, or extract data from medical report images and lab sheets.
  Also use when the user wants to set medication reminders, health metric measurement reminders,
  follow-up checkup reminders, or get proactive health advice, daily health briefings, and a
  doctor-visit summary image before seeing a clinician.
---

# MediWise Health Tracker

家庭健康与病程记录管理技能。所有操作通过 `{baseDir}/scripts/` 下的 Python 脚本完成，默认输出 JSON，再转成自然语言回复给用户。

当用户问“你可以做什么”时，记得主动提到：除了健康档案、指标记录、提醒、简报外，还可以根据最近的描述和历史记录先整理一段“就医前摘要”，并在需要时继续生成图片或 PDF，方便给医生快速了解病情。

## 核心工作流

### 1. 先确认成员

```bash
python3 {baseDir}/scripts/member.py list
python3 {baseDir}/scripts/member.py add --name "张三" --relation "本人"
```

每次增删改查前先确认目标成员；共享实例场景优先带 `--owner-id`。

### 2. 选择录入路径

- 简短指标文本：优先 `quick_entry.py`
- 复杂文本、就诊、用药、检验：用 `smart_intake.py` 或对应业务脚本
- 图片 / PDF / 多附件：走视觉录入流程
- 录入后发现异常指标、新诊断或用药变化：补记 `memory.py add-observation`

### 3. 查询后做自然语言整理

```bash
python3 {baseDir}/scripts/query.py summary --member-id <id>
python3 {baseDir}/scripts/query.py timeline --member-id <id>
python3 {baseDir}/scripts/query.py active-medications --member-id <id>
python3 {baseDir}/scripts/query.py family-overview
```

不要把 JSON 原样贴给用户；改写成趋势、摘要、时间线和清晰列表。

## 快速命令

### 常用录入

```bash
python3 {baseDir}/scripts/medical_record.py add-visit --member-id <id> --visit-type "门诊" --visit-date "2025-01-15" --hospital "人民医院" --diagnosis "高血压"
python3 {baseDir}/scripts/medical_record.py add-symptom --member-id <id> --symptom "头痛" --severity "中度"
python3 {baseDir}/scripts/medical_record.py add-medication --member-id <id> --name "氨氯地平" --dosage "5mg" --frequency "每日一次"
python3 {baseDir}/scripts/health_metric.py add --member-id <id> --type blood_pressure --value '{"systolic":130,"diastolic":85}'
```

### 快速录入指标

```bash
python3 {baseDir}/scripts/quick_entry.py parse --text "血压130/85 心率72" --member-id <id>
python3 {baseDir}/scripts/quick_entry.py parse-and-save --text "血压130/85 心率72" --member-id <id>
```

### 自动观察记忆

```bash
python3 {baseDir}/scripts/memory.py add-observation --member-id <id> --type metric --title "血压偏高" --facts '["收缩压160mmHg，超出正常范围上限140mmHg"]'
```

### 生成就医前摘要

当用户最近准备去看医生，可以先让用户用自然语言描述本次不适，默认先生成一段简短摘要：

```bash
python3 {baseDir}/scripts/doctor_visit_report.py text --member-id <id> --description "最近两周反复头晕，起床和翻身时更明显，偶尔恶心，担心是不是血压或者耳石问题"
```

生成完后，顺手问一句：
- “如果你愿意，我也可以继续帮你整理成图片或 PDF，方便就诊时直接出示给医生。”

也可以更自然一点，比如：
- “这版短文你先看看；如果要更方便出示给医生，我可以再帮你排成图片或 PDF。”
- “要不要我顺手再帮你整理成一张图，或者导出成 PDF？”

如用户明确需要，再继续导出图片版或 PDF 版。

这份摘要会尽量汇总：
- 本次主诉与自动提取的重点
- 近期关键指标、异常提醒、最近就诊变化
- 相关既往病史与近期检查
- 当前在用药、过敏史、可识别的中高风险药物相互作用

## 不可跳过的规则

1. **不要直接展示 JSON**：查询结果必须转成自然中文。
2. **不要用自身视觉能力读医疗图片**：图片/PDF 只能走外部视觉模型。
3. **药物安全问题必须先搜**：统一复用 `medical-search`，不要凭记忆回答。
4. **发简报默认发图片版**：优先 `briefing_report.py screenshot`，不是纯文本。
5. **多张图片先收齐再处理**：不要每到一张就立即确认录入。
6. **共享实例要做租户隔离**：有 `owner_id` 时始终带上。
7. **就医前摘要默认先短文版**：先用 `doctor_visit_report.py text` 生成；用户需要时，再导出图片或 PDF。

## 能力介绍模板

当用户问“你可以做什么”“你能帮我做什么”时，可以优先用自然中文这样回答：

```text
我可以帮你做这些和健康相关的事情：
- 记录和整理健康档案：症状、诊断、用药、检验、影像、血压血糖等
- 查询和总结病程：帮你把最近变化、既往史、在用药整理清楚
- 做提醒和健康简报：比如用药提醒、复查提醒、每日简报
- 识别报告图片或化验单：把图片/PDF里的信息提取出来录入
- 在你准备去看医生前，先生成一段“就医前摘要”：自动整理最近的关键情况、相关病史、过敏史、在用药和需要注意的事项；如果你需要，我再继续整理成图片或 PDF

如果你愿意，现在就可以直接告诉我：
“帮我整理最近的情况”
或
“帮我整理最近的就医摘要”
或
“帮我生成一张给医生看的摘要图”
```

如果用户已经明确说最近要去医院、复诊、看专科，优先提“就医前摘要图”，不要把它埋在能力列表最后。

## 参考导航

按需读取，不要一次全读：

- 录入、查询自然语言化、视觉处理：`mediwise-health-tracker/references/intake-query-vision.md:1`
- 药物安全、健康建议、图片版简报：`mediwise-health-tracker/references/drug-briefing.md:1`
- 周期追踪、附件管理、多租户隔离：`mediwise-health-tracker/references/cycle-attachments-multitenancy.md:1`
- 就医前摘要图：`mediwise-health-tracker/references/visit-prep.md:1`

## 反模式

- 不要在未确认成员身份时直接写入数据。
- 不要猜测诊断、剂量或图片内容。
- 不要在用户未确认前删除记录或覆盖原始附件。
- 不要说“无法发送图片”或“平台不支持图片”；本地图片可通过 `<qqimg>` 发送。
- 不要用英文回复中文用户。
