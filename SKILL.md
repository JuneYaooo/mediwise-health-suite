---
name: mediwise-health-suite
description: "Private local health assistant for Skills-compatible AI agents. Use for personal or family health records, medical files, metrics, medications, reminders, diet, weight, exercise, sleep, health cards, pre-visit summaries, backups, and Apple Health or Gadgetbridge imports. Local SQLite storage is the default; optional cloud features require explicit setup."
---

# MediWise Health Suite

面向支持 Skills 的 AI Agent 的个人本地健康助手：记录、整理和追踪本人及家人的健康数据。支持 Hermes、OpenClaw、Claude Code、Codex、WorkBuddy，以及其他能够加载 Skills、访问本地文件并执行脚本的 Agent 工具。

对用户统一使用产品全名 **MediWise Health Suite**，首次提及后可简称 **MediWise**。`mediwise-health-tracker`、`diet-tracker` 等仅是内部模块 ID，不得作为产品别名。图片汇总能力统一称为“健康记录卡片”，家庭概览版本称为“家庭健康记录卡片”；普通文字查询结果称为“文字健康摘要”，不要与图片卡片混称。

## 核心能力

### ✅ 1. 健康档案 (`mediwise-health-tracker`)
- 成员信息管理：姓名、关系、性别、出生日期、血型
- 基础病史：既往史、过敏史、联系方式、紧急联系人
- 病程记录：门诊、住院、急诊、症状、诊断、检验、影像
- 用药信息：当前在用药、历史用药、停药原因
- 日常指标：血压、血糖、心率、血氧、体温、体重等
- 查询能力：文字健康摘要、时间线、在用药、全家概览
- **就医前摘要**：自动整理病情、既往史、在用药，生成文本/图片/PDF

### ✅ 2. 饮食追踪 (diet-tracker)
- 每餐记录与食物条目管理
- 营养分析：热量、蛋白质、脂肪、碳水、膳食纤维
- 每日/每周营养摘要
- 热量趋势分析

### ✅ 3. 体重管理 (weight-manager)
- 目标设定：减重/增重/维持
- BMI/BMR/TDEE 计算
- 运动记录与消耗追踪
- 身体围度记录
- 热量收支分析
- 达标预测

### ✅ 4. 智能健康监测 (health-monitor) - 按需检查
- 多级阈值告警（info/warning/urgent/emergency）
- 趋势分析与异常检测
- 本地提醒记录：用药、复查、指标测量；到点主动通知依赖当前 Agent 的调度能力

### ✅ 5. 可穿戴数据导入 (wearable-sync)
- Apple Health `export.zip` / `export.xml`：已验证本地导入与去重
- Gadgetbridge SQLite：已验证本地导入与去重，实际指标取决于设备和表结构
- Garmin Connect：实验性，不作为普通用户默认流程
- Huawei、Zepp 云账号、OpenWearables：暂不可用

### ✅ 6. 睡眠追踪 (sleep-tracker)
- 睡眠时长与深睡、浅睡、REM、清醒分期记录
- 每日分析、周趋势与历史查询

## 快速开始

### 安装

不要求普通用户手动安装或运行代码。让具备终端权限的 AI 助手读取下面的安装文档并完成依赖、路径、个人本地模式与验收检查：

<https://github.com/JuneYaooo/mediwise-health-suite>

安装 Agent 进入仓库后必须先读取 `docs/INSTALL_AGENT.md`。

当前公开流程只支持个人本地使用：一个用户可以管理自己和多位家人的档案，不部署到群聊或多人共享服务。不同 Agent 按各自的 Skills 加载机制安装；OpenClaw 的完整适配说明见 `docs/AGENT_SETUP.md`。

### 基本使用

1. **添加家庭成员**
   ```
   "帮我添加一个家庭成员，叫张三，是我爸爸"
   ```

2. **记录健康指标**
   ```
   "帮我记录今天血压 130/85，心率 72"
   ```

3. **生成健康记录卡片**
   ```
   "帮我生成最近 7 天的健康记录卡片"
   ```

4. **饮食记录**
   ```
   "帮我记录今天早餐：牛奶一杯、面包两片、鸡蛋一个"
   ```

5. **体重管理**
   ```
   "帮我设定一个减重目标，从 70kg 减到 65kg"
   ```

6. **就医前准备**
   ```
   "我准备去看医生，帮我整理一下最近的情况"
   ```

## 系统要求

- **Python**: 3.8+
- **Node.js**: 18+
- **SQLite**: 3.x
- **操作系统**: Linux / macOS / Windows
- **Agent**: 能够加载 Skills、访问本地文件并执行脚本
- **OpenClaw（如使用）**: 2026.3.0+
- **Chrome / Chromium**: 生成本地 PNG 健康记录卡片或 PDF 时需要；纯文字记录与查询不需要

## 数据隐私

- **默认本地存储**：所有数据存储在本地 SQLite 数据库，不上传云端
- **可选后端模式**：支持可选的后端 API 模式（需用户主动配置，默认关闭）
- **可选向量搜索**：支持智能查询功能（本地模型优先，可选 API，默认关闭）
- **个人本地使用**：一个用户管理自己和多位家人的独立档案

**重要**：所有云端功能均为可选，需用户主动配置启用。默认配置下，所有数据仅存储在本地。

## 可选环境变量

这些变量由具备本机权限的安装或配置 Agent 管理，不要求普通用户运行命令。公开流程固定使用个人本地模式；详细配置模板见根目录 `.env.example`。

### 多模态视觉模型（可选，用于复杂版面与图表理解）

当前 Agent 能直接读取用户上传的图片或 PDF 时，直接提取并让用户确认，不需要设置任何 `MEDIWISE_VISION_*` 变量。只有当前 Agent 无法读取附件时，才把下列视觉配置作为可选 fallback；本地 PaddleOCR 也可作为普通图片和扫描 PDF 的 fallback。

| 变量名 | 说明 | 推荐值 |
|--------|------|--------|
| `MEDIWISE_VISION_API_KEY` | 视觉模型 API Key（设置即自动启用） | 见下方推荐方案 |
| `MEDIWISE_VISION_PROVIDER` | 提供商名称 | `siliconflow` / `openai` / `ollama` |
| `MEDIWISE_VISION_MODEL` | 模型名称 | 见下方推荐方案 |
| `MEDIWISE_VISION_BASE_URL` | API 地址（OpenAI 兼容接口） | 见下方推荐方案 |

**推荐方案：**

| 方案 | 适用场景 | PROVIDER | MODEL | BASE_URL |
|------|---------|----------|-------|----------|
| 硅基流动 Qwen3.6（**国内首选**） | 国内部署；配置时确认模型支持图片输入，[注册链接](https://cloud.siliconflow.cn/i/MOlLXTYM) | `siliconflow` | `Qwen/Qwen3.6-35B-A3B` | `https://api.siliconflow.cn/v1` |
| 硅基流动 GLM-4.5V | 国内视觉理解备选；配置时确认服务商仍提供该模型 | `siliconflow` | `zai-org/GLM-4.5V` | `https://api.siliconflow.cn/v1` |
| Google Gemini 3.1 Pro（**海外首选**） | 多模态效果强 | `openai` | `gemini-3.1-pro-preview` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| OpenAI GPT-4o | 通用，效果稳定 | `openai` | `gpt-4o` | `https://api.openai.com/v1` |
| 阶跃星辰 Step-1V | 国内备选 | `openai` | `step-1v-32k` | `https://api.stepfun.com/v1` |
| 本地 Ollama | 完全离线，模型标签以本机模型库为准 | `ollama` | `qwen3-vl:8b` | `http://localhost:11434/v1` |

配置 fallback 前必须取得用户明确同意。配置 Agent 应使用项目的 setup 能力保存到 `config.json`，并通过安全的本地凭据输入机制接收 API Key；不得让用户把 Key 发送到聊天中，也不得要求普通用户复制配置命令。不得因附件读取失败而静默启用新的云端服务。

### 纯文本 LLM（可选）

用于结构化提取、快速录入解析。**不设置时自动复用视觉模型**，无需单独配置。

| 变量名 | 说明 |
|--------|------|
| `MEDIWISE_LLM_API_KEY` | 文本模型 API Key |
| `MEDIWISE_LLM_PROVIDER` | 提供商 |
| `MEDIWISE_LLM_MODEL` | 模型名称 |
| `MEDIWISE_LLM_BASE_URL` | API 地址 |

### 其他可选变量

| 变量名 | 用途 | 默认行为 |
|--------|------|----------|
| `MEDIWISE_SINGLE_USER` | 个人本地 Agent 运行模式，由安装 Agent 在实际运行 MediWise 的环境中配置 | 公开安装流程设为 `1` |
| `USDA_API_KEY` | USDA FoodData Central API Key，用于国际食材查询。免费注册：https://api.data.gov/signup/ | 未设置且未安装获授权的本地数据包时，食物查询会明确返回数据源不可用 |
| `OPENFOODFACTS_ENABLED` | 启用 Open Food Facts 包装/品牌食品搜索（ODbL 1.0） | 默认关闭；设为 `1` 才启用 |
| `OPENFOODFACTS_SEARCH_URL` | Open Food Facts 官方 Search-a-licious 查询地址 | `https://search.openfoodfacts.org/search` |
| `MEDIWISE_FOOD_ONLINE_ENABLED` | 在线食物查询总开关 | 未设置时仅使用已显式配置的来源；设为 `0` 强制全部关闭 |
| `MEDIWISE_DATA_DIR` | 覆盖 SQLite 数据库存储目录 | 默认 OS 用户数据目录（Linux: `~/.local/share/mediwise`） |
| `MEDIWISE_MEDICAL_DB_PATH` | 覆盖医疗数据库（medical.db）路径 | 存储在 `MEDIWISE_DATA_DIR` 下 |
| `MEDIWISE_LIFESTYLE_DB_PATH` | 覆盖生活方式数据库（lifestyle.db）路径 | 存储在 `MEDIWISE_DATA_DIR` 下 |

## 安全说明

### 运行时环境

本 skill 同时使用 **Python 3.8+**（业务脚本）和 **Node.js 18+**（action 路由层），两者均需已安装。

### 个人本地使用

- 当前公开版本只面向个人/家庭单机使用，所有成员档案由同一个本地用户管理。
- 安装 Agent 负责启用并验证个人模式，普通用户不需要配置身份参数。
- 不把同一数据目录部署到群聊机器人或多人共享服务。

### 第三方凭据处理

- **凭据绝不经过聊天传递**：API Key、密码等敏感信息只能通过客户端提供的安全本地输入机制进入配置；如果当前客户端没有这种能力，就停止配置。
- **Garmin Connect 密码**：Garmin 当前为实验性接入，不要求普通用户运行认证命令，也不允许在聊天中粘贴密码。
- **视觉/LLM API Key**：配置 Agent 优先写入操作系统 keyring；keyring 不可用时才以 `0600` 权限保存到本机 `config.json` 并输出警告。
- **所有凭据**均保存在本机，不上传到任何远程服务器。

### 可选外部访问（默认关闭）

默认完全离线，以下网络请求仅在用户明确要求、且配置 Agent 完成对应设置后才会发生：

| 显式启用的能力 | 外部主机 | 发送内容 |
|---|---|---|
| 视觉模型 | `api.siliconflow.cn` / Google / OpenAI 等 | 完整图片/PDF 页面内容（base64）+ 提示词；原文件中可能包含姓名、身份证号等 PII |
| USDA | `api.nal.usda.gov` | 食物名称搜索词 |
| Open Food Facts | `search.openfoodfacts.org` | 食物名称搜索词、语言和分页参数；不发送成员、餐次或健康数据 |
| 远程向量搜索 | 用户选择的 Embedding 端点 | 检索文本片段 |
| 后端 API | 用户自配置的端点 | **完整健康记录** — 仅在自托管可信端点使用，不建议指向第三方服务 |

> **set-backend 风险说明**：启用后端 API 后，所有健康记录（病历、指标、用药等）将发送至配置的端点。请仅在完全信任该端点的情况下启用，且优先使用本地或自托管服务。

### 备份文件

`setup.py backup` 会将所有数据库打包为 `.tar.gz`，**包含完整的健康档案**，请妥善保管，不要分享给未授权人员。

新备份使用一致性 SQLite 快照和 SHA-256 manifest，归档权限为 `0600`；恢复前会校验成员白名单、哈希和数据库完整性。输出路径不得与任何源数据库/配置重合；恢复会把归档中的数据库路径规范化到当前数据目录。同一数据目录不允许两个恢复进程并发执行；文件替换、Schema 升级或升级后的完整性检查失败时，会恢复原有配置、数据库及 SQLite sidecar。恢复期间仍须停止服务、定时同步和其他 SQLite 客户端。旧版无 manifest 的官方备份仍可恢复，但无法进行哈希校验。manifest 未签名，能发现损坏或未同步修改，不能抵御攻击者同时重写数据和 manifest。

## 技术架构

- **数据库**: SQLite（`medical.db` 与 `lifestyle.db` 分域存储，兼容旧版 `health.db`）
- **脚本语言**: Python 3.8+
- **Skill 框架**: 支持 Skills 的 AI Agent；OpenClaw 另有 action 路由适配
- **模块化设计**: 6 个 skills（健康档案、饮食、体重、睡眠、监测、可穿戴）
- **可选功能**: 后端 API、向量搜索（默认关闭）

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 免责声明

本工具只提供健康信息的记录、整理、查询、展示、趋势汇总和提醒，不提供诊断、治疗建议、用药建议、营养治疗建议、临床判断或其他医疗指导。只能转述档案中已有的诊断、处方、报告标记和用户设定的阈值；不得根据数据自行给出处理方案。如需医学判断，请咨询专业医疗人员。

---

**关键词**: 健康管理、医疗记录、家庭健康、饮食追踪、体重管理、health management, medical records, family health, diet tracking, weight management
