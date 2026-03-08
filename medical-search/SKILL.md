---
name: medical-search
description: "Drug safety and medical information search. Use when user asks about: drug interactions, medication safety, contraindications, side effects, drug-alcohol interactions (吃药能喝酒吗), drug-food interactions, traditional Chinese medicine safety, medication conflicts, dosage concerns, general medical questions, disease information, symptom causes. 药物安全、药物交互、用药禁忌、药品不良反应、药物+酒精、药物+食物、中成药安全、疾病知识、医学问答。HIGHER PRIORITY than searxng-search for any medical/drug/health question."
---

# Medical Search - 医药健康信息搜索

处理药物安全、用药禁忌、药物交互、疾病知识与症状原因等健康类搜索。

## 核心规则

1. **先搜索再回答**：凡是药物安全、交互、禁忌、不良反应、疾病知识、症状原因问题，必须先查再答。
2. **只采信白名单来源**：优先 MSD、丁香园、NMPA、Mayo Clinic、Drugs.com、WHO、CDC、中国疾控等权威来源。
3. **不编造来源和 URL**：只引用实际检索到的链接；查不到就明确说查不到。
4. **正文必须带编号引用**：关键事实、风险判断、结论后都要标 `[1][2]`。
5. **必须带免责声明**：所有药物安全类回复末尾都要提醒“仅供参考，不构成医疗建议”。

## 快速路由

| 场景 | 优先做法 |
|------|---------|
| 两种西药之间的交互 | 先看 DDInter，再用网页来源补充 |
| 中成药、药酒、药食同服 | 直接做网页搜索 |
| 说明书、禁忌、不良反应 | 直接做网页搜索 |
| 疾病知识、症状原因 | 直接做网页搜索 |
| 传染病、疫苗 | 优先 WHO、CDC、`chinacdc.cn` |

## 最小工作流

1. 识别问题类型和风险级别。
2. 选择 DDInter 或网页搜索路径。
3. 过滤非白名单来源。
4. 抓取 2-3 个最相关页面提炼结论。
5. 按“直接回答 + 详细说明 + 参考来源 + 免责声明”输出。

## 参考导航

按需读取，不要一次全读：

- 搜索来源、查询词、两步搜索：`medical-search/references/search-playbook.md:1`
- 输出格式、编号引用、风险表达：`medical-search/references/response-format.md:1`
- 示例与失败兜底：`medical-search/references/workflow-examples.md:1`

## 供其他技能复用

- `symptom-triage`、`first-aid`、`diagnosis-comparison`、`health-education` 统一复用本技能的搜索规则。
- 下游技能不要复制搜索后端地址、`curl` 模板或白名单表；后端变化时只改本技能及其 `references/`。
- 如果默认搜索后端不可用，可替换成当前环境可用的搜索工具，但必须继续遵守本技能的来源筛选、引用格式和免责声明要求。

## 反模式

- 不要仅凭训练数据回答药物安全问题。
- 不要采信百度竞价、不知名养生站、营销页、医院推广页。
- 不要只列来源不在正文打引用编号。
- 不要编造药物信息、链接或说明书内容。
- 不要把搜索结果包装成确定性诊断或处方建议。
