---
name: diagnosis-comparison
description: >-
  多源问诊对比与第二意见。当用户想要对比不同平台的诊断意见、获取第二意见、综合分析症状时使用。
  先完成 symptom-triage 的完整问诊流程，再搜索多个权威医学平台获取对比意见，输出对比表格和分析。
  Multi-source diagnosis comparison and second opinion. Use when user wants to compare
  opinions from different platforms, get a second opinion, or comprehensive analysis.
  关键词：对比、第二意见、其他平台怎么说、综合分析、多方意见、别的医生怎么看。
---

# Diagnosis Comparison - 多源问诊对比

当用户希望获取“多个平台怎么说”的对比时，先完成 `symptom-triage`，再做多源交叉验证并输出差异分析。

## 核心规则

1. **先问诊后对比**：没有结构化症状信息时，不要直接搜外部平台。
2. **至少三源交叉验证**：其中至少 2 个为权威医学平台。
3. **差异必须透明展示**：不要只挑支持某个方向的来源。
4. **编号引用不可省略**：表格、分析、结论都要标 `[1][2]`。
5. **不做诊断**：对比只提供方向性参考，不能替代医生诊断。

## 最小工作流

1. 先按 `symptom-triage` 完成初步问诊与自有分析。
2. 用“症状 + 关键特征 + 可疑方向”构造检索词。
3. 统一复用 `medical-search` 搜索至少 3 个平台。
4. 提取每个平台的可能方向、建议科室、紧急程度。
5. 输出对比表、一致意见、分歧点和参考来源。

## 参考导航

按需读取，不要一次全读：

- 来源选择、搜索和对比流程：`diagnosis-comparison/references/comparison-workflow.md:1`
- 输出模板、编号引用、进度反馈：`diagnosis-comparison/references/response-format.md:1`

## 反模式

- 不要跳过问诊直接搜平台。
- 不要隐藏来源之间的分歧。
- 不要编造来源链接。
- 不要把多平台一致说成“已经确诊”。
- 不要省略编号引用。
