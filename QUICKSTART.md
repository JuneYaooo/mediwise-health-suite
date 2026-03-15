# 快速开始指南 - Quick Start Guide

## 中文

### 1. 安装

```bash
# 通过 ClawdHub 安装（推荐）
clawdhub install mediwise-health-suite

# 或手动安装
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite
```

### 2. 基本使用

#### 添加家庭成员
```
用户："帮我添加一个家庭成员，叫张三，是我爸爸，65岁"
助手：好的，我来帮您添加...
```

#### 记录健康指标
```
用户："帮我记录今天血压 130/85，心率 72"
助手：已为您记录今天的健康指标...
```

#### 记录用药
```
用户："我今天开始吃氨氯地平，每天一次，5mg"
助手：已为您记录用药信息...
```

#### 查看健康摘要
```
用户："帮我看看最近的健康情况"
助手：根据最近的记录，您的血压...
```

#### 饮食记录
```
用户："帮我记录今天早餐：牛奶一杯、面包两片、鸡蛋一个"
助手：已为您记录早餐...
```

#### 体重管理
```
用户："帮我设定一个减重目标，从 70kg 减到 65kg"
助手：好的，我来帮您设定减重目标...
```

#### 就医前准备
```
用户："我准备去看医生，帮我整理一下最近的情况"
助手：好的，我先为您生成一份就医前摘要...
```

### 3. 家庭群组使用

在 QQ 群或飞书群中，一家人可以共同使用健康助手，数据自动按发送者隔离：

```
张三: @健康 帮我添加家庭成员"妈妈"，68岁
助手: 已为您添加家庭成员"妈妈"

李四: @健康 帮我记录血压 125/80
助手: 已为您记录血压...

张三: @健康 帮我看看全家的健康情况
助手: [只显示张三的数据，看不到李四的记录]
```

每个用户还可以为家人代管健康档案：

```
张三: @健康 帮妈妈记录今天血糖 6.8
助手: 已为"妈妈"记录空腹血糖 6.8 mmol/L
```

### 4. 高级功能

#### 图片识别

> **前提条件**：需先配置多模态视觉模型，否则图片识别功能不可用。
> 快速配置方法（以硅基流动为例）：
> ```bash
> export MEDIWISE_VISION_PROVIDER=siliconflow
> export MEDIWISE_VISION_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
> export MEDIWISE_VISION_API_KEY=sk-xxx
> export MEDIWISE_VISION_BASE_URL=https://api.siliconflow.cn/v1
> ```
> 详细配置见 `.env.example` 或 [INSTALLATION.md](docs/INSTALLATION.md)。

```
用户：[发送化验单图片]
用户："帮我识别这张化验单"
助手：我来帮您识别化验单内容...
```

#### 体检报告解读

```
用户："帮我解读这张体检报告"
助手：为您解读体检报告，空腹血糖 5.8 mmol/L（正常），甘油三酯 2.1 mmol/L（偏高）...
```

#### 可穿戴设备同步
```
用户："帮我同步小米手环的数据"
助手：好的，我来同步您的手环数据...
```

### 5. 常用命令

| 功能 | 示例对话 |
|------|---------|
| 添加成员 | "添加家庭成员" |
| 记录指标 | "记录血压 130/85" |
| 查看摘要 | "最近健康情况" |
| 饮食记录 | "记录早餐" |
| 体重管理 | "设定减重目标" |
| 就医准备 | "整理就医摘要" |
| 数据备份 | "帮我备份健康数据" |

### 6. 数据备份与迁移

换设备或换 OpenClaw 实例时，可以把全部数据打包带走：

```bash
# 旧环境打包
python3 ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts/setup.py \
  backup --output ~/mediwise-backup.tar.gz

# 新环境恢复（Schema 自动升级）
python3 ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts/setup.py \
  restore --input ~/mediwise-backup.tar.gz
```

详细说明见 [INSTALLATION.md](docs/INSTALLATION.md)。

### 7. 配置（可选）

**视觉模型配置**（图片/PDF 识别必填）：

复制并编辑环境变量文件：

```bash
cp .env.example .env
# 填入 MEDIWISE_VISION_API_KEY 等变量
```

详细配置方案见 [INSTALLATION.md](docs/INSTALLATION.md) 或 `.env.example`。

**OpenClaw 插件配置**（可选）：

编辑 `~/.openclaw/config.json`：

```json
{
  "plugins": {
    "mediwise-health-suite": {
      "enableDailyBriefing": true,
      "reminderCheckInterval": 60000
    }
  }
}
```

---

## English

### 1. Installation

```bash
# Install via ClawdHub (recommended)
clawdhub install mediwise-health-suite

# Or manual installation
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite
```

### 2. Basic Usage

#### Add Family Member
```
User: "Add a family member named John, he's my father, 65 years old"
Assistant: Okay, let me add that for you...
```

#### Record Health Metrics
```
User: "Record today's blood pressure 130/85, heart rate 72"
Assistant: I've recorded your health metrics for today...
```

#### Record Medication
```
User: "I started taking Amlodipine today, once daily, 5mg"
Assistant: I've recorded your medication information...
```

#### View Health Summary
```
User: "Show me my recent health status"
Assistant: Based on recent records, your blood pressure...
```

#### Diet Tracking
```
User: "Record today's breakfast: a glass of milk, two slices of bread, one egg"
Assistant: I've recorded your breakfast...
```

#### Weight Management
```
User: "Set a weight loss goal from 70kg to 65kg"
Assistant: Okay, let me set up your weight loss goal...
```

#### Doctor Visit Preparation
```
User: "I'm preparing to see a doctor, help me organize my recent condition"
Assistant: Okay, let me generate a doctor visit summary for you...
```

### 3. Family Group Usage

In a QQ group or Feishu group, family members can share the same health assistant. Data is automatically isolated by sender identity:

```
Alice: @Health Add a family member "Mom", 68 years old
Assistant: Added family member "Mom" for you.

Bob: @Health Record my blood pressure 125/80
Assistant: Recorded blood pressure for you...

Alice: @Health Show me my family's health overview
Assistant: [Only shows Alice's data, cannot see Bob's records]
```

Each user can also manage health records for their family members:

```
Alice: @Health Record Mom's blood sugar today: 6.8
Assistant: Recorded fasting blood sugar 6.8 mmol/L for "Mom"
```

### 4. Advanced Features

#### Image Recognition

> **Prerequisite**: A multimodal vision model must be configured first. Without it, image recognition is unavailable.
> Quick setup example (SiliconFlow):
> ```bash
> export MEDIWISE_VISION_PROVIDER=siliconflow
> export MEDIWISE_VISION_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
> export MEDIWISE_VISION_API_KEY=sk-xxx
> export MEDIWISE_VISION_BASE_URL=https://api.siliconflow.cn/v1
> ```
> See `.env.example` or [INSTALLATION.md](docs/INSTALLATION.md) for all options.

```
User: [Send lab report image]
User: "Help me recognize this lab report"
Assistant: Let me help you recognize the lab report content...
```

#### Checkup Report Interpretation

```
User: "Help me interpret this health checkup report"
Assistant: Interpreting your checkup report: fasting glucose 5.8 mmol/L (normal), triglycerides 2.1 mmol/L (elevated)...
```

#### Wearable Device Sync
```
User: "Sync my Xiaomi Band data"
Assistant: Okay, let me sync your band data...
```

### 5. Common Commands

| Feature | Example Dialogue |
|---------|-----------------|
| Add Member | "Add family member" |
| Record Metrics | "Record blood pressure 130/85" |
| View Summary | "Recent health status" |
| Diet Tracking | "Record breakfast" |
| Weight Management | "Set weight loss goal" |
| Doctor Visit Prep | "Organize medical summary" |
| Backup Data | "Back up my health data" |

### 6. Data Backup and Migration

When switching devices or OpenClaw instances, you can pack all your data and take it with you:

```bash
# Old environment: create backup
python3 ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts/setup.py \
  backup --output ~/mediwise-backup.tar.gz

# New environment: restore data (schema auto-upgrades)
python3 ~/.openclaw/skills/mediwise-health-suite/mediwise-health-tracker/scripts/setup.py \
  restore --input ~/mediwise-backup.tar.gz
```

See [INSTALLATION.md](docs/INSTALLATION.md) for full details.

### 7. Configuration (Optional)

**Vision model configuration** (required for image/PDF recognition):

Copy and edit the environment variables file:

```bash
cp .env.example .env
# Fill in MEDIWISE_VISION_API_KEY and related variables
```

See [INSTALLATION.md](docs/INSTALLATION.md) or `.env.example` for all configuration options.

**OpenClaw plugin configuration** (optional):

Edit `~/.openclaw/config.json`:

```json
{
  "plugins": {
    "mediwise-health-suite": {
      "enableDailyBriefing": true,
      "reminderCheckInterval": 60000
    }
  }
}
```

---

## 需要帮助？

- 📖 查看完整文档：[docs/](docs/)
- 🐛 报告问题：[GitHub Issues](https://github.com/JuneYaooo/mediwise-health-suite/issues)
- 💬 加入讨论：[GitHub Discussions](https://github.com/JuneYaooo/mediwise-health-suite/discussions)
