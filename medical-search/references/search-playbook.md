# Search Playbook

## 目录

- 可信来源与禁用来源
- 查询方式选择
- 网页搜索模板
- DDInter 查询模板
- 两步搜索策略
- 结果验证规则

## 可信来源与禁用来源

### 白名单来源

| 优先级 | 来源 | 域名 | 用途 |
|--------|------|------|------|
| 1 | MSD 诊疗手册 | `msdmanuals.cn` | 疾病知识、药物、患者教育 |
| 2 | 丁香园 / 用药助手 | `dxy.cn`, `drugs.dxy.cn` | 药品信息、中文用药说明 |
| 3 | 国家药监局 | `nmpa.gov.cn` | 说明书、法定信息 |
| 4 | Mayo Clinic | `mayoclinic.org` | 患者教育、疾病知识 |
| 5 | Drugs.com | `drugs.com` | 药物交互、英文补充 |
| 6 | WHO | `who.int` | 疫苗、公共卫生 |
| 7 | CDC | `cdc.gov` | 传染病、疫苗 |
| 8 | 中国疾控 | `chinacdc.cn` | 国内公共卫生 |
| 9 | 医脉通 | `medlive.cn` | 专业医学资讯 |
| 10 | 医学微视 | `mvyxws.com` | 面向患者的医学科普 |

### 禁止采信

- 百度竞价排名和搜索广告
- 不知名健康养生网站
- “偏方”“秘方”“祖传方”类内容
- 莆田系或营销导流页面

## 查询方式选择

| 场景 | 做法 |
|------|------|
| 两种西药交互 | DDInter → 网页验证 |
| 中成药 / 品牌药成分不清 | 先查成分，再查问题 |
| 药物 + 酒精 / 食物 | 直接网页搜索 |
| 禁忌 / 不良反应 / 说明书 | 直接网页搜索 |
| 疾病知识 / 症状原因 | 直接网页搜索 |
| 疫苗 / 传染病 | WHO / CDC / 中国疾控优先 |

## 网页搜索模板

### 基础模板

```bash
curl -s "http://43.156.131.167:4000/search?q=QUERY&format=json&language=zh"
```

### 常见查询词模式

```text
药品说明书 / 禁忌：<药名> 说明书 禁忌 site:msdmanuals.cn OR site:dxy.cn
药物交互：<药A> <药B> 药物相互作用 site:drugs.com OR site:dxy.cn
药物 + 酒精：<药名> 喝酒 禁忌 site:msdmanuals.cn OR site:dxy.cn
疾病知识：<疾病> 症状 治疗 site:msdmanuals.cn OR site:mayoclinic.org
疫苗 / 传染病：<主题> site:who.int OR site:cdc.gov OR site:chinacdc.cn
```

### 结果不足时

- 可以放宽 `site:` 限制做通用搜索。
- 但最终仍只保留白名单域名。

## DDInter 查询模板

如已安装 `mediwise-health-tracker`，优先复用：

```bash
python3 /home/ubuntu/github/openclaw-project/mediwise-health-tracker/scripts/drug_interaction.py check-pair --drug-a "阿司匹林" --drug-b "华法林"
python3 /home/ubuntu/github/openclaw-project/mediwise-health-tracker/scripts/drug_interaction.py search --name "布洛芬"
python3 /home/ubuntu/github/openclaw-project/mediwise-health-tracker/scripts/drug_interaction.py lookup --name "奥美拉唑"
```

## 两步搜索策略

### 何时先查成分

以下情况先确认成分，再回答安全问题：

- 品牌名、商品名
- 中成药
- 不熟悉的中文药名
- 组合制剂

### 路径 A：成分不明

1. 搜“药名 + 说明书 + 成分 + `site:dxy.cn OR site:nmpa.gov.cn`”
2. 确认通用名、主要成分、剂型
3. 再搜“药名/成分 + 用户真正关心的问题”
4. 引用两步里真正命中的来源

### 路径 B：成分明确

1. 直接按问题搜索
2. 取 2-3 个白名单结果交叉验证
3. 页面不足时补充一个英文来源

## 结果验证规则

- 至少保留 2 个可信来源再下结论；高风险问题尽量 3 个。
- 同一来源可多次引用，但编号复用。
- 标题、URL、正文内容要一致，不要张冠李戴。
- 没找到可靠来源时，明确输出“未查到可靠的权威来源，建议咨询医生或药师”。
