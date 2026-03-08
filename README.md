# MediWise Health Suite - 家庭健康管理套件

<div align="center">

[English](#english) | [中文](#中文)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OpenClaw Compatible](https://img.shields.io/badge/OpenClaw-Compatible-blue.svg)](https://openclaw.ai)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

</div>

---

## 中文

### 📋 项目简介

MediWise Health Suite 是一个完整的家庭健康管理助手，专为 OpenClaw AI 助手设计。它不仅能记录和管理健康数据，还能在你不舒服时提供症状分诊，在准备就医时自动整理病情摘要。

**核心价值**：从"随手记录"到"准备就医"的完整健康管理闭环。

### ✨ 核心功能

#### 🏥 健康档案管理
- 家庭成员信息管理
- 病程记录（门诊、住院、急诊）
- 用药追踪与提醒
- 日常健康指标（血压、血糖、心率等）
- 图片识别（化验单、体检报告、处方）
- **就医前摘要生成**（文本/图片/PDF）

#### 🔍 症状分诊与急救
- 结构化症状问诊
- 危险信号识别
- 可能方向分析与建议科室
- 标准化急救指导（CPR、烫伤、骨折等）
- 多源问诊对比（第二意见）

#### 🔬 医学搜索与安全
- 药物安全查询（交互、禁忌、不良反应）
- 疾病知识搜索
- 权威来源验证
- 健康科普内容推荐

#### 🍎 生活方式管理
- 饮食记录与营养分析
- 体重管理（BMI/BMR/TDEE）
- 运动记录与消耗追踪
- 可穿戴设备数据同步（小米手环、华为手表等）

#### 📊 智能监测与提醒
- 多级健康告警（info/warning/urgent/emergency）
- 趋势分析与异常检测
- 用药提醒、复查提醒
- 每日健康简报

### 🚀 快速开始

#### 安装

**方式 1：通过 ClawdHub（推荐）**
```bash
clawdhub install mediwise-health-suite
```

**方式 2：手动安装**
```bash
# 克隆仓库
git clone https://github.com/your-username/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite

# 进入目录
cd ~/.openclaw/skills/mediwise-health-suite

# 安装 Python 依赖（如果有）
pip install -r requirements.txt
```

#### 基本使用示例

```
用户："帮我添加一个家庭成员，叫张三，是我爸爸"
助手：好的，已为您添加家庭成员...

用户："帮我记录今天血压 130/85，心率 72"
助手：已记录您今天的健康指标...

用户："帮我看看最近的健康情况"
助手：根据最近的记录，您的血压...

用户："我最近老是头晕"
助手：我来帮您分析一下。请问头晕是什么时候开始的？

用户："我准备去看医生，帮我整理一下最近的情况"
助手：好的，我先为您生成一份就医前摘要...
```

### 📦 包含的 Skills

| Skill | 功能 |
|-------|------|
| `mediwise-health-tracker` | 核心健康档案管理 |
| `health-monitor` | 智能健康监测与告警 |
| `medical-search` | 医学搜索与药物安全 |
| `symptom-triage` | 症状分诊 |
| `first-aid` | 急救指导 |
| `diagnosis-comparison` | 多源问诊对比 |
| `health-education` | 健康科普 |
| `diet-tracker` | 饮食追踪 |
| `weight-manager` | 体重管理 |
| `wearable-sync` | 可穿戴设备同步 |
| `self-improving-agent` | 自我改进 |

### ⚙️ 配置（可选）

在 OpenClaw 配置文件中添加：

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

### 🔒 数据隐私

- ✅ 所有数据存储在本地 SQLite 数据库
- ✅ 不上传任何个人健康信息到云端
- ✅ 医学搜索使用公开的权威来源
- ✅ 支持多租户隔离

### 📋 系统要求

- Python 3.8+
- SQLite 3.x
- OpenClaw 2026.3.0+
- 操作系统：Linux / macOS / Windows

### 🤝 贡献

欢迎贡献代码、报告问题或提出建议！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

### ⚠️ 免责声明

本工具仅供健康信息记录和参考，不构成医疗建议。任何健康问题请咨询专业医生。

### 📞 联系方式

- GitHub Issues: https://github.com/your-username/mediwise-health-suite/issues
- Email: your-email@example.com

---

## English

### 📋 Project Overview

MediWise Health Suite is a comprehensive family health management assistant designed for OpenClaw AI. It not only records and manages health data but also provides symptom triage when you're unwell and automatically organizes medical summaries when preparing for doctor visits.

**Core Value**: A complete health management loop from "casual recording" to "doctor visit preparation".

### ✨ Key Features

#### 🏥 Health Records Management
- Family member information management
- Medical visit records (outpatient, inpatient, emergency)
- Medication tracking and reminders
- Daily health metrics (blood pressure, blood sugar, heart rate, etc.)
- Image recognition (lab reports, medical reports, prescriptions)
- **Doctor visit summary generation** (text/image/PDF)

#### 🔍 Symptom Triage & First Aid
- Structured symptom assessment
- Red flag detection
- Possible diagnosis directions and department suggestions
- Standardized first aid guidance (CPR, burns, fractures, etc.)
- Multi-source diagnosis comparison (second opinion)

#### 🔬 Medical Search & Safety
- Drug safety queries (interactions, contraindications, side effects)
- Disease knowledge search
- Authoritative source verification
- Health education content recommendations

#### 🍎 Lifestyle Management
- Diet tracking and nutrition analysis
- Weight management (BMI/BMR/TDEE)
- Exercise logging and calorie tracking
- Wearable device data sync (Xiaomi Band, Huawei Watch, etc.)

#### 📊 Smart Monitoring & Reminders
- Multi-level health alerts (info/warning/urgent/emergency)
- Trend analysis and anomaly detection
- Medication reminders, follow-up reminders
- Daily health briefings

### 🚀 Quick Start

#### Installation

**Method 1: Via ClawdHub (Recommended)**
```bash
clawdhub install mediwise-health-suite
```

**Method 2: Manual Installation**
```bash
# Clone the repository
git clone https://github.com/your-username/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite

# Enter directory
cd ~/.openclaw/skills/mediwise-health-suite

# Install Python dependencies (if any)
pip install -r requirements.txt
```

#### Basic Usage Examples

```
User: "Add a family member named John, he's my father"
Assistant: Okay, I've added the family member...

User: "Record today's blood pressure 130/85, heart rate 72"
Assistant: I've recorded your health metrics for today...

User: "Show me my recent health status"
Assistant: Based on recent records, your blood pressure...

User: "I've been feeling dizzy lately"
Assistant: Let me help you analyze this. When did the dizziness start?

User: "I'm preparing to see a doctor, help me organize my recent condition"
Assistant: Okay, let me generate a doctor visit summary for you...
```

### 📦 Included Skills

| Skill | Function |
|-------|----------|
| `mediwise-health-tracker` | Core health records management |
| `health-monitor` | Smart health monitoring and alerts |
| `medical-search` | Medical search and drug safety |
| `symptom-triage` | Symptom triage |
| `first-aid` | First aid guidance |
| `diagnosis-comparison` | Multi-source diagnosis comparison |
| `health-education` | Health education |
| `diet-tracker` | Diet tracking |
| `weight-manager` | Weight management |
| `wearable-sync` | Wearable device sync |
| `self-improving-agent` | Self-improvement |

### ⚙️ Configuration (Optional)

Add to OpenClaw configuration file:

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

### 🔒 Data Privacy

- ✅ All data stored in local SQLite database
- ✅ No personal health information uploaded to cloud
- ✅ Medical searches use public authoritative sources
- ✅ Multi-tenant isolation supported

### 📋 System Requirements

- Python 3.8+
- SQLite 3.x
- OpenClaw 2026.3.0+
- OS: Linux / macOS / Windows

### 🤝 Contributing

Contributions, issues, and feature requests are welcome!

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details

### ⚠️ Disclaimer

This tool is for health information recording and reference only and does not constitute medical advice. Please consult a professional doctor for any health issues.

### 📞 Contact

- GitHub Issues: https://github.com/your-username/mediwise-health-suite/issues
- Email: your-email@example.com
