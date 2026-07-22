# Cycle, Attachments, and Personal Local Scope

## 目录

- 周期追踪
- 附件管理
- 个人本地运行边界

## 周期追踪

支持经期和周期性事件记录、历史日期估算与提醒。估算只基于已有记录，不预测疾病发作，也不提供健康或用药建议。

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

- `predict`：根据历史记录估算的开始时间、平均周期和置信度
- `status`：当前记录阶段和日期提醒；兼容字段 `care_tips` 始终为空

## 附件管理

### 添加与查看

```bash
python3 {baseDir}/scripts/attachment.py add --member-id <id> --source-path /path/to/report.jpg --category lab_report --description "2025年3月化验单"
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

## 个人本地运行边界

当前公开版本只面向一个本地用户管理本人和多位家人的档案：

- OpenClaw 运行环境必须启用 `MEDIWISE_SINGLE_USER=1`。
- 不把同一数据目录部署到群聊机器人或提供给多人共同访问。
- `owner_id` 仅作为内部兼容参数保留，不是公开的多人共享功能。
- 成员是被当前用户代管的健康对象，不是独立登录用户。
- 只有唯一“本人”档案时可以默认本人；出现多位成员后，写入必须指定姓名。
- 附件、导出和查询都必须先确认目标成员，并用“姓名（身份）”展示。

配置异常应交给具备本机权限的 Agent 处理，不要求普通用户设置身份参数。
