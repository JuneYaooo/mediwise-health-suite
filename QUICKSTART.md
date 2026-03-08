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

#### 症状咨询
```
用户："我最近老是头晕"
助手：我来帮您分析一下。请问头晕是什么时候开始的？
```

#### 急救指导
```
用户："有人晕倒了怎么办"
助手：🚨 意识丧失急救步骤：
1️⃣ 立即拨打 120
2️⃣ 检查呼吸和脉搏...
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

### 3. 高级功能

#### 图片识别
```
用户：[发送化验单图片]
用户："帮我识别这张化验单"
助手：我来帮您识别化验单内容...
```

#### 药物安全查询
```
用户："氨氯地平和阿司匹林能一起吃吗？"
助手：让我查询一下这两种药物的相互作用...
```

#### 健康科普
```
用户："高血压是怎么回事？"
助手：让我为您找一些权威的科普内容...
```

#### 可穿戴设备同步
```
用户："帮我同步小米手环的数据"
助手：好的，我来同步您的手环数据...
```

### 4. 常用命令

| 功能 | 示例对话 |
|------|---------|
| 添加成员 | "添加家庭成员" |
| 记录指标 | "记录血压 130/85" |
| 查看摘要 | "最近健康情况" |
| 症状咨询 | "我头晕" |
| 急救指导 | "烫伤怎么办" |
| 饮食记录 | "记录早餐" |
| 体重管理 | "设定减重目标" |
| 就医准备 | "整理就医摘要" |

### 5. 配置（可选）

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

#### Symptom Consultation
```
User: "I've been feeling dizzy lately"
Assistant: Let me help you analyze this. When did the dizziness start?
```

#### First Aid Guidance
```
User: "Someone fainted, what should I do?"
Assistant: 🚨 Loss of consciousness first aid steps:
1️⃣ Call 911 immediately
2️⃣ Check breathing and pulse...
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

### 3. Advanced Features

#### Image Recognition
```
User: [Send lab report image]
User: "Help me recognize this lab report"
Assistant: Let me help you recognize the lab report content...
```

#### Drug Safety Query
```
User: "Can I take Amlodipine and Aspirin together?"
Assistant: Let me check the interaction between these two medications...
```

#### Health Education
```
User: "What is hypertension?"
Assistant: Let me find some authoritative educational content for you...
```

#### Wearable Device Sync
```
User: "Sync my Xiaomi Band data"
Assistant: Okay, let me sync your band data...
```

### 4. Common Commands

| Feature | Example Dialogue |
|---------|-----------------|
| Add Member | "Add family member" |
| Record Metrics | "Record blood pressure 130/85" |
| View Summary | "Recent health status" |
| Symptom Consultation | "I feel dizzy" |
| First Aid | "What to do for burns" |
| Diet Tracking | "Record breakfast" |
| Weight Management | "Set weight loss goal" |
| Doctor Visit Prep | "Organize medical summary" |

### 5. Configuration (Optional)

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
