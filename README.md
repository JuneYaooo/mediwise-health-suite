# MediWise Health Suite - 家庭健康管理套件

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OpenClaw](https://img.shields.io/badge/OpenClaw-Compatible-blue.svg)](https://openclaw.ai)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/Status-Active%20Development-green.svg)]()

**家庭健康管理助手**

从日常记录到健康追踪的完整解决方案

[快速开始](#快速开始) • [功能介绍](#功能介绍) • [安装方法](#安装方法) • [使用示例](#使用示例)

</div>

---

## 📋 简介

MediWise Health Suite 是一个为 OpenClaw AI 设计的家庭健康管理助手。帮助你记录和管理健康数据，追踪饮食和体重，为家庭健康保驾护航。

**核心价值**：平时能记、能查、能追踪；数据本地存储，保护隐私。默认数据库拆分为医疗与生活方式两库，便于隔离与权限控制。

## 🏗 项目架构图（技术设计）

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                           用户 / 聊天入口（OpenClaw）                        │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ action + params + owner_id
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                 Node.js 技能路由层（各 skill 的 index.js）                  │
│  - 路由 action -> script(args)                                               │
│  - 统一 subprocess 调 python3                                                │
│  - 强制 owner_id 并注入 MEDIWISE_OWNER_ID 做多用户隔离                        │
└───────────────┬───────────────────────────────────────────────┬──────────────┘
                │                                               │
                ▼                                               ▼
   ┌─────────────────────────────┐                 ┌─────────────────────────────┐
   │  Health Tracker (Python)    │                 │  其他领域技能 (Python)      │
   │  - member / medical_record  │                 │  - diet-tracker             │
   │  - health_metric / reminder │                 │  - weight-manager           │
   │  - sleep records / reports  │                 │  - sleep-tracker            │
   │  - visit_lifecycle / notes  │                 │  - wearable-sync            │
   │  - checkup/doctor report    │                 │  - health-monitor           │
   └───────────────┬─────────────┘                 └───────────────┬─────────────┘
                   │                                               │
                   └──────────────────────┬────────────────────────┘
                                          ▼
                         ┌─────────────────────────────────┐
                         │      shared 公共层              │
                         │  - path_setup.py                │
                         │  - metric_utils.py              │
                         └─────────────────┬───────────────┘
                                           ▼
                   ┌────────────────────────────────────────────────────┐
                   │         数据访问层：health_db.py（SQLite）          │
                   │  Domain 路由：medical / lifestyle                  │
                   │  事务、审计、owner 校验                             │
                   └───────────────┬──────────────────────┬─────────────┘
                                   │                      │
                                   ▼                      ▼
                     ┌──────────────────────┐   ┌──────────────────────┐
                     │ medical.db           │   │ lifestyle.db         │
                     │ members/visits/...   │   │ diet/weight/wearable │
                     │ health_metrics/...   │   │ sync_log/...         │
                     └──────────────────────┘   └──────────────────────┘

外部集成（可选）：
  - Wearable Provider: gadgetbridge / apple_health / garmin / huawei / zepp / openwearables
  - 视觉识别模型：图片/PDF 走外部模型（通过 setup 配置）
  - Backend API 模式（可切换）
```

## 🗺 项目使用图

```text
[用户发起请求]
      │
      ▼
[确定 owner_id]
      │
      ▼
[先列成员并确认“为哪位成员操作”]
      │
      ├──────────────┐
      │              │
      ▼              ▼
[文本录入]      [图片/PDF录入]
(就诊/症状/用药/指标)  (外部视觉模型识别后写入)
      │              │
      └───────┬──────┘
              ▼
         [落库到 SQLite]
              │
              ├───────────────────────────────┐
              │                               │
              ▼                               ▼
      [饮食/体重管理]                    [可穿戴同步]
      - food_lookup先查再记餐            - 拉取设备数据
      - 热量/营养统计                     - 去重写入 health_metrics
                                          - 自动触发 monitor 检查
              │                               │
              └───────────────┬───────────────┘
                              ▼
                       [监测与提醒/告警]
                              │
                              ▼
                 [健康简报 / 就医前摘要 / 导出]
```

---

## ✨ 功能状态

### ✅ 已实现功能

#### 🏥 健康档案管理
- 家庭成员信息管理
- 病程记录（门诊、住院、急诊）
- 用药追踪与提醒
- 日常健康指标（血压、血糖、心率等）
- 图片识别（化验单、体检报告、处方）
- 就医前摘要生成（文本/图片/PDF）

#### 🍎 饮食追踪
- 饮食记录与营养分析
- 热量计算
- 营养素统计

#### ⚖ 体重管理
- 体重记录与趋势分析
- BMI/BMR/TDEE 计算
- 目标设定与进度追踪

#### 😴 睡眠追踪
- 手动记录睡眠时长和深睡/浅睡/REM/清醒分期
- 每日分析、周趋势与历史查询

### ⚠ 部分实现功能（待完善）

#### 📊 智能监测与提醒（待完善）
- 多级健康告警
- 趋势分析与异常检测
- 用药提醒、复查提醒

#### ⌚ 可穿戴设备同步
- ✅ **佳明（Garmin）**：Garmin Connect 账号直连，支持心率、睡眠分期、HRV、身体电量（Body Battery）、压力、步数、血氧、活动记录
- ✅ **Apple Watch / iPhone**：Health App 导出 export.xml/zip，支持心率、步数、血氧、睡眠、体重、血糖、血压等
- ✅ **小米手环 / Amazfit**：Gadgetbridge 本地 SQLite 导出，支持心率、步数、血氧、睡眠
- 🔜 华为手表、高驰（COROS）等（开发中）

---

## 🚀 快速开始

### 安装

**方式 1：从 GitHub 安装（推荐）**
```bash
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite

cd ~/.openclaw/skills/mediwise-health-suite
python3 -m pip install -r requirements.txt
bash install-check.sh
```

**方式 2：通过 ClawdHub 安装**
```bash
# 从 GitHub 直接安装
clawdhub install JuneYaooo/mediwise-health-suite

# 或从市场安装（审核通过后）
clawdhub install mediwise-health-suite
```

共享实例必须让宿主在每次 action 调用中传入稳定且唯一的 `owner_id`（建议格式 `<channel>:<user_id>`）。仅个人本地实例可设置 `MEDIWISE_SINGLE_USER=1`；否则缺少 owner 的调用会被拒绝。

### 基本使用

安装后，直接与 OpenClaw 对话即可：

```
"帮我添加一个家庭成员，叫张三，是我爸爸"
"帮我记录今天血压 130/85，心率 72"
"帮我看看最近的健康情况"
"记录今天吃了一碗米饭和一份青菜"
"记录今天体重 65kg"
"我准备去看医生，帮我整理一下最近的情况"
```

---

## 💡 使用示例

### 添加家庭成员
```
用户："帮我添加一个家庭成员，叫张三，是我爸爸，65岁"
助手：好的，我来帮您添加...
```

### 记录健康指标
```
用户："帮我记录今天血压 130/85，心率 72"
助手：已为您记录今天的健康指标...
```

### 饮食追踪
```
用户："记录今天吃了一碗米饭和一份青菜"
助手：已为您记录今天的饮食...
```

### 体重管理
```
用户："记录今天体重 65kg"
助手：已记录体重，您的 BMI 是...
```

### 就医前准备
```
用户："我准备去看医生，帮我整理一下最近的情况"
助手：好的，我先为您生成一份就医前摘要...
```

### 绑定佳明手表
```
用户："帮我绑定佳明手表"
助手：好的，请问您的手表型号是？（如 Fenix 7、Forerunner 965 等）
用户："Fenix 7"
助手：请不要在聊天里发送密码。我会生成一条带 `--prompt-password` 的命令，
      请在你自己的终端中交互输入（不回显，也不经过模型或日志）。
用户：[在本机终端完成认证]
助手：验证成功！正在同步近 7 天数据...
       已同步：心率 1240 条、睡眠 7 条、身体电量 2016 条、HRV 7 条
```

---

## 👪 家庭共用场景

### 一家人在同一个群里使用

在 QQ 群、飞书群等群聊中，多个家庭成员可以共同使用同一个健康助手。系统通过发送者身份（如 QQ 号）自动隔离数据，**每个人只能看到和管理自己添加的记录**。

```
张三: @健康 帮我记录今天血压 135/88
助手: 已为您记录血压 135/88。

李四: @健康 帮我看看最近的健康情况
助手: [只显示李四自己的数据，看不到张三的]
```

### 为家人代管健康

每个用户可以为自己和家人创建独立的健康档案：

```
张三: @健康 帮我添加一个家庭成员，叫张爸爸，是我爸爸，65岁
助手: 好的，已添加家庭成员"张爸爸"

张三: @健康 帮张爸爸记录今天血压 150/95
助手: 已为张爸爸记录血压 150/95。收缩压偏高，建议关注。
```

### 隔离机制

| 场景 | 隔离方式 |
|------|---------|
| 不同用户在同一群里 | 自动按发送者身份隔离，互不可见 |
| 同一用户的多个家庭成员 | 通过成员管理区分，用户可切换查看 |
| 不同群聊 | 可配置为同一或不同 Agent，数据独立 |

详细配置方法参见 [Agent 配置指南](docs/AGENT_SETUP.md)。

---

## 📦 包含的功能模块

| 模块 | 状态 | 功能 |
|------|------|------|
| 健康档案 | ✅ 已实现 | 成员管理、病程记录、用药追踪、健康指标 |
| 饮食追踪 | ✅ 已实现 | 饮食记录、营养分析、热量计算 |
| 体重管理 | ✅ 已实现 | 体重记录、BMI/BMR/TDEE 计算、趋势分析 |
| 睡眠追踪 | ✅ 已实现 | 睡眠记录、每日分析、周趋势与历史查询 |
| 健康监测 | ⚠ 待完善 | 智能告警、趋势分析 |
| 可穿戴设备 | ✅ 已实现 | 佳明/Apple Watch/Gadgetbridge 数据同步；HRV、身体电量、睡眠分期 |

---

## 🔒 数据隐私

- ✅ **默认本地存储**：所有数据存储在本地 SQLite 数据库（`medical.db` 与 `lifestyle.db`）
- ✅ **私有文件权限**：数据目录默认 `0700`，数据库、配置、附件与备份默认 `0600`
- ✅ **默认不上传云端**：未启用视觉模型、远程 LLM、Embedding、后端 API 或在线食物来源时，不发送数据到第三方
- ✅ **可选功能**：后端 API、向量搜索等高级功能需用户主动配置启用
- ✅ **多租户隔离**：共享 action 强制要求 `owner_id`，跨 owner 读写会被拒绝
- ✅ **发布安全**：数据库、附件、导出文件默认被 `.gitignore` / `.clawdhubignore` 排除

**重要**：启用云端视觉模型后，完整图片/PDF 页面会发送给所选提供商；原文件可能包含姓名、身份证号、病历号等 PII。敏感材料请使用可信端点或本地 Ollama。食物数据包不随仓库分发：可配置 USDA API Key、显式启用免 Key 的 Open Food Facts，或自行安装来源与授权明确的兼容本地数据包。在线食物 API 只收到搜索词，不会收到成员、餐次或健康记录；设置 `MEDIWISE_FOOD_ONLINE_ENABLED=0` 可强制离线。

### 数据位置与备份

默认数据目录取决于操作系统：macOS 为 `~/Library/Application Support/mediwise`；Linux 在设置 `XDG_DATA_HOME` 时为 `$XDG_DATA_HOME/mediwise`，否则为 `~/.local/share/mediwise`；Windows 为 `%LOCALAPPDATA%\mediwise`。可通过 `MEDIWISE_DATA_DIR` 或两个数据库路径变量覆盖。

```bash
python3 mediwise-health-tracker/scripts/setup.py backup --output ~/mediwise-backup.tar.gz
python3 mediwise-health-tracker/scripts/setup.py restore --input ~/mediwise-backup.tar.gz
```

备份输出不能与数据库或配置文件使用同一路径。恢复时归档内的数据库路径不会被信任，而会统一落到当前 `MEDIWISE_DATA_DIR`，因此迁移到新设备后不会意外写回旧机器上的绝对路径。同一数据目录不允许并发执行两个 restore；文件替换、Schema 升级或升级后完整性检查失败时，会自动恢复原有配置、数据库和 SQLite sidecar。执行 restore 前仍应停止服务、定时同步及其他 SQLite 客户端。

新备份包含 SQLite 一致性快照与 SHA-256 `manifest.json`，恢复前会验证白名单、哈希和数据库完整性；2.0.8 及更早的官方无 manifest 备份仍可恢复，但无法进行哈希校验。manifest 未签名，可发现损坏或未同步修改，但不能抵御攻击者同时重写数据和 manifest。备份含完整健康档案，请按敏感文件保管。

---

## 📋 系统要求

- Python 3.8+
- SQLite 3.x
- OpenClaw 2026.3.0+
- 操作系统：Linux / macOS / Windows

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## ⚠ 免责声明

本工具仅供健康信息记录和参考，不构成医疗建议。任何健康问题请咨询专业医生。

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给个 Star！**

Made with ❤ by MediWise Team

</div>
