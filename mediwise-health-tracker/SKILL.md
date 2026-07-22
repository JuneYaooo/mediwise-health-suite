---
name: mediwise-health-tracker
description: Family health and medical record management. Tracks members, visits, medications, lab results, daily metrics, reminders, health cards, and pre-visit summaries.
---

# MediWise Health Suite · 健康档案 Skill

健康档案与病程记录 Skill。所有操作通过 `{baseDir}/scripts/` 下的 Python 脚本完成，默认输出 JSON，再转成自然语言回复给用户。

当用户问”你可以做什么”时，记得主动提到：除了健康档案、指标记录、提醒、健康记录卡片外，还可以根据最近的描述和历史记录先整理一段”就医前摘要”，并在需要时继续生成图片或 PDF，方便给医生快速了解病情。

## 适用场景

- 添加或管理家庭成员信息
- 记录就诊经历（门诊/住院/急诊）、症状/诊断/用药/检验/影像检查结果
- 记录日常健康指标（血压/血糖/心率/体温等）
- 查询病程历史或用药记录、生成健康时间线或摘要、查看全家健康概况
- 发送体检报告图片或化验单需要识别录入
- 设置用药提醒、健康指标测量提醒、复查提醒，或获取主动健康建议、健康记录卡片、就医前摘要图
- 规划就诊流程（预约 → 就诊前汇总 → 记录诊断结果 → 复诊追踪）
- 随口提到健康问题（如”最近膝盖有点疼”）需要记录并定期跟进

## 核心工作流

### 0. 确认个人本地模式

当前公开版本只面向一个本地用户管理自己和多位家人的档案。安装 Agent 已负责配置个人模式；不要再让普通用户配置共享身份、群聊路由或 `owner_id`。

### 1. 按姓名与身份解析成员

写入或查询前调用 `resolve-member`：

- 没有任何成员：询问用户姓名，确认后调用 `add-member` 创建“姓名（本人）”。
- 只有一个且身份为“本人”：用户没说姓名时可以默认选择本人。
- 已有两位及以上成员：写入时必须有姓名；用户没说姓名就先询问，不能猜。
- 用户说了“爸爸”“妈妈”等关系：只有该关系唯一时才可解析，并在写入前复述最终的“姓名（身份）”。
- 同名或同身份出现多个匹配：同时询问姓名和身份进行消歧。

成员列表和确认回复始终显示“姓名（身份）”，例如“张建国（父亲）”“王丽（母亲）”。不得只展示内部 ID。

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
| `add-member` | 创建家庭成员档案 | name、relation；本人默认 relation=本人 |
| `resolve-member` | 按姓名/身份解析目标成员 | 可选 name、relation；多成员时用于消歧 |
| `add-visit` | 添加就诊记录 | member_id, visit_type, visit_date；可选 hospital/department/diagnosis |
| `add-symptom` | 添加症状记录 | member_id, symptom；可选 severity/visit_id/onset_date |
| `add-medication` | 添加用药记录 | member_id, name；可选 dosage/frequency/visit_id/purpose |
| `add-metric` | 添加健康指标 | member_id, type, value；可选 measured_at/source/context |

自然语言或图片输入走 `smart-extract` → `smart-confirm` 流程；短文本指标走 `quick-entry-save`。

### 快速录入指标

```bash
python3 {baseDir}/scripts/quick_entry.py parse --text "血压130/85 心率72" --member-id <id>
python3 {baseDir}/scripts/quick_entry.py parse-and-save --text "血压130/85 心率72" --member-id <id>
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

待跟进的健康备注会自动出现在下一张健康记录卡片（`health_advisor.py briefing`）中，确保不遗漏。

## 初始配置引导

当用户首次使用、或表示"图片识别不工作""无法识别报告"时，先在后台运行配置检查：

```bash
python3 {baseDir}/scripts/setup.py check
```

先检查 `pdf_tools.paddleocr`。PaddleOCR 是图片和扫描 PDF 的首选本地文字识别能力，不需要把原图上传到云端；由具备本机权限的配置 Agent 安装、设置并运行 `test-paddleocr`，不得要求普通用户运行命令。

若用户需要复杂版面、图表理解或自动结构化，再检查 `vision_configured`。**不要在聊天中索要 API Key**，也不要把安装或配置命令转交给普通用户。

### 配置流程

**第一步：询问地区/偏好**

> 本地 PaddleOCR 可以先处理图片和扫描 PDF 的文字。如果你还需要理解复杂表格或图表，我可以继续配置视觉模型。
>
> 你用的是国内网络还是海外网络？或者想完全在本地离线运行？

根据回答推荐方案，并给出对应的注册链接：
- 国内 → **硅基流动**；示例模型 `Qwen/Qwen3.6-35B-A3B` 或 `zai-org/GLM-4.5V`，配置前确认当前支持图片输入
- 海外 → **Google Gemini**（免费，在 https://aistudio.google.com/apikey 获取）
- 离线 → **本地 Ollama**（需提前安装 Ollama 并下载模型）

**第二步：由配置 Agent 完成设置**

使用客户端提供的安全本地凭据输入或系统 keyring。当前客户端没有安全输入能力时停止配置；不得要求用户在聊天中粘贴 Key，也不得让普通用户复制配置命令。

**第三步：配置 Agent 验证能力**

```bash
python3 {baseDir}/scripts/setup.py test-vision
```

- 测试通过 → "配置好了！现在可以直接把报告图片或 PDF 发给我来识别。"
- 测试失败 → 根据错误信息提示用户检查 API Key 是否正确，或网络是否可用。

### 原则

- **不在聊天中收集凭据**：API Key 属于敏感信息，只能通过客户端安全本地输入或系统 keyring，不得经过对话传递。
- **后台静默执行**：`setup.py test-vision` 等验证命令在后台完成，不要把 JSON 输出贴给用户。
- **配置失败友好提示**：失败时给出具体原因和可操作的修复建议，不要直接贴报错。

## 不可跳过的规则

1. **不要直接展示 JSON**：查询结果必须转成自然中文。
2. **医疗图片走受控识别链路**：优先本地 PaddleOCR；复杂版面再使用用户明确启用的视觉模型。PaddleOCR 返回的文字仍需展示给用户确认后才能写库。
   - 云端视觉模型会收到完整图片/PDF 页面，内容可能包含姓名、身份证号、病历号等 PII；调用前应确认用户已选择并信任该提供商。敏感材料优先使用本地能力。
3. **药物安全问题必须先搜**：通过 DDInter、openFDA 或网页搜索查询，不要凭记忆回答。
4. **近期健康记录默认发图片卡片**：优先调用 `generate-report`，传入用户要求的 `days`（默认 7）、语言和个人/家庭视图，不是把 JSON 或 HTML 发给用户。
5. **多张图片先收齐再处理**：不要每到一张就立即确认录入。
6. **只用于个人本地档案**：不要引导群聊或多人共享部署；安装配置异常时交给具备本机权限的 Agent 修复，不让普通用户处理身份参数。
7. **就医前摘要默认先短文版**：先用 `doctor_visit_report.py text` 生成；用户需要时，再导出图片或 PDF。
8. **成员按姓名和身份解析**：只有唯一“本人”档案时允许默认本人；出现多位家庭成员后，写入必须明确姓名。每次写入前复述“姓名（身份）”，同名时必须进一步消歧。
9. **记录饮食前必须先查食物数据库**：通过 diet-tracker 的 `food_lookup.py search` 查每种食物的营养数据，用查询结果填写 `--items`。禁止凭 AI 自身知识估算营养值后直接写入。
10. **对话中的健康提及必须实时记录（强制）**：用户在对话中随口提到任何健康相关内容（症状、不适、用药感受、睡眠、情绪等），**必须在当次对话结束前**调用 `health_memory.py log` 将其写入健康备注。这是夜间做梦机制的原始素材来源——`dream.py gather` 会专门读取当日记录的对话提及，未被记录的提及将永久丢失。

    **触发关键词示例**（不限于此）：
    - "最近/今天/昨天有点…"、"感觉…"、"一直…"、"偶尔…"
    - 身体部位 + 描述：头、胃、腿、眼睛、心脏 + 疼/胀/酸/晕/难受
    - 睡眠问题：睡不着、早醒、多梦、睡眠质量差
    - 情绪/精力：累、乏力、焦虑、情绪低落、提不起劲
    - 用药感受：吃了药之后…、副作用、效果不明显

## 健康记录卡片定时推送规范（OpenClaw 定时任务）

**触发时机：每日早晨 8:00，由 OpenClaw agent 自动执行。**

### 执行流程

```
1. wearable-sync: sync-all          → 同步手表数据（若有绑定设备）
2. health-monitor: check-all        → 检测异常指标，写入 alerts 表
3. health_advisor.py briefing       → 获取卡片数据（提醒 + 建议 + 风险等级）
4. briefing_report.py screenshot    → 生成健康记录卡片（PNG），同时自动保存当日快照
5. 推送给用户（见下方推送规则）
```

### 夜间做梦任务（OpenClaw 定时任务）

**触发时机：每晚 22:00，由 OpenClaw agent 自动执行，调用 DREAM skill。**

做梦机制负责在夜间回顾当日健康素材，提炼规律和隐患，将有价值的洞察写入健康备注，供次日健康记录卡片展示。详见 `mediwise-health-tracker/DREAM.md`。

```
dream.py status   → 检查是否满足触发条件（≥20h 间隔）
dream.py lock     → 获取做梦锁（防止并发）
dream.py gather   → 收集当日健康素材
↓ agent 深度分析（逐成员回顾指标/告警/备注趋势）
health_memory.py log  → 写入值得记录的发现（有发现才写，最多3条/成员）
dream.py unlock   → 释放锁，标记完成
```

### 推送内容规则

| 情况 | 推送什么 |
|---|---|
| 有 alert 级告警 | 健康记录卡片 + 文字摘要，文字中明确点出告警项 |
| 只有 warning 或 info | 健康记录卡片，文字一句话概括（"今日整体正常，有 N 项提醒"）|
| 完全正常 | 只发一句"今日健康状况良好，无待处理事项" + 可选健康记录卡片 |
| 同步失败（无手表数据） | 注明"今日手表数据未能同步，以下数据基于上次同步结果" |

### 推送格式

- **默认发卡片图片**：`briefing_report.py screenshot` 生成 PNG，作为图片消息发送
- **文字摘要**：在图片前附一段不超过 100 字的中文摘要，点出最重要的 1-2 件事
- **禁止**：直接把 JSON 或 HTML 内容粘贴到聊天里

### 用户手动请求时

当用户说“帮我生成最近 7 天的健康记录卡片”“给我看近期健康简报”“今天身体怎么样”等口语表达时，统一按“健康记录卡片”能力处理：

1. 个人版先按姓名与身份规则调用 `resolve-member`。只有唯一“本人”档案时可以默认本人；有多位成员且用户未说明姓名时必须先询问。明确请求家庭版时跳过单成员解析。
2. 个人版调用 `generate-report`，传入已确认的 `member_id`、`days`、`view=personal` 和对话语言对应的 `locale`；未指定时间时默认 7 天。
3. 将生成的 PNG 作为图片消息发送，并用一句自然语言概括最重要的提醒。
4. 用户明确说“家庭健康记录卡片”“全家健康卡片”时，调用 `generate-report` 并传入 `view=family`，不要传 `member_id`。家庭版用于一个本地用户管理本人及家人的概览，不代表多人共享服务。
5. 英文请求使用 `locale=en-US`，中文请求使用 `locale=zh-CN`。对外名称分别统一为 “Health Record Card” 和“健康记录卡片”。

个人版按真实记录展示指标趋势、饮食摄入、运动消耗、步数、睡眠、近期就医、检验、检查和在用药。家庭版展示成员关注状态、有限的关键指标、数据覆盖摘要和家庭医疗时间线，不把多张完整个人卡片纵向拼接。饮食日均只按有记录日计算；运动消耗不等于完整能量支出；没有独立饮水或临床液体出入量记录时不得生成相关数字；检验异常仅认原始数据中的明确标记。

## 每日健康快照记忆（daily_snapshot.py）

每次生成健康记录卡片时自动保存当日快照，agent 可在对话中直接引用历史状态，无需每次重新计算。

### 支持的查询场景

| 用户说 | agent 调用 | 说明 |
|---|---|---|
| "昨天状态怎么样" | `daily_snapshot.py get --date <昨天>` | 返回单日摘要 |
| "这周身体趋势" | `daily_snapshot.py history --days 7` | 最近7天列表 |
| "这个月有几天出现告警" | `daily_snapshot.py trend --days 30` | 逐日风险等级 |
| "上周五血压有没有异常" | `daily_snapshot.py get --date <日期>` + 若需要细节查 `health_metrics` | 快照 + 原始指标 |

### 使用规则

- **优先查快照**：用户问历史健康状态时，先查 `daily_snapshot.py`，有结果就直接用，不需要重新跑 `health_advisor.py`
- **快照没有再查原始指标**：快照只存摘要和风险等级；如用户追问具体数值，再查 `health_metrics`
- **描述要自然**：把 risk_level（ok / warning / alert）和 summary_text 组合成一句话，不要直接展示 JSON

```bash
# 查昨天快照
python3 {baseDir}/scripts/daily_snapshot.py get --member-id <id> --date 2026-04-05

# 查最近7天
python3 {baseDir}/scripts/daily_snapshot.py history --member-id <id> --days 7

# 查30天趋势（用于描述"这个月整体状况"）
python3 {baseDir}/scripts/daily_snapshot.py trend --member-id <id> --days 30
```

## 能力介绍模板

当用户问“你可以做什么”“你能帮我做什么”时，可以优先用自然中文这样回答：

```text
我可以帮你做这些和健康相关的事情：
- 记录和整理健康档案：症状、诊断、用药、检验、影像、血压血糖等
- 查询和总结病程：帮你把最近变化、既往史、在用药整理清楚
- 做提醒和健康记录卡片：比如用药提醒、复查提醒、最近 7 天健康记录卡片
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

备份文件包含：`medical.db`、`lifestyle.db`、`config.json`（以及旧版 `health.db`，如存在）和 SHA-256 `manifest.json`。备份使用 SQLite 一致性快照，支持配置在自定义路径中的数据库；恢复会先校验白名单、哈希和数据库完整性。旧版无 manifest 的官方备份仍兼容恢复，但无法进行哈希校验。manifest 未签名，不提供来源真实性保证。

**迁移流程**：
1. 旧环境：`setup.py backup --output xxx.tar.gz`，将文件发给用户
2. 用户把文件传到新设备
3. 新环境：`setup.py restore --input xxx.tar.gz`，数据恢复并自动完成 Schema 迁移

## 参考导航

按需读取，不要一次全读：

- 录入、查询自然语言化、视觉处理：`mediwise-health-tracker/references/intake-query-vision.md:1`
- 药物安全、健康建议、健康记录卡片：`mediwise-health-tracker/references/drug-safety-health-card.md:1`
- 周期追踪、附件与个人本地边界：`mediwise-health-tracker/references/cycle-attachments-local-scope.md:1`
- 就医前摘要图：`mediwise-health-tracker/references/visit-prep.md:1`

## 反模式

- 不要在未确认成员身份时直接写入数据。
- 不要猜测诊断、剂量或图片内容。
- 不要在用户未确认前删除记录或覆盖原始附件。
- 不要说“无法发送图片”或“平台不支持图片”；本地图片可通过 `<qqimg>` 发送。
- 不要用英文回复中文用户。
