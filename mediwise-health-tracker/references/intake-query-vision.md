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
python3 {baseDir}/scripts/quick_entry.py parse --text "血压130/85 心率72" --member-id <id> --owner-id "<sender_id>"
python3 {baseDir}/scripts/quick_entry.py parse-and-save --text "血压130/85 心率72" --member-id <id> --owner-id "<sender_id>"
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
正确：最近一次血压是 140/90 mmHg，收缩压偏高；最近一周整体略高但相对稳定，建议继续监测。
```

## 图片 / PDF / 文本智能录入

### 强制规则

**不要在没有受控识别路径时直接解读医疗图片。** 图片和 PDF 必须走以下至少一种已经实际测试通过的路径：

- 能读取图片的多模态模型，并已写入 MediWise 视觉配置、通过 `setup.py test-vision`、`setup.py test-pdf` 和 `setup.py test-intake --input both`。
- 普通文本模型搭配 PaddleOCR；PaddleOCR 负责提取图片或扫描 PDF 的文字，并已通过 `setup.py test-paddleocr`、`setup.py test-pdf` 和 `setup.py test-intake --input both`。

当前对话模型声称“支持视觉”不等于 MediWise 的附件处理脚本已经可用。不要绕过配置和测试，也不要把识别失败的附件悄悄切换到未经用户授权的云端服务。

### 首次使用先检查配置

```bash
python3 {baseDir}/scripts/setup.py check
```

按检查结果选择路径：

1. `vision_configured: true`：运行 `test-vision`、`test-pdf` 和 `test-intake --input both`；只有脱敏测试图、扫描 PDF 与结构化结果都通过后才声称两类附件可解析。
2. `pdf_tools.paddleocr: true`：运行 `test-paddleocr`、`test-pdf` 和 `test-intake --input both`；三者通过后可以使用 OCR + 文本模型处理图片和扫描 PDF。
3. 两条路径都不可用：交给具备本机权限的配置 Agent。不要让普通用户运行命令，也不要在聊天中索要 API Key。

配置多模态模型时，可参考 SiliconFlow 的 `Qwen/Qwen3.6-35B-A3B`、`zai-org/GLM-4.5V`，或配置 Agent 当时能够验证的其他视觉模型。模型名称不能证明图片输入能力，必须查询当前服务信息并用实际图片测试。凭据只能通过客户端安全本地输入或系统 keyring 处理。

```bash
python3 {baseDir}/scripts/setup.py test-vision
python3 {baseDir}/scripts/setup.py test-vision --image /path/to/any_lab_report.jpg
python3 {baseDir}/scripts/setup.py test-paddleocr
python3 {baseDir}/scripts/setup.py test-pdf
python3 {baseDir}/scripts/setup.py test-intake --input both
```

### 已配置后处理附件

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
