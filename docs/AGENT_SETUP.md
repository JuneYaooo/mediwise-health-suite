# 健康管理 Agent 配置指南

## 为什么需要独立的健康管理 Agent？

1. **上下文隔离** - 健康数据与日常工作/聊天分开，避免混淆
2. **隐私保护** - 敏感健康信息不会泄露到其他对话
3. **专注体验** - 专门的健康助手，更专业的交互
4. **独立工作区** - 健康档案、Skills 和配置独立管理

## 快速开始

### 方法 1：使用向导（推荐）

```bash
openclaw agents add health
```

向导会引导你完成配置。

### 方法 2：手动配置

编辑 `~/.openclaw/openclaw.json`：

```json5
{
  agents: {
    list: [
      {
        id: "main",
        name: "Main Assistant",
        workspace: "~/.openclaw/workspace",
        default: true,
      },
      {
        id: "health",
        name: "Health Manager",
        workspace: "~/.openclaw/workspace-health",
        agentDir: "~/.openclaw/agents/health/agent",
        identity: {
          name: "健康助手",
          description: "专注于家庭健康管理的 AI 助手"
        },
        model: "anthropic/claude-sonnet-4-5",
        sandbox: {
          mode: "all",   // 隔离健康工作区，不与其他 agent 共享文件系统
          scope: "agent",
        },
        tools: {
          // 最小权限配置（推荐起点，见下方"权限说明"）
          allow: ["exec", "read", "write"],
          deny: ["browser", "sessions_list", "sessions_history"],
        },
      },
    ],
  },
  // ... bindings 见下方方案 A/B/C
}
```

### 权限说明

下表说明每个工具的用途和风险等级，请按需开启：

| 工具 | 是否必需 | 用途 | 风险说明 |
|------|----------|------|----------|
| `exec` | **必需** | 运行健康管理 Python 脚本 | Agent 可执行脚本命令；sandbox 模式可限制影响范围 |
| `read` | **必需** | 读取导出报告、化验单图片 | 限于 workspace 目录内 |
| `write` | 推荐 | 保存就医摘要、导出报告 | 限于 workspace 目录内 |
| `sessions_list` | 可选 | health_memory 功能：检索历史会话 | 可访问该 agent 的历史会话列表 |
| `sessions_history` | 可选 | health_memory 功能：读取历史会话内容 | 可读取该 agent 历史对话全文 |

**推荐做法**：从最小权限（`exec` + `read` + `write`）开始，只在需要 health_memory 功能时才添加 `sessions_list` 和 `sessions_history`。

## 推荐配置方案

### 方案 A：家庭健康群组（推荐）

创建专门的群组用于健康管理（支持 QQ、飞书、企业微信、钉钉、WhatsApp、Telegram 等）：

```json5
{
  agents: {
    list: [
      {
        id: "health",
        name: "Family Health",
        workspace: "~/.openclaw/workspace-health",
        identity: { name: "家庭健康助手" },
        groupChat: {
          mentionPatterns: ["@health", "@健康", "@健康助手"],
        },
      },
    ],
  },
  bindings: [
    // QQ 群组示例
    {
      agentId: "health",
      match: {
        channel: "qq",
        peer: { kind: "group", id: "123456789" },
      },
    },
    // 或飞书群组
    {
      agentId: "health",
      match: {
        channel: "feishu",
        peer: { kind: "group", id: "oc_xxx" },
      },
    },
    // 或企业微信群组
    {
      agentId: "health",
      match: {
        channel: "wecom",
        peer: { kind: "group", id: "wrXXXXXXXX" },
      },
    },
  ],
}
```

**优点**：家人都能访问、上下文完全隔离、可设置提及模式

### 方案 B：个人健康私信

将特定联系人的私信路由到健康 agent：

```json5
{
  bindings: [
    // QQ 私信示例
    {
      agentId: "health",
      match: {
        channel: "qq",
        peer: { kind: "dm", id: "987654321" },
      },
    },
    // 或飞书私信
    {
      agentId: "health",
      match: {
        channel: "feishu",
        peer: { kind: "dm", id: "ou_xxx" },
      },
    },
  ],
}
```

**优点**：完全私密、一对一交互

### 方案 C：多渠道隔离

使用不同渠道分离日常和健康（例如：QQ 用于日常，飞书用于健康管理）：

```json5
{
  agents: {
    list: [
      {
        id: "main",
        workspace: "~/.openclaw/workspace",
        model: "anthropic/claude-sonnet-4-5",
      },
      {
        id: "health",
        workspace: "~/.openclaw/workspace-health",
        model: "anthropic/claude-opus-4-5",
      },
    ],
  },
  bindings: [
    { agentId: "main", match: { channel: "qq" } },
    { agentId: "health", match: { channel: "feishu" } },
  ],
}
```

**优点**：渠道级隔离、可为健康管理使用更强大的模型

## 安装 MediWise Skills

```bash
cd ~/.openclaw/workspace-health
mkdir -p skills
cd skills
git clone https://github.com/JuneYaooo/mediwise-health-suite.git
```

或使用 ClawdHub：

```bash
clawdhub install mediwise-health-suite --agent health
```

## 验证配置

```bash
# 列出所有 agents
openclaw agents list --bindings

# 测试健康 agent
openclaw chat --agent health "帮我添加一个家庭成员"
```

## 数据隔离

系统提供两个层级的数据隔离：

### Agent 级隔离

每个 agent 有独立的：
- **工作区**：`~/.openclaw/workspace-health`
- **会话存储**：`~/.openclaw/agents/health/sessions`
- **认证配置**：`~/.openclaw/agents/health/agent/auth-profiles.json`
- **数据库**：`health.db` 存储在工作区（新版拆分为 `medical.db` / `lifestyle.db`）

### 用户级隔离（群聊场景）

在家庭群组中，系统通过 `owner_id`（发送者的平台 ID）自动隔离不同用户的数据：

```
家庭健康群（QQ 群 123456789）
├── 张三（QQ: 111）→ owner_id="qq_111"
│   ├── 自己的健康档案
│   ├── 爸爸的健康档案
│   └── 妈妈的健康档案
│
├── 李四（QQ: 222）→ owner_id="qq_222"
│   ├── 自己的健康档案
│   └── 老婆的健康档案
│
└── 张三和李四的数据完全隔离，互不可见
```

**工作原理**：
- 群聊中每条消息的发送者 ID 由平台自动提供
- 路由层（`index.js`）自动将发送者 ID 作为 `owner_id` 传给脚本
- 所有查询和写入操作都按 `owner_id` 过滤
- 无需用户手动指定，全程自动

## 安全建议

1. **启用沙箱**：`sandbox.mode: "all"` 隔离健康数据
2. **最小权限**：从 `exec + read + write` 开始，按需添加其他权限（见上方"权限说明"表格）
3. **设置提及模式**：避免在群组中误触发
4. **定期备份**：备份 `~/.openclaw/workspace-health/medical.db` 与 `~/.openclaw/workspace-health/lifestyle.db`
5. **可选功能谨慎开启**：
   - **USDA 食物库**：设置 `USDA_API_KEY` 后才会请求 `api.nal.usda.gov`，否则默认离线
   - **向量搜索**：需手动执行 `setup.py set-embedding` 启用，默认关闭
   - **后端 API**：需手动执行 `setup.py set-backend` 启用，默认关闭

## 使用示例

在健康群组中（QQ、飞书、企微、钉钉等）：

```
用户: @健康 帮我添加一个家庭成员，叫张三，是我爸爸，65岁
助手: 好的，我来帮您添加...

用户: @健康 记录今天血压 130/85，心率 72
助手: 已为您记录今天的健康指标...

用户: @健康 我准备去看医生，帮我整理一下最近的情况
助手: 好的，我先为您生成一份就医前摘要...
```

## 总结

使用独立的健康管理 agent 可以：
- ✅ 完全隔离健康数据和日常对话
- ✅ 提供更专业的健康管理体验
- ✅ 保护隐私，避免数据泄露
- ✅ 灵活配置权限和工具
- ✅ 支持多人共享（家庭群组）

推荐使用**方案 A（家庭健康群组）**，既能保证隔离，又方便家人共同使用。支持 QQ、飞书、企业微信、钉钉等常用渠道。
