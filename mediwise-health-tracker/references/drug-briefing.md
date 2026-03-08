# Drug Safety and Briefing

## 目录

- 药物安全查询规则
- DDInter / openFDA / 网页搜索
- 结果呈现
- 健康建议与简报
- 数据导出与在线计算器

## 药物安全查询规则

凡是涉及以下问题，必须先查再答，不能凭记忆：

- 药物交互
- 用药禁忌
- 不良反应
- 药物 + 酒精
- 药物 + 食物
- 中成药安全

统一复用 `medical-search` 的来源筛选、引用格式和免责声明。

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
- 来源优先级沿用 `medical-search`
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

## 健康建议与简报

```bash
python3 {baseDir}/scripts/health_advisor.py tips --member-id <id>
python3 {baseDir}/scripts/health_advisor.py briefing
```

### 强制：简报默认发图片版

当用户要“简报”“报告”“健康报告”时，默认用截图 PNG：

```bash
python3 {baseDir}/scripts/briefing_report.py screenshot --member-id <id>
```

拿到 `image_path` 后，用 `<qqimg>` 发送：

```text
这是你的健康简报：
<qqimg>/path/to/briefing.png</qqimg>
```

不要说“无法发送图片”或“QQ 不支持”。

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
