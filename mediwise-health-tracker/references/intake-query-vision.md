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
- 健康摘要：突出重点，不要把全部字段都念一遍
- 时间线：按时间讲述发生了什么

### 示例

```text
错误：{"type":"blood_pressure","value":"{\"systolic\":140,\"diastolic\":90}"}
正确：最近一次血压是 140/90 mmHg，收缩压偏高；最近一周整体略高但相对稳定，建议继续监测。
```

## 图片 / PDF / 文本智能录入

### 强制规则

**不要使用自身视觉能力读取医疗图片。** 所有图片 / PDF 识别必须通过外部视觉模型。

### 首次使用先检查配置

```bash
python3 {baseDir}/scripts/setup.py check
```

如果 `vision_configured: false`：

1. 告知用户需要先配置视觉模型
2. 推荐 SiliconFlow 的 `Qwen/Qwen3-VL-32B-Instruct`
3. 用户给出 API Key 后执行配置
4. 再运行测试验证

```bash
python3 {baseDir}/scripts/setup.py set-vision --provider siliconflow --model "Qwen/Qwen3-VL-32B-Instruct" --api-key <KEY> --base-url "https://api.siliconflow.cn/v1"
python3 {baseDir}/scripts/setup.py test-vision
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
