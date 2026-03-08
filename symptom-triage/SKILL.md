---
name: symptom-triage
description: >-
  症状问诊与初步分诊。当用户描述身体不适、疼痛、症状时使用此技能。通过多轮追问采集症状信息，
  搜索权威医学来源，给出可能的方向和建议就诊科室。也用于识别需要紧急就医的危险信号。
  Symptom assessment and triage. Use when user describes physical discomfort, pain, or symptoms.
  Conducts multi-round structured questioning, searches authoritative medical sources,
  provides possible directions and suggested departments. Also detects emergency red flags.
  关键词：不舒服、疼、痛、头晕、发烧、咳嗽、拉肚子、恶心、呕吐、胸闷、呼吸困难、我身体、我最近。
---

# Symptom Triage - 症状问诊与分诊

当用户描述身体不适时，先识别危险信号，再通过结构化追问和权威搜索给出方向性建议。

## 核心规则

1. **不做诊断**：只给“可能方向”，不下确定性结论。
2. **先问再答**：信息不足就继续追问。
3. **危险信号优先**：一旦命中红旗，立即中断问诊并建议急诊或当天就医。
4. **搜索验证必做**：最终建议前统一复用 `medical-search`。
5. **可结合健康档案**：如有 `mediwise-health-tracker`，先看病史、在用药和过敏史。

## 最小工作流

1. 先判断是否命中危险信号。
2. 未命中时按“部位 / 时间 / 性质 / 程度 / 诱因”追问 2-3 个关键问题。
3. 再问伴随症状、加重缓解因素、既往史、近期变化。
4. 信息足够后用 `medical-search` 搜索验证。
5. 输出“可能方向 + 建议科室 + 就诊前建议 + 参考来源”。

## 快速档案查询

```bash
python3 {baseDir}/../mediwise-health-tracker/scripts/query.py summary --member-id <id>
python3 {baseDir}/../mediwise-health-tracker/scripts/query.py active-medications --member-id <id>
```

## 参考导航

按需读取，不要一次全读：

- 危险信号与特殊人群处理：`symptom-triage/references/danger-signals.md:1`
- 问诊流程、输出模板、特殊场景：`symptom-triage/references/interview-and-response.md:1`

## 反模式

- 不要直接说“你这是 XX 病”。
- 不要推荐具体处方药。
- 不要忽略胸痛、呼吸困难、卒中样表现等红旗。
- 不要在未搜索验证前给方向性结论。
- 不要用专业术语轰炸用户。
