# MediWise Health Suite - 家庭健康管理套件

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OpenClaw Compatible](https://img.shields.io/badge/OpenClaw-Compatible-blue.svg)](https://openclaw.ai)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

**一个完整的家庭健康管理助手**

从日常记录到就医准备的完整健康管理闭环

[快速开始](#快速开始) • [功能介绍](#功能介绍) • [安装方法](#安装方法) • [使用示例](#使用示例)

</div>

---

## 📋 简介

MediWise Health Suite 是一个为 OpenClaw AI 设计的完整家庭健康管理助手。它不仅能记录和管理健康数据，还能在你不舒服时提供症状分诊，在准备就医时自动整理病情摘要。

**核心价值**：平时能记、能查、能提醒；不舒服时能分诊；准备看医生时还能帮你整理就医摘要。

---

## ✨ 主要功能

### 🏥 健康档案管理
- 家庭成员信息管理
- 病程记录（门诊、住院、急诊）
- 用药追踪与提醒
- 日常健康指标（血压、血糖、心率等）
- 图片识别（化验单、体检报告、处方）
- **就医前摘要生成**（文本/图片/PDF）

### 🔍 症状分诊与急救
- 结构化症状问诊
- 危险信号识别
- 可能方向分析与建议科室
- 标准化急救指导（CPR、烫伤、骨折等）

### 🔬 医学搜索与安全
- 药物安全查询（交互、禁忌、不良反应）
- 疾病知识搜索
- 权威来源验证
- 健康科普内容推荐

### 🍎 生活方式管理
- 饮食记录与营养分析
- 体重管理（BMI/BMR/TDEE）
- 运动记录与消耗追踪
- 可穿戴设备数据同步（小米手环、华为手表等）

### 📊 智能监测与提醒
- 多级健康告警
- 趋势分析与异常检测
- 用药提醒、复查提醒
- 每日健康简报

---

## 🚀 快速开始

### 安装

**方式 1：从 GitHub 安装（推荐）**
```bash
git clone https://github.com/JuneYaooo/mediwise-health-suite.git \
  ~/.openclaw/skills/mediwise-health-suite
```

**方式 2：通过 ClawdHub 安装**
```bash
# 从 GitHub 直接安装
clawdhub install JuneYaooo/mediwise-health-suite

# 或从市场安装（审核通过后）
clawdhub install mediwise-health-suite
```

### 基本使用

安装后，直接与 OpenClaw 对话即可：

```
"帮我添加一个家庭成员，叫张三，是我爸爸"
"帮我记录今天血压 130/85，心率 72"
"帮我看看最近的健康情况"
"我最近老是头晕"
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

### 症状咨询
```
用户："我最近老是头晕"
助手：我来帮您分析一下。请问头晕是什么时候开始的？
```

### 急救指导
```
用户："有人晕倒了怎么办"
助手：🚨 意识丧失急救步骤：
1️⃣ 立即拨打 120
2️⃣ 检查呼吸和脉搏...
```

### 就医前准备
```
用户："我准备去看医生，帮我整理一下最近的情况"
助手：好的，我先为您生成一份就医前摘要...
```

---

## 📦 包含的功能模块

| 模块 | 功能 |
|------|------|
| 健康档案 | 成员管理、病程记录、用药追踪 |
| 健康监测 | 智能告警、趋势分析 |
| 医学搜索 | 药物安全、疾病知识 |
| 症状分诊 | 结构化问诊、危险信号识别 |
| 急救指导 | 标准化急救步骤 |
| 多源对比 | 第二意见、交叉验证 |
| 健康科普 | 权威内容推荐 |
| 饮食追踪 | 营养分析、热量管理 |
| 体重管理 | BMI/BMR/TDEE、运动记录 |
| 设备同步 | 可穿戴设备数据导入 |

---

## 🔒 数据隐私

- ✅ 所有数据存储在本地 SQLite 数据库
- ✅ 不上传任何个人健康信息到云端
- ✅ 医学搜索使用公开的权威来源
- ✅ 支持多租户隔离

---

## 📋 系统要求

- Python 3.8+
- SQLite 3.x
- OpenClaw 2026.3.0+
- 操作系统：Linux / macOS / Windows

---

## 📖 文档

- [快速开始指南](QUICKSTART.md) - 详细的使用教程
- [安装指南](docs/INSTALLATION.md) - 完整的安装说明
- [系统概览](docs/HEALTH-MANAGEMENT-OVERVIEW.md) - 功能详解
- [贡献指南](CONTRIBUTING.md) - 如何参与贡献

---

## 🤝 贡献

欢迎贡献代码、报告问题或提出建议！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## ⚠️ 免责声明

本工具仅供健康信息记录和参考，不构成医疗建议。任何健康问题请咨询专业医生。

---

## 📞 联系方式

- GitHub Issues: https://github.com/JuneYaooo/mediwise-health-suite/issues
- GitHub Repo: https://github.com/JuneYaooo/mediwise-health-suite

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给个 Star！**

Made with ❤️ by MediWise Team

</div>
