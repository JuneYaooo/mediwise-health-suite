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

**核心价值**：平时能记、能查、能追踪；数据本地存储，保护隐私。

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

#### ⚖️ 体重管理
- 体重记录与趋势分析
- BMI/BMR/TDEE 计算
- 目标设定与进度追踪

### ⚠️ 部分实现功能（待完善）

#### 📊 智能监测与提醒（待完善）
- 多级健康告警
- 趋势分析与异常检测
- 用药提醒、复查提醒

#### ⌚ 可穿戴设备同步（待完善）
- 小米手环、华为手表等数据同步
- 运动数据导入

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

---

## 📦 包含的功能模块

| 模块 | 状态 | 功能 |
|------|------|------|
| 健康档案 | ✅ 已实现 | 成员管理、病程记录、用药追踪、健康指标 |
| 饮食追踪 | ✅ 已实现 | 饮食记录、营养分析、热量计算 |
| 体重管理 | ✅ 已实现 | 体重记录、BMI/BMR/TDEE 计算、趋势分析 |
| 健康监测 | ⚠️ 待完善 | 智能告警、趋势分析 |
| 可穿戴设备 | ⚠️ 待完善 | 小米手环、华为手表数据同步 |

---

## 🔒 数据隐私

- ✅ **默认本地存储**：所有数据存储在本地 SQLite 数据库
- ✅ **不上传云端**：默认配置下，不上传任何个人健康信息
- ✅ **可选功能**：后端 API、向量搜索等高级功能需用户主动配置启用
- ✅ **多租户隔离**：支持共享实例场景的数据隔离

**重要**：项目包含可选的后端 API 和向量搜索功能，但默认关闭。所有云端功能需用户主动配置才会启用。

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

## ⚠️ 免责声明

本工具仅供健康信息记录和参考，不构成医疗建议。任何健康问题请咨询专业医生。

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给个 Star！**

Made with ❤️ by MediWise Team

</div>
