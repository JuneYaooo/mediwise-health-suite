# Personalization and Output

## 目录

- 个性化推荐
- 输出格式
- 工作流细节

## 个性化推荐

如用户有 `mediwise-health-tracker` 档案，先查看摘要和在用药：

```bash
python3 {baseDir}/../mediwise-health-tracker/scripts/query.py summary --member-id <id>
python3 {baseDir}/../mediwise-health-tracker/scripts/query.py active-medications --member-id <id>
```

推荐示例：

- 有高血压：推荐饮食管理、运动指导、血压监测科普
- 在用二甲双胍：推荐糖尿病用药与血糖监测知识
- 有过敏史：推荐过敏原回避和日常防护内容

## 输出格式

按内容类型分组，每条都带平台和链接：

```text
🔍 关于「高血压」的科普内容：

📹 视频推荐：
1. 标题 — 平台
   🔗 URL

📝 图文推荐：
1. 标题 — 平台
   🔗 URL

📱 社交媒体精选：
1. 标题 — 平台 / 账号信息
   🔗 URL

💡 个性化提示：
- [为什么这些内容和用户相关]
```

## 工作流细节

1. 识别主题和用户真正想看的形式（图文 / 视频 / 社媒）
2. 先查专业平台
3. 再查视频平台
4. 必要时查社媒并严格过滤
5. 对候选内容补抓详情页，确认不是营销或跑题页面
6. 最终按类型分组展示

不要把“科普推荐”写成诊疗建议。
