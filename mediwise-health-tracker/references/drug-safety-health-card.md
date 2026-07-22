# Drug Safety and Health Record Card

## 目录

- 药物安全查询规则
- DDInter / openFDA / 网页搜索
- 结果呈现
- 健康建议与健康记录卡片
- 数据导出与在线计算器

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

- **严重**：明确警告，不建议自行合用
- **中等**：提示注意，建议咨询药师或医生
- **轻微**：说明风险较低，但仍需遵医嘱

每次药物安全类回复都要：

1. 给出直接结论
2. 说明依据并标注编号引用
3. 列出真实来源链接
4. 追加免责声明

查不到时，直接说“未查到标准交互数据，建议咨询药师确认”。

## 健康建议与健康记录卡片

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

家庭版不接受手动 focus。生成器自动将有 alert 的成员排在最前，其次是 warning、明确标记异常和到期提醒；无风险时按近期记录覆盖度排列。只有确有风险或待办的首位成员使用强化卡片样式。

使用返回的 `layout_profile` 做验证和自然语言概括，不要把它原样发给用户。至少检查：`focus`、`section_order`，以及家庭版的 `member_order` 和 `featured_member`。

### 通用 HTML 截图

```bash
python3 {baseDir}/scripts/html_screenshot.py <input.html> [output.png] [--width 960]
```

## 数据导出与在线计算器

### 导出

```bash
python3 {baseDir}/scripts/export.py fhir --member-id <id>
python3 {baseDir}/scripts/export.py statistics
```

### 在线计算器

需要 BMI、eGFR、CHA₂DS₂-VASc、CURB-65、MELD 等计算时，优先给权威在线工具链接，而不是在本地手算：

- 医脉通：`https://cals.medlive.cn/`
- MSD 临床计算器：`https://www.msdmanuals.cn/professional/pages-with-widgets/clinical-calculators`
- MDCalc：`https://www.mdcalc.com/`
