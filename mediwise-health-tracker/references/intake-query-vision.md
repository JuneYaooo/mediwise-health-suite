# Intake, Query, and Vision

## 目录

- 录入路径选择
- 查询结果自然语言化
- 图片 / PDF / 文本智能录入
- 多附件处理流程

## 录入路径选择

### 简单指标

以下场景优先 `quick_entry.py`，因为它不依赖 LLM，速度更快：

- 血压
- 血糖
- 心率
- 体温
- 体重
- 血氧

```bash
python3 {baseDir}/scripts/quick_entry.py parse --text "血压130/85 心率72" --member-id <id>
python3 {baseDir}/scripts/quick_entry.py parse-and-save --text "血压130/85 心率72" --member-id <id>
```

如果返回 `fallback: true`，再切换到 `smart_intake.py`。

### 复杂文本或结构化记录

```bash
python3 {baseDir}/scripts/smart_intake.py extract --text "今天血压135/88，心率72" --member-id <id>
python3 {baseDir}/scripts/medical_record.py add-visit --member-id <id> --visit-type "门诊" --visit-date "2025-01-15" --hospital "人民医院" --diagnosis "高血压"
python3 {baseDir}/scripts/medical_record.py add-medication --member-id <id> --name "氨氯地平" --dosage "5mg" --frequency "每日一次"
```

### 录入后自动观察

以下情况建议补记到 `memory.py add-observation`：

- 指标异常
- 新增诊断
- 新增或变更用药
- 停药

## 查询结果自然语言化

### 必须做的改写

- 体征查询：描述趋势，不要只堆数字
- 用药查询：按清单展示药名、剂量、频率、开始时间
- 文字健康摘要：突出重点，不要把全部字段都念一遍；不要与图片形式的“健康记录卡片”混称
- 时间线：按时间讲述发生了什么

### 示例

```text
错误：{"type":"blood_pressure","value":"{\"systolic\":140,\"diastolic\":90}"}
正确：最近一次血压是 140/90 mmHg，触发了已配置的收缩压范围提醒；最近一周的已记录数值相对稳定。本项目只展示记录和提醒，不作医学判断。
```

## 图片 / PDF / 文本智能录入

### 强制规则

按以下顺序处理图片和 PDF：

1. **当前 Agent 直接读取**：如果本次对话已收到附件且当前 Agent 能读取，直接提取内容，无需 MediWise 视觉配置，也无需运行 `test-vision`。先展示提取结果，用户确认后再写入档案。
2. **本地 OCR fallback**：当前 Agent 不可读或实际识别失败时，才在后台运行 `python3 {baseDir}/scripts/setup.py check`。若 `pdf_tools.paddleocr: true`，可使用 PaddleOCR；配置 Agent 应通过 `test-paddleocr`、`test-pdf` 和 `test-intake --input both` 验证该 fallback。
3. **用户已配置的视觉 fallback**：若 `vision_configured: true`，可使用用户已经选择的服务；配置 Agent应通过 `test-vision`、`test-pdf` 和 `test-intake --input both` 验证该 fallback。
4. **均不可用**：明确提醒用户交给具备本机权限的配置 Agent。不要让普通用户运行命令，也不要在聊天中索要 API Key。

不得把识别失败的附件悄悄切换到未经用户授权的新云端服务。无论使用哪条路径，提取内容都只能作为待确认记录；不能根据报告给出诊断、治疗、用药或其他医疗指导。

配置多模态模型时，可参考 SiliconFlow 的 `Qwen/Qwen3.6-35B-A3B`、`zai-org/GLM-4.5V`，或配置 Agent 当时能够验证的其他视觉模型。模型名称不能证明图片输入能力，必须查询当前服务信息并用实际图片测试。凭据只能通过客户端安全本地输入或系统 keyring 处理。

```bash
python3 {baseDir}/scripts/setup.py test-vision
python3 {baseDir}/scripts/setup.py test-vision --image /path/to/any_lab_report.jpg
python3 {baseDir}/scripts/setup.py test-paddleocr
python3 {baseDir}/scripts/setup.py test-pdf
python3 {baseDir}/scripts/setup.py test-intake --input both
```

### fallback 脚本处理附件

```bash
python3 {baseDir}/scripts/smart_intake.py extract --image /path/to/image.jpg --member-id <id>
python3 {baseDir}/scripts/smart_intake.py extract --pdf /path/to/report.pdf --member-id <id>
python3 {baseDir}/scripts/smart_intake.py extract --text "今天血压135/88，心率72" --member-id <id>
```

## 多附件处理流程

用户连续发送多张图片时：

1. 先累积，回复“收到，还有更多要发的吗？发完告诉我。”
2. 用户确认发完后，再逐个调用 `smart_intake.py extract`
3. 汇总所有提取结果，按类型分组给用户核对
4. 用户确认后再正式录入

不要每收到一张图就立即处理、立即确认。
