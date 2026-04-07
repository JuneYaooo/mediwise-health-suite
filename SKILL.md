---
name: mediwise-health-suite
description: "Family health management suite: health records, diet tracking, weight management, wearable sync. Local SQLite storage by default; optional cloud features require explicit setup."
version: 2.0.7
author: MediWise Team
license: MIT
homepage: https://github.com/JuneYaooo/mediwise-health-suite
repository: https://github.com/JuneYaooo/mediwise-health-suite
keywords:
  - health
  - medical
  - family
  - diet
  - weight
  - records
  - chinese
  - openclaw
requires:
  bins:
    - python3
    - sqlite3
    - node
---

# MediWise Health Suite - 家庭健康管理套件

家庭健康管理助手：记录健康数据，追踪饮食和体重，为家庭健康保驾护航。

## 核心能力

### ✅ 1. 家庭健康档案 (mediwise-health-tracker)
- 成员信息管理：姓名、关系、性别、出生日期、血型
- 基础病史：既往史、过敏史、联系方式、紧急联系人
- 病程记录：门诊、住院、急诊、症状、诊断、检验、影像
- 用药信息：当前在用药、历史用药、停药原因
- 日常指标：血压、血糖、心率、血氧、体温、体重等
- 查询能力：健康摘要、时间线、在用药、全家概览
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

### ⚠ 4. 智能健康监测 (health-monitor) - 待完善
- 多级阈值告警（info/warning/urgent/emergency）
- 趋势分析与异常检测
- 自动提醒：用药提醒、复查提醒、指标测量提醒

### ⚠ 5. 可穿戴设备同步 (wearable-sync) - 待完善
- 支持 Gadgetbridge（小米手环、华为手表等）
- 自动同步：心率、步数、血氧、睡眠
- 可插拔 Provider 架构

## 快速开始

### 安装

> **重要**：OpenClaw 沙箱要求 skills 必须位于插件/agent 工作区目录内。
> `clawhub install` 会安装到**当前目录**的 `skills/` 子目录，
> 因此务必先 `cd` 进入正确的工作区目录再执行安装命令。

**通过 ClawdHub（推荐）：**
```bash
# 先进入 OpenClaw agent 工作区目录（路径以实际配置为准）
cd ~/.openclaw/workspace-health   # 或你的插件根目录

# 再安装，skill 会被放到 ./skills/mediwise-health-suite/
clawdhub install JuneYaooo/mediwise-health-suite
```

**手动安装（路径最明确）：**
```bash
# 直接克隆到正确路径，不受工作目录影响
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/workspace-health/skills/mediwise-health-suite
```

**路径检测工具（装完后验证）：**
```bash
bash ~/.openclaw/workspace-health/skills/mediwise-health-suite/install-check.sh
```

### 基本使用

1. **添加家庭成员**
   ```
   "帮我添加一个家庭成员，叫张三，是我爸爸"
   ```

2. **记录健康指标**
   ```
   "帮我记录今天血压 130/85，心率 72"
   ```

3. **查看健康摘要**
   ```
   "帮我看看最近的健康情况"
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
- **SQLite**: 3.x
- **操作系统**: Linux / macOS / Windows
- **OpenClaw**: 2026.3.0+

## 数据隐私

- **默认本地存储**：所有数据存储在本地 SQLite 数据库，不上传云端
- **可选后端模式**：支持可选的后端 API 模式（需用户主动配置，默认关闭）
- **可选向量搜索**：支持智能查询功能（本地模型优先，可选 API，默认关闭）
- **多租户隔离**：支持共享实例场景的数据隔离

**重要**：所有云端功能均为可选，需用户主动配置启用。默认配置下，所有数据仅存储在本地。

## 可选环境变量

所有功能在不设置任何环境变量的情况下均可正常使用。详细配置模板见根目录 `.env.example`。

### 多模态视觉模型（强烈推荐配置）

用于识别体检报告图片、化验单、病历 PDF。不配置则无法处理图片输入。

| 变量名 | 说明 | 推荐值 |
|--------|------|--------|
| `MEDIWISE_VISION_API_KEY` | 视觉模型 API Key（设置即自动启用） | 见下方推荐方案 |
| `MEDIWISE_VISION_PROVIDER` | 提供商名称 | `siliconflow` / `openai` / `ollama` |
| `MEDIWISE_VISION_MODEL` | 模型名称 | 见下方推荐方案 |
| `MEDIWISE_VISION_BASE_URL` | API 地址（OpenAI 兼容接口） | 见下方推荐方案 |

**推荐方案：**

| 方案 | 适用场景 | PROVIDER | MODEL | BASE_URL |
|------|---------|----------|-------|----------|
| 硅基流动 Qwen2.5-VL（**国内首选**） | 国内部署，价格低，[注册链接](https://cloud.siliconflow.cn/i/MOlLXTYM) | `siliconflow` | `Qwen/Qwen2.5-VL-72B-Instruct` | `https://api.siliconflow.cn/v1` |
| Google Gemini 3.1 Pro（**海外首选**） | 多模态效果强 | `openai` | `gemini-3.1-pro-preview` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| OpenAI GPT-4o | 通用，效果稳定 | `openai` | `gpt-4o` | `https://api.openai.com/v1` |
| 阶跃星辰 Step-1V | 国内备选 | `openai` | `step-1v-32k` | `https://api.stepfun.com/v1` |
| 本地 Ollama | 完全离线 | `ollama` | `qwen2-vl:7b` | `http://localhost:11434/v1` |

也可以用 `setup.py` 命令配置（保存到 `config.json`，环境变量优先级更高）：
```bash
python3 scripts/setup.py set-vision \
  --provider siliconflow \
  --model Qwen/Qwen2.5-VL-72B-Instruct \
  --api-key sk-xxx \
  --base-url https://api.siliconflow.cn/v1
```

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
| `MEDIWISE_OWNER_ID` | 多租户隔离：限定当前进程只能访问该 owner 的数据。**个人/单用户使用时无需设置**；仅在将本工具部署为多人共享服务（如群聊机器人）时才需要为每个用户设置不同值以实现数据隔离 | 未设置时为单用户模式（访问本机全部数据），适合个人或家庭独立部署 |
| `USDA_API_KEY` | USDA FoodData Central API Key，用于国际食材兜底查询。免费注册：https://api.data.gov/signup/ | 未设置时跳过 USDA 查询，使用内置离线数据库 |
| `MEDIWISE_DATA_DIR` | 覆盖 SQLite 数据库存储目录 | 默认 OS 用户数据目录（Linux: `~/.local/share/mediwise`） |
| `MEDIWISE_MEDICAL_DB_PATH` | 覆盖医疗数据库（medical.db）路径 | 存储在 `MEDIWISE_DATA_DIR` 下 |
| `MEDIWISE_LIFESTYLE_DB_PATH` | 覆盖生活方式数据库（lifestyle.db）路径 | 存储在 `MEDIWISE_DATA_DIR` 下 |

## 可选外部网络访问

## 安全说明

### 运行时环境

本 skill 同时使用 **Python 3.8+**（业务脚本）和 **Node.js 18+**（action 路由层），两者均需已安装。

### 数据隔离（多用户部署）

- **个人/家庭单机使用**：无需任何配置，所有数据保存在本机 SQLite 文件中。
- **多用户共享部署**（如群聊机器人）：必须为每个用户传入不同的 `owner_id`（格式 `<channel>:<user_id>`），否则所有用户共享同一份数据库视图。index.js 在 owner_id 缺失时会打印 WARNING 并进入单用户模式。

### 第三方凭据处理

- **凭据绝不经过聊天传递**：所有 API Key、密码等敏感信息必须由用户在本机终端直接输入，agent 不会在对话中索要、接收或代为保存凭据。
- **Garmin Connect 密码**：首次绑定通过终端交互输入（`--prompt-password`，不回显），密码不经过模型或日志。认证成功后自动保存 OAuth token，后续同步无需密码。
- **视觉/LLM API Key**：用户在终端执行 `setup.py set-vision --api-key <key>` 完成配置，key 保存在本机 `config.json`，不会出现在聊天记录中。
- **所有凭据**均保存在本机，不上传到任何远程服务器。

### 可选外部访问（默认关闭）

默认完全离线，以下网络请求**仅在用户主动在终端执行配置命令后**才会发生：

| 触发操作（需用户在终端执行） | 外部主机 | 发送内容 |
|------------------------------|----------|----------|
| `setup.py set-vision` 启用视觉模型 | `api.siliconflow.cn` / Google / OpenAI 等 | 图片 base64 + 提示词（不含姓名/身份证等 PII） |
| `USDA_API_KEY` 环境变量 | `api.nal.usda.gov` | 食物名称搜索词 |
| `setup.py set-embedding` 启用向量搜索 | `api.siliconflow.cn` | 匿名文本片段 |
| `setup.py set-backend` 启用后端 API | 用户自配置的端点 | **完整健康记录** — 仅在自托管可信端点使用，不建议指向第三方服务 |

> **set-backend 风险说明**：启用后端 API 后，所有健康记录（病历、指标、用药等）将发送至配置的端点。请仅在完全信任该端点的情况下启用，且优先使用本地或自托管服务。

### 备份文件

`setup.py backup` 会将所有数据库打包为 `.tar.gz`，**包含完整的健康档案**，请妥善保管，不要分享给未授权人员。

## 技术架构

- **数据库**: SQLite（共享 health.db）
- **脚本语言**: Python 3.8+
- **Skill 框架**: OpenClaw Agent Skills
- **模块化设计**: 5 个 skills（3 个已实现，2 个待完善）
- **可选功能**: 后端 API、向量搜索（默认关闭）

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 免责声明

本工具仅供健康信息记录和参考，不构成医疗建议。任何健康问题请咨询专业医生。

---

**关键词**: 健康管理、医疗记录、家庭健康、饮食追踪、体重管理、health management, medical records, family health, diet tracking, weight management
