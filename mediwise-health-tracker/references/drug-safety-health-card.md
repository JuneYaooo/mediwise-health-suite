# Drug Safety and Health Record Card

## 目录

- 药物安全查询规则
- DDInter / openFDA / 网页搜索
- 结果呈现
- 状态提醒与健康记录卡片
- 数据导出

## 药物安全查询规则

凡是涉及以下问题，必须先查再答，不能凭记忆：

- 药物交互
- 用药禁忌
- 不良反应
- 药物 + 酒精
- 药物 + 食物
- 中成药安全

通过 DDInter、openFDA 或网页搜索查询，统一使用来源筛选、引用格式和免责声明。

## 查询方式

### DDInter

```bash
python3 {baseDir}/scripts/drug_interaction.py check --member-id <id> --drug-name "布洛芬"
python3 {baseDir}/scripts/drug_interaction.py check-pair --drug-a "阿司匹林" --drug-b "华法林"
python3 {baseDir}/scripts/drug_interaction.py lookup --name "奥美拉唑"
python3 {baseDir}/scripts/drug_interaction.py search --name "阿司匹林"
```

适合两种西药之间的交互检查。

### openFDA

```bash
python3 {baseDir}/scripts/openfda_query.py interaction --name "warfarin"
python3 {baseDir}/scripts/openfda_query.py check-pair --drug-a "warfarin" --drug-b "aspirin"
python3 {baseDir}/scripts/openfda_query.py search --name "metformin"
```

适合作为英文结构化补充验证来源。

### 网页搜索

- 中成药、安全说明、药酒同服、药食同服等优先走网页搜索
- 来源优先级：权威医学数据库 > 官方说明书 > 可靠医学网站
- 正文关键结论必须带 `[1][2]`

## 结果呈现

- 按权威来源原有等级展示严重、中等或轻微等风险标签，不自行升级或降低等级。
- 明确区分“来源中记录的风险”与 MediWise 的提醒，不能把查询结果表述成处方或临床判断。
- 不回答“可以吃/不可以吃”，不指示开始、停用、更换、合用或调整药物；相关决定由医生或药师判断。

每次药物安全类回复都要：

1. 展示查询到的风险标签和来源原文要点
2. 说明依据并标注编号引用
3. 列出真实来源链接
4. 明确说明本项目不提供用药建议，具体用药决定应咨询医生或药师

查不到时，直接说“未查到标准交互数据；MediWise 无法据此判断是否适合合用，请咨询医生或药师”。

## 状态提醒与健康记录卡片

```bash
python3 {baseDir}/scripts/health_advisor.py tips --member-id <id>
python3 {baseDir}/scripts/health_advisor.py briefing
```

### 强制：健康记录卡片默认发送 PNG

当用户要“健康记录卡片”，或使用“健康简报”“健康小报”等口语表达时，统一生成 PNG 健康记录卡片：

```bash
python3 {baseDir}/scripts/briefing_report.py screenshot --member-id <id>
```

拿到 `image_path` 后，使用当前 OpenClaw 客户端的图片消息能力发送：

```text
这是你的健康记录卡片：
[发送 image_path 指向的 PNG]
```

发送失败时说明当前客户端的具体限制，并保留本地图片路径；不要伪造已发送状态。

### 动态布局策略

默认使用 `focus=auto`，让生成器根据真实记录计算布局。不要在 Agent 回复中自行拼接 HTML，也不要用模型主观判断哪个数值异常。

布局按以下优先级决定：

1. 用户明确意图优先。用户问“血压趋势”“最近吃得怎么样”“最近检查结果”“现在吃什么药”时，分别传 `focus=metrics|lifestyle|care|medications`。
2. 未指定重点时，alert 高于 warning，明确标记异常和到期提醒高于单纯记录量。
3. 没有风险信号时，比较指标、生活方式、医疗记录和用药的实际覆盖量；只有明显领先时才选择单一重点，否则使用均衡布局。
4. 重点模块前置。指标重点时把被告警点名的指标优先并放大；生活方式重点时放大饮食、运动或睡眠中记录覆盖最多的面板；医疗重点时把个人时间轴前置；用药重点时把在用药表前置。
5. 自动概览省略完全为空且与本次问题无关的模块。用户明确指定的模块即使为空，也保留空状态，清楚说明没有记录。

个人版支持的 focus：

| focus | 使用场景 | 版式行为 |
|---|---|---|
| `auto` | 普通健康概览、定时卡片 | 风险优先，再看覆盖量；返回 `layout_profile` |
| `metrics` | 血压、血糖、心率、体重等趋势 | 指标区前置，异常或记录最丰富的指标放大 |
| `lifestyle` | 饮食、运动、步数、睡眠 | 生活方式区前置，覆盖最多的面板放大 |
| `care` | 就医、检验、检查 | 个人健康时间轴前置 |
| `medications` | 当前用药、服药提醒 | 在用药区前置 |

家庭版不接受手动 focus，也不展示家庭时间轴。它是按成员组织的状态看板，每张成员卡固定展示当前状态、有限的最新指标、在用药和服药计划、提醒与明确注意事项。生成器自动将有 alert 的成员排在最前，其次是 warning、明确标记异常和到期提醒；均无风险时，再按在用药、计划提醒和近期记录覆盖度排列。只有确有风险或到期待办的首位成员使用强化卡片样式。

使用返回的 `layout_profile` 做验证和自然语言概括，不要把它原样发给用户。个人版至少检查 `focus` 和 `section_order`；家庭版检查 `focus`、`member_order` 和 `featured_member`。

### 通用 HTML 截图

```bash
python3 {baseDir}/scripts/html_screenshot.py <input.html> [output.png] [--width 960]
```

## 数据导出

### 导出

```bash
python3 {baseDir}/scripts/export.py fhir --member-id <id>
python3 {baseDir}/scripts/export.py statistics
```

MediWise 不代替专业人员计算或解读 eGFR、CHA₂DS₂-VASc、CURB-65、MELD 等临床评分。
