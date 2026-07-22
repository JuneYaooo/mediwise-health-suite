# MediWise 安装与配置指南

> [返回文档中心](README.md) · [快速开始](../QUICKSTART.md)

本指南面向普通用户，所有安装、配置和检查动作都交给具备本机权限的 AI 助手完成。不要手动复制命令，不要在聊天中发送 API Key、密码或真实健康数据。

如果你是负责执行安装的 Agent，请改读 [INSTALL_AGENT.md](INSTALL_AGENT.md)。

## 安装

把下面的简单提示发给 Hermes、OpenClaw、Claude Code、Codex、WorkBuddy，或其他具备终端与网络权限的 AI 助手：

```text
请帮我安装并配置 MediWise Health Suite：
https://github.com/JuneYaooo/mediwise-health-suite
完成后帮我检查 Skill 是否已正确加载并可以正常使用。
```

仓库内的 [INSTALL_AGENT.md](INSTALL_AGENT.md) 已包含安装目录、依赖、个人模式、安全边界和检查步骤，普通用户不需要把这些细节写进提示词。

安装 Agent 应负责：

1. 检查 Git、Python、Node.js，以及当前 Agent 的 Skills 支持情况。
2. 找到当前 Agent 实际加载的 Skills 目录或安装入口。
3. 从 GitHub 仓库完成安装，且不覆盖已有本地修改。
4. 安装项目依赖并运行 `install-check.sh`。
5. 设置并验证个人本地模式。
6. 告诉你是否需要重启或重新加载当前 Agent 的 Skills。

只有检查确实通过后，Agent 才能声称安装完成。

## 运行范围

当前公开安装流程只支持个人本地实例：

- 一个用户可以管理本人和多位家人的独立档案。
- 只有一个本人档案时，可以默认选择本人。
- 创建第二位成员后，写入必须指定姓名，并用“姓名（身份）”确认。
- 不配置群聊机器人，不提供多人共同访问同一数据目录的服务。

如果安装 Agent 检测到目标实例已经用于群聊或多人共享，应停止安装并解释冲突。

OpenClaw 用户可使用项目现有的 workspace、ClawHub、飞书/微信私聊接入和重载说明。Hermes、Claude Code、Codex、WorkBuddy 等工具按各自的 Skills 加载机制安装；只要能够读取根 `SKILL.md` 和六个领域 Skill、访问本地文件并执行脚本，就可以运行 MediWise。

## 图片与 PDF 识别

如果当前 Agent 已经能直接读取图片或 PDF，上传附件即可使用，不需要为 MediWise 再配置一套视觉模型。Skill 应先提取内容、展示给你确认，再写入本地档案。

只有当前 Agent 无法读取附件时，才需要让具备本机权限的配置 Agent 添加本地 OCR 或可选视觉服务：

```text
当前 Agent 无法读取这个附件。请帮我为 MediWise 配置本地 OCR 或可选视觉识别，并用一份脱敏文件测试。
```

配置 fallback 时，结果应区分：

- `PaddleOCR 已可用`：必须以本机测试图片和图像型扫描 PDF 都确实识别成功为依据。
- `PaddleOCR 未启用`：应说明平台、依赖或模型初始化的具体失败原因，基础文本功能仍可使用。
- `视觉模型已可用`：必须用脱敏测试图验证图片输入；要声称同时支持 PDF，还必须通过扫描 PDF 测试，不能只凭模型名称判断。

可选 fallback 示例：

| 方案 | 示例 | 说明 |
|---|---|---|
| 本地 OCR | PaddleOCR | 文字提取在本机完成，不上传原图 |
| 硅基流动 | `Qwen/Qwen3.6-35B-A3B` | 配置时确认服务商当前条目支持图片输入 |
| 硅基流动 | `zai-org/GLM-4.5V` | 视觉理解备选，同样需要现场测试 |
| 本地视觉 | Ollama 中实际可用的 Qwen3-VL 等 | 标签和硬件要求以本机模型库为准 |

不得因为直接读取失败就静默启用新的云端视觉服务。云端视觉端点会收到完整图片或 PDF 页面，只有用户明确选择后才能配置；包含姓名、证件号、病历号等信息的资料应先脱敏。

## 食物营养来源

默认不允许用模型记忆估算营养值并直接写入记录。可选来源包括本地食物数据包、USDA FoodData Central 和 Open Food Facts。

如需联网查询，可以说：

```text
请向我说明 USDA 和 Open Food Facts 会发送哪些数据。得到我确认后，再由你安全配置我选择的来源并执行一次非敏感测试；不要在聊天中收集 API Key。
```

在线食物查询只应发送食物关键词与必要的语言、分页参数，不应发送成员 ID、餐次或健康记录。

完全离线可以说：

```text
请帮我关闭 MediWise 的全部在线食物查询，并确认现在只会使用本地食物数据来源。
```

## 可穿戴数据

当前正式支持 Apple Health 导出文件和 Gadgetbridge 本地 SQLite 文件。用户只需上传文件并说明要导入的成员，Agent 负责格式检查、导入和去重。

Garmin Connect 是实验性来源，不作为普通用户默认配置；Huawei Health Kit、Zepp 云账号和 OpenWearables 当前不可用。详见 [WEARABLES.md](WEARABLES.md)。

## 数据目录与备份

默认数据位置：

| 系统 | 位置 |
|---|---|
| macOS | `~/Library/Application Support/mediwise` |
| Linux | `$XDG_DATA_HOME/mediwise` 或 `~/.local/share/mediwise` |
| Windows | `%LOCALAPPDATA%\mediwise` |

备份可以直接说：

```text
请为 MediWise 创建一个完整备份，保存到我的个人备份目录。完成后告诉我文件位置、完整性校验结果和文件权限，不要上传到第三方。
```

恢复会覆盖现有数据库，因此应先让 Agent 检查归档、停止同步任务，并在替换数据前取得明确确认。

## 验收

让当前 Agent 重新加载 Skills 后，用下面的无敏感数据对话检查能力：

```text
请检查 MediWise 是否已正确加载，但先不要创建任何测试健康记录。告诉我个人本地模式和基础依赖是否正常。
```

随后可以创建本人档案，并请求生成最近 7 天健康记录卡片。没有指标时，卡片应明确显示暂无数据，不应编造内容。

图片/PDF 不是安装成功的前置条件。只有用户要求配置 fallback 时，才需要额外报告 PaddleOCR 或可选视觉服务的实际测试状态。

## 故障处理

把错误原文或截图交给配置 Agent，并要求它读取 [INSTALL_AGENT.md](INSTALL_AGENT.md) 后诊断。Agent 应返回：

- 失败阶段和简短原因。
- 做了哪些安全修复。
- 哪些检查已经重新通过。
- 是否需要重启或重新加载当前 Agent。
- 是否存在未启用的可选能力。

不要为了排障上传真实健康数据库、体检报告、账号凭据或包含个人信息的日志。
