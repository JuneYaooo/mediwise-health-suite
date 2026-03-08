---
name: health-education
description: >-
  健康科普与教育内容发现。当用户想了解疾病知识、寻找科普视频、查看小红书/公众号上的健康内容、
  学习健康知识时使用此技能。通过搜索权威科普平台和社交媒体精选内容，提供分层的健康教育资源。
  Health education and popular science content discovery. Use when user wants to learn
  about diseases, find educational videos, browse health content on social media,
  or understand health topics. Searches authoritative platforms and curated social media content.
  关键词：科普、学习、了解、视频、小红书、公众号、怎么回事、健康知识、什么是、为什么会。
---

# Health Education - 健康科普与内容发现

当用户想学某个健康主题、找靠谱科普、找视频讲解时，按“权威优先、社媒兜底”的分层策略推荐内容。

## 核心规则

1. **专业平台优先**：先找医学微视、丁香医生、腾讯医典、有来医生等。
2. **社交媒体只做补充**：仅在前两层不足或用户明确要求时使用。
3. **严格过滤营销和偏方**：社媒命中不代表可信。
4. **按类型分组展示**：视频、图文、社交精选分开列。
5. **如有健康档案就个性化推荐**：结合诊断、用药、过敏史挑内容。

## 最小工作流

1. 明确用户想学的主题。
2. 如有档案，先看相关诊断和在用药。
3. 先用 `medical-search` 搜专业科普来源。
4. 再补视频平台；必要时才补社媒。
5. 过滤低质量结果并按类型输出。

## 档案查询

```bash
python3 {baseDir}/../mediwise-health-tracker/scripts/query.py summary --member-id <id>
python3 {baseDir}/../mediwise-health-tracker/scripts/query.py active-medications --member-id <id>
```

## 参考导航

按需读取，不要一次全读：

- 分层搜索策略与社媒过滤：`health-education/references/content-layers.md:1`
- 个性化推荐与输出格式：`health-education/references/personalization-and-output.md:1`

## 反模式

- 不推荐来源不明的养生内容。
- 不推荐营销、带货、偏方、秘方。
- 不跳过权威平台直接给社媒结果。
- 不把科普推荐包装成医疗诊断或处方建议。
- 不省略来源链接。
