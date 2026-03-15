---
name: mediwise-health-tracker
description: Family health and medical record management. Tracks members, visits, medications, lab results, daily metrics, reminders, briefings, and pre-visit summaries.
---

# MediWise Health Tracker

家庭健康与病程记录管理技能。所有操作通过 `{baseDir}/scripts/` 下的 Python 脚本完成，默认输出 JSON，再转成自然语言回复给用户。

当用户问”你可以做什么”时，记得主动提到：除了健康档案、指标记录、提醒、简报外，还可以根据最近的描述和历史记录先整理一段”就医前摘要”，并在需要时继续生成图片或 PDF，方便给医生快速了解病情。

## 适用场景

- 添加或管理家庭成员信息
- 记录就诊经历（门诊/住院/急诊）、症状/诊断/用药/检验/影像检查结果
- 记录日常健康指标（血压/血糖/心率/体温等）
- 查询病程历史或用药记录、生成健康时间线或摘要、查看全家健康概况
- 发送体检报告图片或化验单需要识别录入
- 设置用药提醒、健康指标测量提醒、复查提醒，或获取主动健康建议、每日健康简报、就医前摘要图
- 规划就诊流程（预约 → 就诊前汇总 → 记录诊断结果 → 复诊追踪）
- 随口提到健康问题（如”最近膝盖有点疼”）需要记录并定期跟进

## 核心工作流

### 0. 确定 owner_id（每次必做）

从会话上下文获取当前发送者 ID，格式为 `<channel>:<user_id>`，用于所有脚本的 `--owner-id` 参数。例如：
- 飞书用户：`feishu:ou_707461a1baa7790213d30230b88fb575`
- QQ 用户：`qqbot:12345678`

后续所有脚本调用均以此 ID 作为 `--owner-id`，不得省略。

### 1. 先确认成员（必须等用户回复）

```bash
python3 {baseDir}/scripts/member.py list --owner-id "<sender_id>"
```

每次增删改查前先调用 `list` 查询现有成员，**将结果展示给用户，明确询问"是为哪位成员操作？"，等待用户明确回复后再继续。**

**禁止以下行为：**
- 未经询问自动创建新成员（包括"本人"）
- 在用户未确认目标成员的情况下继续写入数据
- 假设"只有一个成员所以自动选择"

**成员不存在时的处理：**
```
列表为空或未找到目标成员 → 告知用户 → 询问是否新建成员 → 等待用户确认姓名和关系 → 再调用 member.py add
```

```bash
# 用户确认后才执行创建
python3 {baseDir}/scripts/member.py add --name "张三" --relation "本人" --owner-id "<sender_id>"
```

### 2. 选择录入路径

- 简短指标文本：优先 `quick_entry.py`
- 复杂文本、就诊、用药、检验：用 `smart_intake.py` 或对应业务脚本
- 图片 / PDF / 多附件：走视觉录入流程
- 录入后发现异常指标、新诊断或用药变化：用 `log-health-note` 动作记录并跟进

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

结构化数据可直接调用对应动作写入：

| 动作 | 说明 | 关键参数 |
|------|------|----------|
| `add-visit` | 添加就诊记录 | member_id, visit_type, visit_date；可选 hospital/department/diagnosis |
| `add-symptom` | 添加症状记录 | member_id, symptom；可选 severity/visit_id/onset_date |
| `add-medication` | 添加用药记录 | member_id, name；可选 dosage/frequency/visit_id/purpose |
| `add-metric` | 添加健康指标 | member_id, type, value；可选 measured_at/source/context |

自然语言或图片输入走 `smart-extract` → `smart-confirm` 流程；短文本指标走 `quick-entry-save`。

### 快速录入指标

```bash
python3 {baseDir}/scripts/quick_entry.py parse --text "血压130/85 心率72" --member-id <id> --owner-id "<sender_id>"
python3 {baseDir}/scripts/quick_entry.py parse-and-save --text "血压130/85 心率72" --member-id <id> --owner-id "<sender_id>"
```

### 录入后发现异常，记录并跟进

录入数据后若发现异常指标、新诊断或用药变化，用 `log-health-note` 动作记录并自动创建跟进提醒：

```bash
# action: log-health-note
python3 {baseDir}/scripts/health_memory.py log --member-id <id> --content "血压160/100，高于正常上限" --category observation --follow-up-days 3
```

### 生成就医前摘要

当用户最近准备去看医生，可以先让用户用自然语言描述本次不适，默认先生成一段简短摘要：

```bash
python3 {baseDir}/scripts/doctor_visit_report.py text --member-id <id> --description “最近两周反复头晕，起床和翻身时更明显，偶尔恶心，担心是不是血压或者耳石问题”
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

### 就诊全程管理（plan → prep → outcome → follow-up）

对于有明确就诊计划的场景，可以走完整就诊生命周期：

```bash
# 1. 创建就诊预约（status=planned），获取准备提醒
python3 {baseDir}/scripts/visit_lifecycle.py plan --member-id <id> --visit-date 2026-03-15 --hospital 协和医院 --department 心内科 --chief-complaint “反复胸闷”

# 2. 就诊前智能汇总：症状按身体系统分组 + 近期异常指标 + 在用药 + 药物相互作用警告
python3 {baseDir}/scripts/visit_lifecycle.py prep --member-id <id> [--days 30]

# 3. 就诊后引导录入：诊断、处方、复诊安排（自动创建复诊提醒）
python3 {baseDir}/scripts/visit_lifecycle.py outcome --visit-id <vid> --diagnosis “高血压” \
  --follow-up-date 2026-06-15 \
  --medications '[{“name”:”氨氯地平”,”dosage”:”5mg”,”frequency”:”每日一次”}]'

# 4. 查看待处理就诊（planned / 未填结果 / 复诊提醒）
python3 {baseDir}/scripts/visit_lifecycle.py pending --member-id <id>
```

### 健康记忆追踪

当用户随口提到健康问题时，及时记录并自动跟进：

```bash
# 记录随口提到的健康问题，自动创建 N 天后的跟进提醒
python3 {baseDir}/scripts/health_memory.py log --member-id <id> --content “最近睡眠很差，经常半夜醒” --category symptom --follow-up-days 5

# 查看未解决的健康备注和到期跟进
python3 {baseDir}/scripts/health_memory.py list --member-id <id>

# 标记已解决
python3 {baseDir}/scripts/health_memory.py resolve --note-id <nid> --resolution-note “医生建议减少咖啡因摄入，已执行”
```

待跟进的健康备注会自动出现在每日简报（`health_advisor.py briefing`）中，确保不遗漏。

## 初始配置引导

当用户首次使用、或表示"图片识别不工作""无法识别报告"时，先在后台运行配置检查：

```bash
python3 {baseDir}/scripts/setup.py check
```

若输出中 `vision_configured` 为 `false`，**不要把命令行细节暴露给用户**，而是用自然语言引导他们完成对话式配置：

### 对话式配置流程

**第一步：询问地区/偏好**

> 检测到图片和 PDF 识别功能还没配置，需要接入一个视觉模型才能用。
>
> 你用的是国内网络还是海外网络？或者想完全在本地离线运行？

根据回答推荐方案：
- 国内 → **硅基流动**（免费注册有额度，在 https://cloud.siliconflow.cn 获取 API Key）
- 海外 → **Google Gemini**（免费，在 https://aistudio.google.com/apikey 获取）
- 离线 → **本地 Ollama**（需提前安装 Ollama 并下载模型）

**第二步：收集 API Key**

> 好的，推荐你用 [方案名]。去 [链接] 注册后复制 API Key，直接发给我就行。

用户回复 API Key 后，**在后台静默执行**（不要把命令贴给用户看）：

```bash
python3 {baseDir}/scripts/setup.py set-vision --provider <preset> --api-key <用户提供的key>
```

`--model` 和 `--base-url` 对内置预设（siliconflow / gemini / openai / stepfun / ollama）均可省略，自动填入。

**第三步：验证并告知结果**

```bash
python3 {baseDir}/scripts/setup.py test-vision
```

- 测试通过 → "配置好了！现在可以直接把报告图片或 PDF 发给我来识别。"
- 测试失败 → 根据错误信息提示用户检查 API Key 是否正确，或网络是否可用。

### 原则

- **用户侧零命令**：整个过程用户只需回答问题、粘贴 API Key，不需要接触任何命令行。
- **后台静默执行**：所有 `setup.py` 调用在后台完成，不要把命令或 JSON 输出贴给用户。
- **配置失败友好提示**：失败时给出具体原因和可操作的修复建议，不要直接贴报错。

## 不可跳过的规则

1. **不要直接展示 JSON**：查询结果必须转成自然中文。
2. **不要用自身视觉能力读医疗图片**：图片/PDF 只能走外部视觉模型。
3. **药物安全问题必须先搜**：通过 DDInter、openFDA 或网页搜索查询，不要凭记忆回答。
4. **发简报默认发图片版**：优先 `briefing_report.py screenshot`，不是纯文本。
5. **多张图片先收齐再处理**：不要每到一张就立即确认录入。
6. **每次调用脚本必须携带 `--owner-id`（强制）**：从当前会话上下文获取发送者 ID，格式为 `<channel>:<user_id>`（如 `feishu:ou_707461a1baa7790213d30230b88fb575` 或 `qqbot:12345`），作为所有脚本的 `--owner-id` 参数。这是多用户数据隔离的核心机制，任何脚本调用都不得省略。不知道 owner_id 时，先停下来确认，不要在没有 owner_id 的情况下写入数据。
7. **就医前摘要默认先短文版**：先用 `doctor_visit_report.py text` 生成；用户需要时，再导出图片或 PDF。
8. **成员确认必须等用户明确回复**：先调用 `member.py list` 展示已有成员，问清楚"是为哪位成员操作"，等待用户回复后再继续。不得自动创建成员（包括"本人"），不得在成员未确认的情况下写入任何数据。
9. **记录饮食前必须先查食物数据库**：通过 diet-tracker 的 `food_lookup.py search` 查每种食物的营养数据，用查询结果填写 `--items`。禁止凭 AI 自身知识估算营养值后直接写入。

## 能力介绍模板

当用户问“你可以做什么”“你能帮我做什么”时，可以优先用自然中文这样回答：

```text
我可以帮你做这些和健康相关的事情：
- 记录和整理健康档案：症状、诊断、用药、检验、影像、血压血糖等
- 查询和总结病程：帮你把最近变化、既往史、在用药整理清楚
- 做提醒和健康简报：比如用药提醒、复查提醒、每日简报
- 识别报告图片或化验单：把图片/PDF里的信息提取出来录入
- 在你准备去看医生前，先生成一段”就医前摘要”：自动整理最近的关键情况、相关病史、过敏史、在用药和需要注意的事项；如果你需要，我再继续整理成图片或 PDF
- 就诊全程管理：提前规划预约 → 就诊前智能汇总症状/指标/用药 → 就诊后记录诊断和处方 → 自动追踪复诊提醒
- 健康记忆：随时告诉我你注意到的健康问题（如”最近膝盖有点疼”），我会记下来并在几天后主动提醒你跟进

如果你愿意，现在就可以直接告诉我：
“帮我整理最近的情况”
或
“帮我整理最近的就医摘要”
或
“帮我生成一张给医生看的摘要图”
```

如果用户已经明确说最近要去医院、复诊、看专科，优先提“就医前摘要图”，不要把它埋在能力列表最后。

## 数据备份与迁移

当用户需要换设备、换环境，或者迁移到新的小龙虾实例时，使用以下命令打包和恢复数据：

```bash
# 备份：将所有数据库和配置打包到一个文件
python3 {baseDir}/scripts/setup.py backup --output mediwise-backup.tar.gz

# 恢复：在新环境中还原数据（Schema 自动升级到最新版本）
python3 {baseDir}/scripts/setup.py restore --input mediwise-backup.tar.gz
```

备份文件包含：`medical.db`、`lifestyle.db`、`config.json`（以及旧版 `health.db`，如存在）。

**迁移流程**：
1. 旧环境：`setup.py backup --output xxx.tar.gz`，将文件发给用户
2. 用户把文件传到新设备
3. 新环境：`setup.py restore --input xxx.tar.gz`，数据恢复并自动完成 Schema 迁移

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
