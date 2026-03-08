# Cycle, Attachments, and Multi-Tenancy

## 目录

- 周期追踪
- 附件管理
- 多租户隔离

## 周期追踪

支持经期和周期性疾病事件记录、预测、提醒与关怀。

### 常用命令

```bash
python3 {baseDir}/scripts/cycle_tracker.py record --member-id <id> --cycle-type menstrual --event-type period_start --date 2025-03-01
python3 {baseDir}/scripts/cycle_tracker.py record --member-id <id> --cycle-type menstrual --event-type period_end --date 2025-03-06
python3 {baseDir}/scripts/cycle_tracker.py predict --member-id <id> --cycle-type menstrual
python3 {baseDir}/scripts/cycle_tracker.py status --member-id <id> --cycle-type menstrual
python3 {baseDir}/scripts/cycle_tracker.py history --member-id <id> --cycle-type menstrual --limit 12
python3 {baseDir}/scripts/reminder.py auto-cycle --member-id <id> --cycle-type menstrual
```

### 返回重点

- `predict`：预计开始时间、平均周期、排卵期、易孕窗、置信度
- `status`：当前阶段、关怀建议

## 附件管理

### 添加与查看

```bash
python3 {baseDir}/scripts/attachment.py add --member-id <id> --file /path/to/report.jpg --category lab_report --description "2025年3月化验单"
python3 {baseDir}/scripts/attachment.py list --member-id <id>
python3 {baseDir}/scripts/attachment.py get --id <attachment_id>
```

### 关联、删除、导出

```bash
python3 {baseDir}/scripts/attachment.py link --attachment-id <id> --record-type lab_result --record-id <record_id>
python3 {baseDir}/scripts/attachment.py unlink --attachment-id <id> --record-type lab_result --record-id <record_id>
python3 {baseDir}/scripts/attachment.py delete --id <attachment_id>
python3 {baseDir}/scripts/attachment.py delete --id <attachment_id> --purge
python3 {baseDir}/scripts/attachment.py get --id <attachment_id> --base64
python3 {baseDir}/scripts/attachment.py serve --port 9120
python3 {baseDir}/scripts/attachment.py get-url --id <attachment_id> --secret <server_secret>
```

### 规则

- 支持分类：`body_photo`、`food_photo`、`medical_image`、`lab_report`、`prescription`、`exercise_photo`、`other`
- 同一成员上传相同文件会按 SHA256 去重
- 文件大小上限 50MB
- 一张附件可关联多条记录

## 多租户隔离

共享机器人实例下，通过 `owner_id` 在成员层做隔离。

### 核心规则

- 添加成员时带 `--owner-id`
- 列出成员时带 `--owner-id`
- 家庭概况、简报、搜索都带 `--owner-id`
- 不传 `--owner-id` 时视为本地 CLI 模式

### 示例

```bash
python3 {baseDir}/scripts/member.py add --name "张三" --relation "本人" --owner-id "qq_12345"
python3 {baseDir}/scripts/member.py list --owner-id "qq_12345"
python3 {baseDir}/scripts/query.py family-overview --owner-id "qq_12345"
python3 {baseDir}/scripts/health_advisor.py briefing --owner-id "qq_12345"
python3 {baseDir}/scripts/query.py search --keyword "高血压" --owner-id "qq_12345"
```

通过 `index.js` 调用时，只要 `inputs` 中带 `owner_id`，路由层会自动追加对应参数。
