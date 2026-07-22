---
name: wearable-sync
description: "Import Apple Health or Gadgetbridge exports into MediWise health records. Garmin is experimental; Huawei, Zepp cloud, and OpenWearables are not user-ready."
---

# MediWise · 可穿戴数据导入 Skill

把用户明确提供的可穿戴导出文件读取、标准化并写入 MediWise 健康指标。当前公开流程只面向个人本地 Agent 环境。

## 可用性分级

| Provider | 状态 | 数据来源 | 说明 |
|---|---|---|---|
| Apple Health | ✅ 已验证 | `export.zip` / `export.xml` | 支持文件检查、导入、标准化与去重 |
| Gadgetbridge | ✅ 已验证 | SQLite 导出数据库 | 只读导入常见活动数据表 |
| Garmin Connect | 🧪 实验性 | 非官方 Garmin Connect 接口 | 没有安全的免代码凭据输入能力时不得引导绑定 |
| Huawei Health Kit | ⛔ 暂不可用 | OAuth API | 授权回调尚未完成 |
| Zepp / 小米云账号 | ⛔ 暂不可用 | 非官方账号接口 | 账号兼容性和凭据处理未达到稳定发布标准 |
| OpenWearables | ⛔ 暂不可用 | 统一 API | 当前是 Stub |

不得因为代码中存在 Provider 类，就把实验性或未完成来源描述成“已支持”。

## 用户交互规则

1. 用户只需要用自然语言提出导入请求并上传导出文件。
2. 不要求普通用户运行 Python、Node.js、Shell、pip 或其他命令。
3. 不在聊天中索要 API Key、账号密码、token 或其他凭据。
4. 一个本地用户可以管理多位家人：只有唯一“本人”档案时可默认本人；出现多位成员后必须按姓名确认目标，不得根据文件内容猜测。
5. 不把当前 MediWise 数据目录用于群聊机器人或多人共享服务。
6. 不修改用户提供的 Apple Health 或 Gadgetbridge 原始文件。
7. 完成后必须报告新增数量、重复跳过数量、实际指标类型和时间范围；不能只回复“同步成功”。

如果 action 返回个人模式未配置、依赖缺失或安装路径错误，应让具备本机访问权限的 AI 助手修复安装，不要把代码命令转交给普通用户。

## Apple Health 导入流程

### 用户侧准备

指导用户在 iPhone 中：

1. 打开“健康”App。
2. 点击右上角头像。
3. 选择“导出所有健康数据”。
4. 保存或上传系统生成的 `export.zip`。

导出包包含敏感健康数据，只能交给用户信任的个人本地 Agent。

### Agent 执行顺序

1. 调用 `resolve-member`：唯一“本人”可默认；有多位成员时按姓名确认，并复述“姓名（身份）”。
2. 确认附件已落到当前 Agent 可读取的本地路径，扩展名为 `.zip` 或 `.xml`。
3. 调用 `device-add`，Provider 使用 `apple_health`。
4. 调用 `device-auth`，把附件本地路径作为 `export_path`。
5. 调用 `device-test` 检查文件。
6. 调用 `sync-device` 导入。
7. 查询该成员本次导入后的健康指标，汇总类型、条数和时间范围。

Apple Health 导出是手动快照，不是实时流。用户再次上传新导出包时可重新导入；系统会按成员、指标类型、测量时间和来源跳过重复记录。

### Apple Health 可识别指标

- 心率、步数、血氧、睡眠
- 体重、身高、体脂
- 血糖、血压
- 活动卡路里

实际导入项以文件内容为准。不得看到 Apple Watch 型号后就声称上述指标全部存在。

## Gadgetbridge 导入流程

### 用户侧准备

此流程只适合已经使用 Gadgetbridge 管理设备的用户。指导用户在 Gadgetbridge App 的“设置”或“数据库管理”中导出数据库，然后上传 `Gadgetbridge` 或 `Gadgetbridge.db` 文件。

设备兼容性以 Gadgetbridge 官方支持列表为准。不要声称所有小米、Amazfit 或华为设备都适用。

### Agent 执行顺序

1. 调用 `resolve-member`：唯一“本人”可默认；有多位成员时按姓名确认，并复述“姓名（身份）”。
2. 确认附件已落到当前 Agent 可读取的本地路径。
3. 调用 `device-add`，Provider 使用 `gadgetbridge`。
4. 调用 `device-auth`，把附件本地路径作为 `export_path`。
5. 调用 `device-test`，确认它是可读取的 SQLite 数据库且包含已知活动数据表。
6. 调用 `sync-device` 导入。
7. 查询该成员本次导入后的健康指标，汇总类型、条数和时间范围。

当前解析器可识别部分常见数据表中的心率、步数、血氧与睡眠活动。具体结果取决于设备型号、Gadgetbridge 版本及导出表结构。

## Garmin 处理规则

Garmin Provider 已有数据获取实现，但依赖非官方 Garmin Connect Web 接口和一次账号认证，无法仅凭仓库内离线测试确认真实账号长期可用。

当前必须遵守：

- 将 Garmin 表述为“实验性接入”，不表述为已验证支持。
- 绝不让用户把 Garmin 密码发到聊天中。
- 不向普通用户展示或要求执行认证命令。
- 当前客户端没有安全的本地凭据输入能力时，明确说明暂时不能绑定并停止。
- 不用环境变量、命令行参数或明文配置绕过安全限制。

## 暂不可用来源

Huawei Health Kit、Zepp / 小米云账号和 OpenWearables 不得进入用户绑定流程：

- Huawei 的 OAuth 回调尚未完成。
- Zepp 对迁移后的小米账号兼容性不足，当前凭据生命周期也不满足稳定发布要求。
- OpenWearables Provider 明确是未实现占位。

用户询问时应直接说明限制，不要让用户尝试未完成的授权流程或调试代码。

## 可调用 Action

| Action | 用途 | 关键参数 |
|---|---|---|
| `device-add` | 为成员登记数据来源 | `member_id`、`provider`、可选 `device_name` |
| `device-list` | 查看成员已登记来源 | `member_id` |
| `device-remove` | 停用已登记来源 | `device_id` |
| `device-auth` | 校验并保存导出文件路径 | `device_id`、`export_path` |
| `device-test` | 检查导出文件是否可读取 | `device_id` |
| `sync-device` | 导入一个来源 | `device_id` |
| `sync-status` | 查看最近同步状态 | `device_id` |
| `sync-history` | 查看导入历史 | `device_id`、可选 `limit` |

这些 Action 由 Agent 调用，不是让用户手动执行的命令。

## 结果与错误说明

成功回复至少包含：

- 数据来源和目标成员。
- 新增条数与重复跳过条数。
- 实际出现的指标类型。
- 最早和最晚记录时间。
- 没有导入到预期指标时的明确说明。

常见失败处理：

| 错误 | 处理方式 |
|---|---|
| 文件不存在 | 检查聊天附件是否已经下载到 Agent 可访问路径 |
| ZIP/XML 不可读 | 说明文件损坏或不是 Apple Health 导出，不继续写库 |
| SQLite 无已知表 | 说明当前 Gadgetbridge 设备/版本表结构尚未适配 |
| 目标成员不明确 | 先列出成员并请用户选择 |
| 个人模式未生效 | 由具备本机权限的 AI 修复当前 Agent 的安装配置 |
| 来源暂不可用 | 如实说明状态，不尝试绕过 |

## 隐私边界

- Apple Health 和 Gadgetbridge 文件在本地读取，原文件不应被修改。
- 导入文件、数据库和同步日志不得提交到 Git、ClawHub 或测试 fixture。
- 只记录处理结果摘要，不在普通日志中输出完整健康数据。
- 云端模型不是解析这两种导出格式的必需条件。

更详细的用户操作文案见 `docs/WEARABLES.md`。
